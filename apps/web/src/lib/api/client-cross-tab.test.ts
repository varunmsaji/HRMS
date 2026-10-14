import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadSession, saveSession } from "@/lib/auth/token-storage";

type Client = (typeof import("@/lib/api/client"))["apiClient"];

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const unauthorised = () =>
  jsonResponse({ error: { code: "INVALID_TOKEN", message: "expired", details: [], request_id: "r" } }, 401);

/**
 * The production policy in miniature. The browser's cookie jar is shared by every tab and is
 * updated only when a refresh *response* arrives; a refresh presents the cookie held when it was
 * sent. Presenting a cookie that is no longer current is a replay and revokes the family.
 */
function strictServer() {
  const server = { accessToken: "access-1", cookie: "c1", n: 1, revoked: false, refreshCalls: 0 };
  const jar = { cookie: "c1" };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/v1/auth/token/refresh")) {
      const presented = jar.cookie; // read at send time
      server.refreshCalls += 1;
      await new Promise((r) => setTimeout(r, 5)); // network + server time
      if (server.revoked || presented !== server.cookie) {
        server.revoked = true;
        return unauthorised();
      }
      server.n += 1;
      server.cookie = `c${server.n}`;
      server.accessToken = `access-${server.n}`;
      jar.cookie = server.cookie; // Set-Cookie applied on response
      return jsonResponse({
        data: {
          access_token: server.accessToken,
          token_type: "Bearer",
          expires_in_minutes: 15,
          company_id: "company-1",
          companies: [],
        },
        meta: { request_id: "r" },
      });
    }
    await Promise.resolve();
    const auth = new Headers(init?.headers).get("Authorization");
    if (server.revoked || auth !== `Bearer ${server.accessToken}`) return unauthorised();
    return jsonResponse({ data: { ok: true }, meta: { request_id: "r" } });
  });
  return { server, fetchMock };
}

/** Minimal exclusive Web Lock shared by every "tab" in this test. */
function installLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, cb: () => Promise<boolean>) => {
        const run = tail.then(cb, cb);
        tail = run.catch(() => undefined);
        return run;
      },
    },
  });
}

async function newTab(): Promise<Client> {
  vi.resetModules(); // a fresh module instance = a separate tab (its own in-flight state)
  return (await import("@/lib/api/client")).apiClient;
}

describe("refresh across browser tabs", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // Both tabs hold access-1 (shared localStorage) ...
    saveSession({ accessToken: "access-1", companyId: "company-1", companies: [], expiresAt: Date.now() + 60_000 });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "locks");
  });

  async function bothTabsHitAnExpiredToken(withLocks: boolean) {
    const { server, fetchMock } = strictServer();
    server.accessToken = "access-0-already-expired-for-the-tabs"; // ... which the server rejects
    vi.stubGlobal("fetch", fetchMock);
    if (withLocks) installLocks();
    const tabA = await newTab();
    const tabB = await newTab();
    const results = await Promise.allSettled([tabA.get("/x"), tabB.get("/x")]);
    return { server, results };
  }

  it("with a cross-tab lock, both tabs recover and the session is not revoked", async () => {
    const { server, results } = await bothTabsHitAnExpiredToken(true);
    expect(results.map((r) => r.status)).toEqual(["fulfilled", "fulfilled"]);
    expect(server.revoked).toBe(false);
    expect(server.refreshCalls).toBe(1); // the second tab saw the renewed shared session
    expect(loadSession()?.accessToken).toBe(server.accessToken);
  });

  it("without Web Locks the old per-tab behaviour is kept: the race looks like a replay", async () => {
    const { server, results } = await bothTabsHitAnExpiredToken(false);
    expect(server.refreshCalls).toBe(2);
    expect(server.revoked).toBe(true);
    expect(results.some((r) => r.status === "rejected")).toBe(true);
  });

  it("a failed refresh under the lock still ends the session in every tab", async () => {
    const { server, fetchMock } = strictServer();
    server.accessToken = "access-0";
    server.revoked = true;
    vi.stubGlobal("fetch", fetchMock);
    installLocks();
    const tabA = await newTab();
    const tabB = await newTab();

    const results = await Promise.allSettled([tabA.get("/x"), tabB.get("/x")]);

    expect(results.every((r) => r.status === "rejected")).toBe(true);
    expect(loadSession()).toBeNull();
  });
});

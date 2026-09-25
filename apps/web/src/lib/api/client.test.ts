import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { loadSession, saveSession, SESSION_EXPIRED_EVENT, type StoredSession } from "@/lib/auth/token-storage";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const SAMPLE_SESSION: StoredSession = {
  accessToken: "access-1",
  companyId: "company-1",
  companies: [],
  expiresAt: Date.now() + 60_000,
};

describe("apiClient", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps a successful DataEnvelope and attaches auth headers", async () => {
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ data: { hello: "world" }, meta: { request_id: "r1" } }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiClient.get<{ hello: string }>("/some/path");

    expect(result).toEqual({ hello: "world" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }];
    expect(init.headers.Authorization).toBe("Bearer access-1");
    expect(init.headers["X-Company-Id"]).toBe("company-1");
  });

  it("throws an ApiError built from the error envelope on a non-2xx response", async () => {
    saveSession(SAMPLE_SESSION);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "CONFLICT", message: "Already exists", details: [], request_id: "r1" } },
          409,
        ),
      ),
    );

    await expect(apiClient.get("/some/path")).rejects.toMatchObject({
      status: 409,
      code: "CONFLICT",
      message: "Already exists",
    });
  });

  it("refreshes once on a 401 and retries the original request", async () => {
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "INVALID_TOKEN", message: "expired", details: [], request_id: "r1" } }, 401),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          data: {
            access_token: "access-2",
            token_type: "Bearer",
            expires_in_minutes: 15,
            company_id: "company-1",
            companies: [],
          },
          meta: { request_id: "r2" },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ data: { ok: true }, meta: { request_id: "r3" } }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiClient.get<{ ok: boolean }>("/protected");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(loadSession()?.accessToken).toBe("access-2");
  });

  it("clears the session and dispatches session-expired when refresh also fails", async () => {
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "INVALID_TOKEN", message: "expired", details: [], request_id: "r1" } }, 401),
      )
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "INVALID_TOKEN", message: "invalid", details: [], request_id: "r2" } }, 401),
      );
    vi.stubGlobal("fetch", fetchMock);

    const expiredHandler = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, expiredHandler);

    await expect(apiClient.get("/protected")).rejects.toBeInstanceOf(ApiError);
    expect(loadSession()).toBeNull();
    expect(expiredHandler).toHaveBeenCalledTimes(1);

    window.removeEventListener(SESSION_EXPIRED_EVENT, expiredHandler);
  });

  it("SEC-06: sends credentials: include so the HttpOnly refresh cookie travels cross-origin", async () => {
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ data: { hello: "world" }, meta: { request_id: "r1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.get<{ hello: string }>("/some/path");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("include");
  });

  it("wraps a fetch rejection (offline/DNS failure) as a NetworkError", async () => {
    saveSession(SAMPLE_SESSION);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new TypeError("network down")));

    await expect(apiClient.get("/some/path")).rejects.toMatchObject({
      status: 0,
      code: "NETWORK_ERROR",
    });
  });
});

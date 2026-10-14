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

  it("keeps the request id it sent on a network failure, so support can find the attempt", async () => {
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiClient.get("/some/path").catch((e: unknown) => e);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const sent = (init.headers as Record<string, string>)["X-Request-Id"];
    expect(error).toMatchObject({ status: 0, code: "NETWORK_ERROR", requestId: sent });
  });

  it("reports OFFLINE when the browser has no connectivity", async () => {
    saveSession(SAMPLE_SESSION);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new TypeError("offline")));
    const onLine = vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);

    await expect(apiClient.get("/some/path")).rejects.toMatchObject({ status: 0, code: "OFFLINE" });
    onLine.mockRestore();
  });

  it("times out a hung request, says a write may have applied, and never retries it", async () => {
    vi.useFakeTimers();
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const pending = apiClient.post("/leave-applications", { a: 1 }, { timeoutMs: 5_000 }).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(5_000);
    const error = await pending;
    vi.useRealTimers();

    expect(error).toMatchObject({ status: 0, code: "REQUEST_TIMEOUT" });
    expect((error as Error).message).toMatch(/may or may not have been saved/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("turns a proxy 502 without a JSON body into a readable, referenced error", async () => {
    saveSession(SAMPLE_SESSION);
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError("not json");
      },
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiClient.get("/some/path").catch((e: unknown) => e);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(error).toMatchObject({
      status: 502,
      code: "SERVICE_UNAVAILABLE",
      requestId: (init.headers as Record<string, string>)["X-Request-Id"],
    });
    expect((error as Error).message).toMatch(/temporarily unavailable/);
  });

  it("prefers the server's request id from the envelope, then the response header", async () => {
    saveSession(SAMPLE_SESSION);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ error: { code: "INTERNAL_ERROR", message: "x", details: [], request_id: "srv-1" } }, 500),
        )
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          headers: new Headers({ "X-Request-Id": "hdr-2" }),
          json: async () => null,
        } as unknown as Response),
    );

    await expect(apiClient.get("/a")).rejects.toMatchObject({ requestId: "srv-1" });
    await expect(apiClient.get("/b")).rejects.toMatchObject({ requestId: "hdr-2" });
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

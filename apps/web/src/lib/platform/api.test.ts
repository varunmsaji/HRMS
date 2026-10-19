import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { clearPlatformSession, loadPlatformSession, platformApi } from "@/lib/platform/api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("platform api client", () => {
  beforeEach(() => {
    clearPlatformSession();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    clearPlatformSession();
  });

  it("stores the platform session after login and sends it as a bearer token", async () => {
    const expiresAt = new Date(Date.now() + 60_000).toISOString();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse(200, { data: { access_token: "tok", expires_at: expiresAt, username: "admin" }, meta: {} }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { data: { counts_by_status: {}, pending_count: 2, oldest_pending_since: null, trials_expiring_within_7_days: 0 }, meta: {} }),
      );

    await platformApi.login("admin", "pw");
    expect(loadPlatformSession()?.username).toBe("admin");

    const dash = await platformApi.dashboard();
    expect(dash.pending_count).toBe(2);
    const init = fetchMock.mock.calls[1]![1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(String(fetchMock.mock.calls[1]![0])).toContain("/v1/platform/dashboard");
  });

  it("parses the standard error envelope, including field details and the request id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(422, {
        error: {
          code: "REQUEST_VALIDATION_ERROR",
          message: "Request validation failed",
          details: [{ field: "body.reason", code: "string_too_short", message: "Too short" }],
          request_id: "req-1",
        },
      }),
    );
    sessionStorage.setItem(
      "hrms.platform.session",
      JSON.stringify({ accessToken: "t", username: "a", expiresAt: new Date(Date.now() + 60_000).toISOString() }),
    );
    const err = await platformApi.act("c1", "reject", {}).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("REQUEST_VALIDATION_ERROR");
    expect(err.requestId).toBe("req-1");
    expect(err.details[0].message).toBe("Too short");
  });

  it("drops the session on a 401 and ignores an expired stored session", async () => {
    sessionStorage.setItem(
      "hrms.platform.session",
      JSON.stringify({ accessToken: "t", username: "a", expiresAt: new Date(Date.now() + 60_000).toISOString() }),
    );
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "INVALID_TOKEN", message: "x", details: [], request_id: "r" } }),
    );
    await expect(platformApi.dashboard()).rejects.toMatchObject({ status: 401 });
    expect(loadPlatformSession()).toBeNull();

    sessionStorage.setItem(
      "hrms.platform.session",
      JSON.stringify({ accessToken: "t", username: "a", expiresAt: new Date(Date.now() - 1000).toISOString() }),
    );
    expect(loadPlatformSession()).toBeNull();
  });
});

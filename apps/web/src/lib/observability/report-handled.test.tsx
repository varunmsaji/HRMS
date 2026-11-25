import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RouteError } from "@/components/common/route-error";
import { ApiError, describeError } from "@/lib/api/errors";
import {
  reportClientError,
  reportHandledError,
  reportedFallback,
  resetReportedErrors,
} from "@/lib/observability/report-client-error";

const server500 = () =>
  new ApiError({
    status: 500,
    code: "INTERNAL_ERROR",
    message: "An unexpected error occurred",
    requestId: "req-1",
    reference: "ERR-1A2B3C4D",
  });

describe("what the user is shown", () => {
  it("describeError: the fallback with no error, the written message for a 4xx, the reference for a 5xx", () => {
    expect(describeError(null, "Pay run not found.")).toBe("Pay run not found.");
    expect(describeError(undefined, "x")).toBe("x");
    const conflict = new ApiError({ status: 409, code: "CONFLICT", message: "Already exists" });
    expect(describeError(conflict, "x")).toBe("Already exists");
    expect(describeError(server500(), "x")).toBe(
      "An unexpected error occurred (Reference: ERR-1A2B3C4D)",
    );
  });

  it("a crashed screen shows a generic line and the reference, never the exception", () => {
    const crash = new TypeError("Cannot read properties of undefined (reading 'salary_minor')");
    Object.assign(crash, { digest: "DIGEST123" });
    render(<RouteError error={crash} reset={() => undefined} />);
    expect(screen.getByRole("alert")).not.toHaveTextContent(/salary_minor|TypeError|undefined/);
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: DIGEST123");
  });

  it("an API failure on a screen shows its safe message and the ERR reference", () => {
    render(<RouteError error={server500()} reset={() => undefined} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "An unexpected error occurred Reference: ERR-1A2B3C4D",
    );
  });

  it("a business error stays useful: a written 4xx message is shown without a reference", () => {
    const denied = new ApiError({
      status: 403,
      code: "PERMISSION_DENIED",
      message: "You do not have permission to do that.",
    });
    render(<RouteError error={denied} reset={() => undefined} />);
    expect(screen.getByRole("alert")).toHaveTextContent("You do not have permission to do that.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Reference");
  });
});

describe("what the developer is told", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    resetReportedErrors();
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const sentBodies = () =>
    fetchMock.mock.calls.map(([, init]) => JSON.parse((init as RequestInit).body as string));

  it("a handled server failure is reported, scrubbed, and does not throw", () => {
    reportHandledError(server500());
    const [body] = sentBodies();
    expect(body).toMatchObject({
      source: "web",
      kind: "handled",
      error_class: "ApiError:500:INTERNAL_ERROR",
      reference: "ERR-1A2B3C4D",
      request_id: "req-1",
    });
    expect(JSON.stringify(body)).not.toMatch(/unexpected error occurred/i);
  });

  it("a bug inside a .then callback is reported without its message", () => {
    reportHandledError(new TypeError("Cannot read properties of undefined (reading 'aadhaar')"));
    const [body] = sentBodies();
    expect(body.error_class).toBe("TypeError");
    expect(JSON.stringify(body)).not.toContain("aadhaar");
  });

  it("expected outcomes are not reported: a 4xx, no connection, a cancelled request", () => {
    reportHandledError(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "x" }));
    reportHandledError(new ApiError({ status: 0, code: "NETWORK_ERROR", message: "x" }));
    reportHandledError(new DOMException("cancelled", "AbortError"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it(".catch(reportedFallback(value)) keeps the screen working and still reports a failure", async () => {
    const value = await Promise.reject(server500()).catch(reportedFallback([] as string[]));
    expect(value).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("the same failure is reported once, and a flood is capped", () => {
    for (let i = 0; i < 5; i++) reportHandledError(server500());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    for (let i = 0; i < 30; i++) {
      const error = new Error("x");
      error.name = `Failure${i}`;
      reportClientError(error, "handled");
    }
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(10);
  });

  it("a rejected report never reaches the page", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    expect(() => reportHandledError(server500())).not.toThrow();
    await Promise.resolve();
  });
});

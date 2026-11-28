import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import {
  buildReport,
  isReportable,
  reportClientError,
  resetReportedErrors,
  topFrames,
} from "@/lib/observability/report-client-error";

describe("client error reports", () => {
  beforeEach(() => resetReportedErrors());

  it("carries the class and code locations, never the message", () => {
    const error = new TypeError("Cannot read properties of undefined (reading 'salary')");
    error.stack = `TypeError: Cannot read properties of undefined (reading 'salary')
    at render (https://app.example.com/_next/static/chunks/page-1.js:10:5)
    at run (https://app.example.com/_next/static/chunks/main-2.js:3:9)`;
    const report = buildReport(error, "render", "/app/employees");
    expect(report.error_class).toBe("TypeError");
    expect(report.frames).toEqual([
      "/_next/static/chunks/page-1.js:10:5",
      "/_next/static/chunks/main-2.js:3:9",
    ]);
    expect(JSON.stringify(report)).not.toContain("salary");
    expect(JSON.stringify(report)).not.toContain("app.example.com");
  });

  it("links an API failure to its reference", () => {
    const error = new ApiError({
      status: 500,
      code: "INTERNAL_ERROR",
      message: "An unexpected error occurred",
      requestId: "r-1",
      reference: "ERR-1A2B3C4D",
    });
    const report = buildReport(error, "handled", "/app");
    expect(report).toMatchObject({ error_class: "ApiError:500:INTERNAL_ERROR", reference: "ERR-1A2B3C4D", request_id: "r-1" });
  });

  it("ignores cancelled requests, expected 4xx and connectivity failures", () => {
    expect(isReportable(new DOMException("x", "AbortError"))).toBe(false);
    expect(isReportable(new ApiError({ status: 409, code: "CONFLICT", message: "x" }))).toBe(false);
    expect(isReportable(new ApiError({ status: 0, code: "NETWORK_ERROR", message: "x" }))).toBe(false);
    expect(isReportable(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "x" }))).toBe(true);
    expect(isReportable(new TypeError("x"))).toBe(true);
  });

  it("never throws, even for odd values", () => {
    expect(() => reportClientError(undefined, "uncaught")).not.toThrow();
    expect(() => reportClientError({ weird: true }, "unhandled_rejection")).not.toThrow();
  });

  it("returns no frames for a missing stack", () => {
    expect(topFrames(undefined)).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";

import type { ErrorDetail } from "@/lib/api/types";
import {
  ApiError,
  describeApiError,
  describeLifecycleError,
  errorReference,
  isRetryableError,
  NetworkError,
} from "@/lib/api/errors";
import { compensationInfoToPayload, validateCompensationInfo } from "@/lib/onboarding/public-wizard";

function apiError(status: number, code: string, message: string, detail?: Partial<ErrorDetail>) {
  return new ApiError({ status, code, message, details: detail ? [detail as ErrorDetail] : [] });
}

describe("describeLifecycleError", () => {
  it("explains a master record that active employees still depend on", () => {
    const err = apiError(409, "MASTER_DATA_HAS_ACTIVE_EMPLOYEES", "blocked", {
      field: "is_active",
      code: "MASTER_DATA_HAS_ACTIVE_EMPLOYEES",
      message: "blocked",
      context: { kind: "branch", active_employee_count: 3 },
    });
    const text = describeLifecycleError(err);
    expect(text).toContain("branch");
    expect(text).toContain("3 active employees are");
    expect(text).toContain("Reassign them first");
  });

  it("uses the singular for a single employee", () => {
    const err = apiError(409, "MASTER_DATA_HAS_ACTIVE_EMPLOYEES", "x", {
      code: "MASTER_DATA_HAS_ACTIVE_EMPLOYEES",
      context: { kind: "grade", active_employee_count: 1 },
    });
    expect(describeLifecycleError(err)).toContain("1 active employee is");
  });

  it("surfaces the inactive-master message", () => {
    const msg = "branch_id references an inactive branch; choose an active one";
    const err = apiError(422, "INACTIVE_MASTER_DATA", msg, { code: "INACTIVE_BRANCH", message: msg });
    expect(describeLifecycleError(err)).toBe(msg);
  });

  it("names the company currency on a compensation currency mismatch", () => {
    const err = apiError(422, "COMPENSATION_CURRENCY_MISMATCH", "m", {
      code: "COMPENSATION_CURRENCY_MISMATCH",
      message: "currency must match the company currency (INR)",
    });
    expect(describeLifecycleError(err)).toContain("(INR)");
  });

  it("falls back to the validation detail, then the message", () => {
    expect(
      describeLifecycleError(apiError(422, "VALIDATION_ERROR", "bad", { code: "x", message: "CTC must be greater than 0" })),
    ).toBe("CTC must be greater than 0");
    expect(describeLifecycleError(apiError(500, "INTERNAL", "boom"))).toBe("boom");
  });
});

describe("onboarding compensation currency", () => {
  it("does not hard-code a currency: blank is omitted so the server uses the company's", () => {
    expect(compensationInfoToPayload({ annualCtc: "1000", currency: "" })).toEqual({
      annual_ctc_minor: 100000,
    });
    expect(compensationInfoToPayload({ annualCtc: "1000", currency: "usd" })).toEqual({
      annual_ctc_minor: 100000,
      currency: "USD",
    });
    expect(validateCompensationInfo({ annualCtc: "1000", currency: "" })).toEqual({});
  });
});

describe("support references and retryability", () => {
  it("adds the reference only to server and connectivity failures", () => {
    const server = new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "An unexpected error occurred", requestId: "r-500" });
    const offline = new NetworkError({ requestId: "r-0" });
    const conflict = new ApiError({ status: 409, code: "CONFLICT", message: "Already exists", requestId: "r-409" });
    const noId = new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" });

    expect(describeApiError(server)).toBe("An unexpected error occurred (Reference: r-500)");
    expect(errorReference(offline)).toBe("r-0");
    expect(describeApiError(conflict)).toBe("Already exists");
    expect(describeApiError(noId)).toBe("Boom");
  });

  it("only treats no-response, gateway and rate-limit failures as retryable", () => {
    const make = (status: number) => new ApiError({ status, code: "X", message: "x" });
    expect(isRetryableError(new NetworkError())).toBe(true);
    expect([502, 503, 504, 429].map((s) => isRetryableError(make(s)))).toEqual([true, true, true, true]);
    expect([400, 401, 403, 409, 422, 500].map((s) => isRetryableError(make(s)))).toEqual([
      false, false, false, false, false, false,
    ]);
    expect(isRetryableError(new Error("x"))).toBe(false);
  });
});

import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { describeDeactivationBlocked } from "./deactivation";

function blocked(code: string, context: Record<string, unknown>): ApiError {
  return new ApiError({
    status: 409,
    code,
    message: "blocked",
    details: [{ field: "is_active", code, message: "blocked", context }],
  });
}

describe("describeDeactivationBlocked", () => {
  it("names the dependent assignments and the next action", () => {
    const text = describeDeactivationBlocked(
      blocked("WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS", {
        active_assignment_count: 3,
        next_action: "Reassign the affected scopes, then deactivate.",
      }),
    );
    expect(text).toBe(
      "It is still used by 3 active or future assignments. Reassign the affected scopes, then deactivate.",
    );
  });

  it("covers a weekly-off pattern that is a work calendar's default", () => {
    const text = describeDeactivationBlocked(
      blocked("WEEKLY_OFF_PATTERN_HAS_ACTIVE_ASSIGNMENTS", {
        active_assignment_count: 1,
        default_for_work_calendars: 2,
      }),
    );
    expect(text).toContain("1 active or future assignment and 2 active work calendars");
    expect(text).toContain("Reassign the affected scopes or end the assignments first");
  });

  it("ignores unrelated errors", () => {
    expect(
      describeDeactivationBlocked(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "x" })),
    ).toBeNull();
  });
});

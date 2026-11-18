import { describe, expect, it } from "vitest";

import {
  NO_SHIFT,
  buildAssignmentCreatePayload,
  emptyAssignmentFormValues,
} from "@/lib/employee/validate-assignment";

describe("buildAssignmentCreatePayload shift field (SH-13)", () => {
  const base = { ...emptyAssignmentFormValues("SHIFT_CHANGE"), effectiveFrom: "2027-08-01" };

  it("a blank shift carries the current shift forward", () => {
    const payload = buildAssignmentCreatePayload({ ...base, shiftId: "" });
    expect(payload.shift_id).toBeNull();
    expect(payload).not.toHaveProperty("clear_shift");
  });

  it("a chosen shift is sent as shift_id", () => {
    const payload = buildAssignmentCreatePayload({ ...base, shiftId: "shift-1" });
    expect(payload.shift_id).toBe("shift-1");
    expect(payload).not.toHaveProperty("clear_shift");
  });

  it('"No shift" is sent as clear_shift, never as a shift id', () => {
    const payload = buildAssignmentCreatePayload({ ...base, shiftId: NO_SHIFT });
    expect(payload.shift_id).toBeNull();
    expect(payload.clear_shift).toBe(true);
  });
});

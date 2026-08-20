import { describe, expect, it } from "vitest";

import {
  buildRegularizationCreatePayload,
  emptyRegularizationFormValues,
  validateRegularizationForm,
} from "@/lib/regularization/validate-regularization";

describe("validateRegularizationForm", () => {
  it("requires an attendance date and a request type", () => {
    const errors = validateRegularizationForm(emptyRegularizationFormValues());
    expect(errors.attendanceDate).toBeDefined();
    expect(errors.requestType).toBeDefined();
  });

  it("requires a shift when correctionKind is SHIFT", () => {
    const errors = validateRegularizationForm(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "WRONG_SHIFT",
        correctionKind: "SHIFT",
      }),
    );
    expect(errors.shiftId).toBeDefined();
  });

  it("requires at least one punch time when correctionKind is PUNCHES", () => {
    const errors = validateRegularizationForm(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "MISSING_PUNCH",
        correctionKind: "PUNCHES",
      }),
    );
    expect(errors.punches).toBeDefined();
  });

  it("accepts a single punch time (IN only)", () => {
    const errors = validateRegularizationForm(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "MISSING_PUNCH",
        correctionKind: "PUNCHES",
        punchInTime: "09:00",
      }),
    );
    expect(errors.punches).toBeUndefined();
  });

  it("does not require a punch time once a shift is chosen", () => {
    const errors = validateRegularizationForm(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "WRONG_SHIFT",
        correctionKind: "SHIFT",
        shiftId: "shift-1",
      }),
    );
    expect(errors.punches).toBeUndefined();
    expect(errors.shiftId).toBeUndefined();
  });
});

describe("buildRegularizationCreatePayload", () => {
  it("builds requested_punches from IN/OUT times, converted from local time to UTC ISO instants (same convention as PunchEntryDialog)", () => {
    const payload = buildRegularizationCreatePayload(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "MISSING_PUNCH",
        correctionKind: "PUNCHES",
        punchInTime: "09:00",
        punchOutTime: "18:00",
        reason: "Forgot to punch",
      }),
    );
    expect(payload.requested_punches).toEqual([
      { direction: "IN", requested_time: new Date("2026-08-10T09:00").toISOString() },
      { direction: "OUT", requested_time: new Date("2026-08-10T18:00").toISOString() },
    ]);
    expect(payload.requested_shift_id).toBeUndefined();
    expect(payload.reason).toBe("Forgot to punch");
  });

  it("omits requested_punches and sends requested_shift_id for a SHIFT correction", () => {
    const payload = buildRegularizationCreatePayload(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "WRONG_SHIFT",
        correctionKind: "SHIFT",
        shiftId: "shift-1",
      }),
    );
    expect(payload.requested_shift_id).toBe("shift-1");
    expect(payload.requested_punches).toBeUndefined();
  });

  it("includes employee_id only when an on-behalf employee is supplied", () => {
    const selfPayload = buildRegularizationCreatePayload(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "MISSING_PUNCH",
        punchInTime: "09:00",
      }),
    );
    expect(selfPayload.employee_id).toBeUndefined();

    const onBehalfPayload = buildRegularizationCreatePayload(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "MISSING_PUNCH",
        punchInTime: "09:00",
      }),
      "employee-1",
    );
    expect(onBehalfPayload.employee_id).toBe("employee-1");
  });

  it("trims a blank reason to undefined rather than sending an empty string", () => {
    const payload = buildRegularizationCreatePayload(
      emptyRegularizationFormValues({
        attendanceDate: "2026-08-10",
        requestType: "MISSING_PUNCH",
        punchInTime: "09:00",
        reason: "   ",
      }),
    );
    expect(payload.reason).toBeUndefined();
  });
});

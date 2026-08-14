import { describe, expect, it } from "vitest";

import type { Shift } from "@/lib/shift/types";
import {
  EMPTY_SHIFT_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  shiftToFormValues,
  validateShiftForm,
} from "@/lib/shift/validate-shift";

const shift: Shift = {
  id: "shift-1",
  company_id: "company-1",
  name: "General Shift",
  code: "GEN",
  start_time: "09:00",
  end_time: "18:00",
  break_minutes_paid: 0,
  break_minutes_unpaid: 30,
  grace_in_minutes: 10,
  grace_out_minutes: 10,
  half_day_threshold_hours: null,
  min_hours_full_day: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateShiftForm", () => {
  it("requires a name, start time, and end time", () => {
    const errors = validateShiftForm(EMPTY_SHIFT_FORM_VALUES);
    expect(errors.name).toBeDefined();
    expect(errors.startTime).toBeDefined();
    expect(errors.endTime).toBeDefined();
  });

  it("treats blank optional fields as valid", () => {
    const errors = validateShiftForm({
      ...EMPTY_SHIFT_FORM_VALUES,
      name: "General Shift",
      startTime: "09:00",
      endTime: "18:00",
    });
    expect(errors).toEqual({});
  });

  it("rejects HH:mm violations", () => {
    const errors = validateShiftForm({
      ...EMPTY_SHIFT_FORM_VALUES,
      name: "General Shift",
      startTime: "9am",
      endTime: "18:00",
    });
    expect(errors.startTime).toBeDefined();
  });

  it("rejects end time before start time when not cross-midnight", () => {
    const errors = validateShiftForm({
      ...EMPTY_SHIFT_FORM_VALUES,
      name: "Bad Shift",
      startTime: "18:00",
      endTime: "09:00",
    });
    expect(errors.endTime).toBeDefined();
  });

  it("allows end time before start time when cross-midnight is set", () => {
    const errors = validateShiftForm({
      ...EMPTY_SHIFT_FORM_VALUES,
      name: "Night Shift",
      startTime: "22:00",
      endTime: "06:00",
      isCrossMidnight: true,
    });
    expect(errors).toEqual({});
  });

  it("rejects min hours for full day below the half-day threshold", () => {
    const errors = validateShiftForm({
      ...EMPTY_SHIFT_FORM_VALUES,
      name: "General Shift",
      startTime: "09:00",
      endTime: "18:00",
      halfDayThresholdHours: "8",
      minHoursFullDay: "4",
    });
    expect(errors.minHoursFullDay).toBeDefined();
  });

  it("allows a min-hours-for-full-day value greater than the half-day threshold", () => {
    const errors = validateShiftForm({
      ...EMPTY_SHIFT_FORM_VALUES,
      name: "General Shift",
      startTime: "09:00",
      endTime: "18:00",
      halfDayThresholdHours: "4",
      minHoursFullDay: "8",
    });
    expect(errors).toEqual({});
  });
});

describe("shiftToFormValues / buildCreatePayload", () => {
  it("round-trips name/code/timings and nulls other optional fields", () => {
    const values = shiftToFormValues(shift);
    expect(values.name).toBe("General Shift");
    expect(values.code).toBe("GEN");
    expect(values.startTime).toBe("09:00");
    expect(values.endTime).toBe("18:00");
    expect(values.halfDayThresholdHours).toBe("");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({
      name: "General Shift",
      code: "GEN",
      start_time: "09:00",
      end_time: "18:00",
      break_minutes_paid: 0,
      break_minutes_unpaid: 30,
      grace_in_minutes: 10,
      grace_out_minutes: 10,
      half_day_threshold_hours: null,
      min_hours_full_day: null,
      is_night_shift: false,
      is_cross_midnight: false,
      is_ot_eligible: false,
    });
  });

  it("converts an empty code to null", () => {
    const values = { ...shiftToFormValues(shift), code: "" };
    const payload = buildCreatePayload(values);
    expect(payload.code).toBeNull();
  });
});

describe("buildUpdatePatch", () => {
  it("returns an empty patch when nothing changed", () => {
    const values = shiftToFormValues(shift);
    expect(buildUpdatePatch(values, shift)).toEqual({});
  });

  it("includes only changed fields", () => {
    const values = shiftToFormValues(shift);
    values.graceInMinutes = "15";
    const patch = buildUpdatePatch(values, shift);
    expect(patch).toEqual({ grace_in_minutes: 15 });
  });

  it("round-trips a half-day threshold value back to the same display", () => {
    const withThreshold: Shift = { ...shift, half_day_threshold_hours: 4.5 };
    const values = shiftToFormValues(withThreshold);
    expect(values.halfDayThresholdHours).toBe("4.5");
    expect(buildUpdatePatch(values, withThreshold)).toEqual({});
  });

  it("nulls out a cleared field", () => {
    const withCode: Shift = { ...shift, code: "GEN" };
    const values = shiftToFormValues(withCode);
    values.code = "";
    const patch = buildUpdatePatch(values, withCode);
    expect(patch).toEqual({ code: null });
  });

  it("includes boolean toggles when changed", () => {
    const values = shiftToFormValues(shift);
    values.isCrossMidnight = true;
    const patch = buildUpdatePatch(values, shift);
    expect(patch).toEqual({ is_cross_midnight: true });
  });
});

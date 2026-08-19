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
  start_time: "00:00",
  end_time: "00:00",
  break_minutes_paid: 0,
  break_minutes_unpaid: 0,
  grace_in_minutes: 0,
  grace_out_minutes: 0,
  half_day_threshold_hours: null,
  min_hours_full_day: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  current_version_id: null,
  draft_version_id: "version-1",
};

describe("validateShiftForm", () => {
  it("requires a name", () => {
    const errors = validateShiftForm(EMPTY_SHIFT_FORM_VALUES);
    expect(errors.name).toBeDefined();
  });

  it("treats a blank code as valid", () => {
    const errors = validateShiftForm({ ...EMPTY_SHIFT_FORM_VALUES, name: "General Shift" });
    expect(errors).toEqual({});
  });
});

describe("shiftToFormValues / buildCreatePayload", () => {
  it("round-trips name/code", () => {
    const values = shiftToFormValues(shift);
    expect(values.name).toBe("General Shift");
    expect(values.code).toBe("GEN");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({ name: "General Shift", code: "GEN" });
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
    values.name = "Renamed Shift";
    const patch = buildUpdatePatch(values, shift);
    expect(patch).toEqual({ name: "Renamed Shift" });
  });

  it("nulls out a cleared code", () => {
    const values = shiftToFormValues(shift);
    values.code = "";
    const patch = buildUpdatePatch(values, shift);
    expect(patch).toEqual({ code: null });
  });
});

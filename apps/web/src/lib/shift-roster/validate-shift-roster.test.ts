import { describe, expect, it } from "vitest";

import type { ShiftRoster } from "@/lib/shift-roster/types";
import {
  buildCreatePayload,
  buildUpdatePatch,
  emptyRosterFormValues,
  rosterToFormValues,
  validateRosterForm,
} from "@/lib/shift-roster/validate-shift-roster";

const baseRoster: ShiftRoster = {
  id: "roster-1",
  company_id: "company-1",
  employee_id: "employee-1",
  roster_date: "2026-08-10",
  shift_id: "shift-1",
  is_week_off_override: false,
  is_holiday_working_override: false,
  status: "DRAFT",
  reason: null,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateRosterForm", () => {
  it("requires an employee and a date", () => {
    const errors = validateRosterForm(emptyRosterFormValues());
    expect(errors.employeeId).toBeDefined();
    expect(errors.rosterDate).toBeDefined();
  });

  it("requires a shift when dayKind is SHIFT", () => {
    const errors = validateRosterForm(
      emptyRosterFormValues({ employeeId: "e1", rosterDate: "2026-08-10", dayKind: "SHIFT" }),
    );
    expect(errors.shiftId).toBeDefined();
  });

  it("does not require a shift for a week-off override", () => {
    const errors = validateRosterForm(
      emptyRosterFormValues({ employeeId: "e1", rosterDate: "2026-08-10", dayKind: "WEEK_OFF" }),
    );
    expect(errors.shiftId).toBeUndefined();
  });
});

describe("buildCreatePayload", () => {
  it("sends shift_id and clears both overrides for a SHIFT day", () => {
    const payload = buildCreatePayload(
      emptyRosterFormValues({
        employeeId: "e1",
        rosterDate: "2026-08-10",
        dayKind: "SHIFT",
        shiftId: "s1",
      }),
    );
    expect(payload).toMatchObject({
      employee_id: "e1",
      roster_date: "2026-08-10",
      shift_id: "s1",
      is_week_off_override: false,
      is_holiday_working_override: false,
    });
  });

  it("clears shift_id and sets is_week_off_override for a WEEK_OFF day", () => {
    const payload = buildCreatePayload(
      emptyRosterFormValues({
        employeeId: "e1",
        rosterDate: "2026-08-10",
        dayKind: "WEEK_OFF",
        shiftId: "s1", // stale selection from a prior SHIFT choice — must not leak through
      }),
    );
    expect(payload.shift_id).toBeNull();
    expect(payload.is_week_off_override).toBe(true);
    expect(payload.is_holiday_working_override).toBe(false);
  });

  it("sets is_holiday_working_override for a HOLIDAY_WORKING day", () => {
    const payload = buildCreatePayload(
      emptyRosterFormValues({
        employeeId: "e1",
        rosterDate: "2026-08-10",
        dayKind: "HOLIDAY_WORKING",
        shiftId: "s1",
      }),
    );
    expect(payload.is_holiday_working_override).toBe(true);
    expect(payload.is_week_off_override).toBe(false);
  });
});

describe("buildUpdatePatch", () => {
  it("always sends both override flags together", () => {
    const patch = buildUpdatePatch(
      emptyRosterFormValues({
        employeeId: "e1",
        rosterDate: "2026-08-10",
        dayKind: "WEEK_OFF",
      }),
    );
    expect(patch.is_week_off_override).toBe(true);
    expect(patch.is_holiday_working_override).toBe(false);
    expect(patch.shift_id).toBeNull();
  });
});

describe("rosterToFormValues", () => {
  it("maps a plain shift row to dayKind SHIFT", () => {
    expect(rosterToFormValues(baseRoster).dayKind).toBe("SHIFT");
  });

  it("maps is_week_off_override to dayKind WEEK_OFF", () => {
    const values = rosterToFormValues({
      ...baseRoster,
      shift_id: null,
      is_week_off_override: true,
    });
    expect(values.dayKind).toBe("WEEK_OFF");
  });

  it("maps is_holiday_working_override to dayKind HOLIDAY_WORKING", () => {
    const values = rosterToFormValues({
      ...baseRoster,
      is_holiday_working_override: true,
    });
    expect(values.dayKind).toBe("HOLIDAY_WORKING");
  });
});

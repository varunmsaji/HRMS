import type { ShiftRosterCreatePayload, ShiftRosterUpdatePayload } from "@/lib/shift-roster/types";

/** Form state for the create/edit roster-entry dialog. `dayKind` collapses the backend's two
 * mutually-exclusive override booleans plus "has a shift" into one radio choice, since a form
 * showing three independent checkboxes would let a user build an invalid combination the
 * backend would reject anyway (`shift_roster_override_exclusive_check`). */
export type RosterDayKind = "SHIFT" | "WEEK_OFF" | "HOLIDAY_WORKING";

export interface RosterFormValues {
  employeeId: string;
  rosterDate: string;
  dayKind: RosterDayKind;
  shiftId: string;
  reason: string;
}

export type RosterFormErrors = Partial<Record<"employeeId" | "rosterDate" | "shiftId", string>>;

export function emptyRosterFormValues(overrides?: Partial<RosterFormValues>): RosterFormValues {
  return {
    employeeId: "",
    rosterDate: "",
    dayKind: "SHIFT",
    shiftId: "",
    reason: "",
    ...overrides,
  };
}

export function rosterToFormValues(roster: {
  employee_id: string;
  roster_date: string;
  shift_id: string | null;
  is_week_off_override: boolean;
  is_holiday_working_override: boolean;
  reason: string | null;
}): RosterFormValues {
  return {
    employeeId: roster.employee_id,
    rosterDate: roster.roster_date,
    dayKind: roster.is_week_off_override
      ? "WEEK_OFF"
      : roster.is_holiday_working_override
        ? "HOLIDAY_WORKING"
        : "SHIFT",
    shiftId: roster.shift_id ?? "",
    reason: roster.reason ?? "",
  };
}

export function validateRosterForm(values: RosterFormValues): RosterFormErrors {
  const errors: RosterFormErrors = {};
  if (!values.employeeId) errors.employeeId = "Choose an employee.";
  if (!values.rosterDate) errors.rosterDate = "Choose a date.";
  if (values.dayKind === "SHIFT" && !values.shiftId) {
    errors.shiftId = "Choose a shift, or pick a week-off / holiday-working override instead.";
  }
  return errors;
}

export function buildCreatePayload(values: RosterFormValues): ShiftRosterCreatePayload {
  return {
    employee_id: values.employeeId,
    roster_date: values.rosterDate,
    shift_id: values.dayKind === "SHIFT" ? values.shiftId : null,
    is_week_off_override: values.dayKind === "WEEK_OFF",
    is_holiday_working_override: values.dayKind === "HOLIDAY_WORKING",
    reason: values.reason.trim() || undefined,
  };
}

/** Diff-only payload for `PATCH /rosters/{id}` — always sends both override flags together
 * since the dialog always knows the full intended `dayKind`, avoiding a partial update that
 * could leave the mutually-exclusive pair inconsistent server-side mid-edit. */
export function buildUpdatePatch(values: RosterFormValues): ShiftRosterUpdatePayload {
  return {
    shift_id: values.dayKind === "SHIFT" ? values.shiftId : null,
    is_week_off_override: values.dayKind === "WEEK_OFF",
    is_holiday_working_override: values.dayKind === "HOLIDAY_WORKING",
    reason: values.reason.trim() || undefined,
  };
}

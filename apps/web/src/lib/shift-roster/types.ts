/** Mirrors `apps/api/src/hrms/modules/attendance/schemas.py::ShiftRosterRead` (W5 —
 * architecture §4.2/§9.7, decision log WD-27). A `PUBLISHED` row for an employee-date outranks
 * `EmployeeAssignment.shift_id` in attendance calculation; `DRAFT` rows never affect a live
 * calculation. */
export interface ShiftRoster {
  id: string;
  company_id: string;
  employee_id: string;
  roster_date: string;
  shift_id: string | null;
  is_week_off_override: boolean;
  is_holiday_working_override: boolean;
  status: "DRAFT" | "PUBLISHED";
  reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export const ROSTER_STATUSES = ["DRAFT", "PUBLISHED"] as const;
export type RosterStatus = (typeof ROSTER_STATUSES)[number];

/** Mirrors `ShiftRosterCreate`. */
export interface ShiftRosterCreatePayload {
  employee_id: string;
  roster_date: string;
  shift_id?: string | null;
  is_week_off_override?: boolean;
  is_holiday_working_override?: boolean;
  reason?: string | null;
}

/** Mirrors `ShiftRosterUpdate` — diff-only PATCH. */
export interface ShiftRosterUpdatePayload {
  shift_id?: string | null;
  is_week_off_override?: boolean;
  is_holiday_working_override?: boolean;
  reason?: string | null;
}

/** Mirrors `ShiftRosterBulkCreate` — an explicit per-date list (fixed/monthly rosters), not a
 * rotation-pattern generator (WD-27); any rotating pattern is expanded into concrete dates by
 * the caller before submission. */
export interface ShiftRosterBulkCreatePayload {
  employee_id: string;
  entries: Array<{
    roster_date: string;
    shift_id?: string | null;
    is_week_off_override?: boolean;
    is_holiday_working_override?: boolean;
  }>;
  reason?: string | null;
}

/** Mirrors `apps/api/src/hrms/modules/attendance/schemas.py` `AttendancePeriod*` (W8 —
 * architecture §4.2/§22, decision log WD-30). Two persisted states only: `OPEN` (mutable,
 * computable) and `CLOSED` (locked — historical attendance in range becomes immutable). There is
 * no separate "open" action — a period is `OPEN` the instant it is created. */

export const ATTENDANCE_PERIOD_STATUSES = ["OPEN", "CLOSED"] as const;
export type AttendancePeriodStatus = (typeof ATTENDANCE_PERIOD_STATUSES)[number];

export const ATTENDANCE_PERIOD_VALIDATION_STATUSES = ["READY", "BLOCKED"] as const;
export type AttendancePeriodValidationStatus =
  (typeof ATTENDANCE_PERIOD_VALIDATION_STATUSES)[number];

export interface AttendancePeriodActionEntry {
  id: string;
  action: "OPENED" | "VALIDATED" | "VALIDATION_FAILED" | "CLOSED" | "REOPENED";
  actor_user_id: string | null;
  comment: string | null;
  created_at: string;
}

export interface AttendancePeriod {
  id: string;
  company_id: string;
  period_start: string;
  period_end: string;
  label: string | null;
  status: AttendancePeriodStatus;

  opened_by_user_id: string | null;
  opened_at: string;

  last_validated_at: string | null;
  last_validation_status: AttendancePeriodValidationStatus | null;

  closed_by_user_id: string | null;
  closed_at: string | null;

  reopened_by_user_id: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;

  version: number;
  actions: AttendancePeriodActionEntry[];
  created_at: string;
  updated_at: string;
}

/** Mirrors `AttendancePeriodCreate`. */
export interface AttendancePeriodCreatePayload {
  period_start: string;
  period_end: string;
  label?: string;
}

/** Mirrors `AttendancePeriodReopenInput`. */
export interface AttendancePeriodReopenPayload {
  reason: string;
}

export const ATTENDANCE_PERIOD_BLOCKING_REASON_LABELS: Record<string, string> = {
  EMPLOYEES_WITHOUT_ATTENDANCE: "Employees missing calculated attendance",
  CONFIG_ERROR: "Unresolved configuration errors",
  INCOMPLETE_ATTENDANCE: "Incomplete attendance requiring manual resolution",
  PENDING_REGULARIZATION: "Pending regularization requests",
  PENDING_OVERTIME_APPROVAL: "Pending overtime approvals",
  UNPUBLISHED_ROSTER: "Unpublished (DRAFT) roster entries",
};

export interface AttendancePeriodBlockingReason {
  code: string;
  message: string;
  count: number;
  sample: string[];
}

/** Mirrors `AttendancePeriodValidationRead`. */
export interface AttendancePeriodValidation {
  status: AttendancePeriodValidationStatus;
  reasons: AttendancePeriodBlockingReason[];
  validated_at: string;
}

/** Mirrors `AttendancePeriodSummaryRead` — a live, unpersisted preview while `OPEN`
 * (`frozen: false`), the payroll-facing frozen snapshot once `CLOSED` (`frozen: true`). */
export interface AttendancePeriodSummaryRow {
  employee_id: string;
  present_days: string;
  absent_days: string;
  leave_days: string;
  holiday_days: string;
  weekly_off_days: string;
  half_days: string;
  lop_days: string;
  ot_minutes_normal: number;
  ot_minutes_weekly_off: number;
  ot_minutes_holiday: number;
  ot_minutes_night: number;
  comp_off_minutes_earned: number;
  late_count: number;
  worked_minutes_total: number;
  generated_at: string;
  frozen: boolean;
}

export const ATTENDANCE_PERIOD_STATUS_LABELS: Record<AttendancePeriodStatus, string> = {
  OPEN: "Open",
  CLOSED: "Closed & locked",
};

export const ATTENDANCE_PERIOD_ACTION_LABELS: Record<
  AttendancePeriodActionEntry["action"],
  string
> = {
  OPENED: "Period opened",
  VALIDATED: "Validated — ready to finalize",
  VALIDATION_FAILED: "Validation blocked",
  CLOSED: "Finalized and locked",
  REOPENED: "Reopened",
};

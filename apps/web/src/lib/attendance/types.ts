/** Mirrors `hrms.modules.attendance.schemas` (W4) — Punch and AttendanceDay shapes only.
 * Policy schemas already live in `lib/attendance-policy/types.ts` (W3). */

export const PUNCH_DIRECTIONS = ["IN", "OUT"] as const;
export type PunchDirection = (typeof PUNCH_DIRECTIONS)[number];

export const PUNCH_SOURCES = ["WEB", "MOBILE", "DEVICE", "IMPORT", "ADMIN", "API"] as const;
export type PunchSource = (typeof PUNCH_SOURCES)[number];

export interface Punch {
  id: string;
  company_id: string;
  employee_id: string;
  punch_time: string;
  direction: PunchDirection;
  source: PunchSource;
  idempotency_key: string | null;
  recorded_by_user_id: string | null;
  reference: string | null;
  created_at: string;
}

export interface PunchCreateInput {
  employee_id?: string;
  punch_time?: string;
  direction: PunchDirection;
  source?: PunchSource;
  reference?: string;
  idempotency_key?: string;
}

/** `attendance_day.attendance_status` — architecture §17/WD-07. Late/OT/regularized are
 * separate boolean flags on the row, not folded into this enum. */
export const ATTENDANCE_STATUSES = [
  "NOT_JOINED",
  "EXITED",
  "NOT_EXPECTED",
  "PRESENT",
  "HALF_DAY",
  "ABSENT",
  "LEAVE",
  "ON_DUTY",
  "WFH",
  "INCOMPLETE",
  "CONFIG_ERROR",
] as const;
export type AttendanceStatus = (typeof ATTENDANCE_STATUSES)[number];

/** `work_calendar` day classification (W1, `organisation.calendar_resolution`) — carried onto
 * the day so OT/payroll can read it without re-resolving the calendar. */
export const CALENDAR_DAY_TYPES = [
  "WORKING",
  "WEEKLY_OFF",
  "HOLIDAY",
  "SPECIAL_WORKING",
  "SHUTDOWN",
] as const;
export type CalendarDayType = (typeof CALENDAR_DAY_TYPES)[number];

export interface AttendanceBreak {
  id: string;
  attendance_day_id: string;
  shift_break_id: string | null;
  break_start: string | null;
  break_end: string | null;
  minutes: number;
  is_paid: boolean;
  is_excess: boolean;
}

export interface AttendanceDay {
  id: string;
  company_id: string;
  employee_id: string;
  attendance_date: string;
  timezone: string;

  shift_id: string | null;
  shift_version_id: string | null;
  work_calendar_id: string | null;
  attendance_policy_version_id: string | null;
  overtime_policy_version_id: string | null;
  regularization_policy_version_id: string | null;

  calendar_day_type: CalendarDayType | null;
  holiday_name: string | null;
  holiday_on_weekly_off: boolean;

  scheduled_start: string | null;
  scheduled_end: string | null;
  scheduled_minutes: number | null;

  actual_first_in: string | null;
  actual_last_out: string | null;
  worked_minutes: number;
  unpaid_break_minutes: number;
  paid_break_minutes: number;
  excess_break_minutes: number;

  attendance_status: AttendanceStatus;
  late_minutes: number;
  early_departure_minutes: number;
  late_classification: string | null;
  early_departure_classification: string | null;
  missing_punch: boolean;
  auto_closed: boolean;

  is_late: boolean;
  is_early_out: boolean;
  is_overtime: boolean;
  is_regularized: boolean;
  is_pending_approval: boolean;
  worked_on_holiday: boolean;
  worked_on_weekly_off: boolean;
  work_on_leave_flagged: boolean;
  /** BUS-012 — `KEEP_LEAVE` once HR confirmed the leave stands over the punches. */
  work_on_leave_resolution: "KEEP_LEAVE" | null;
  work_on_leave_resolution_reason: string | null;
  work_on_leave_resolved_by: string | null;
  work_on_leave_resolved_at: string | null;
  is_core_hours_breach: boolean;
  on_duty: boolean;
  on_duty_regularization_id: string | null;

  paid_day_fraction: string;
  leave_fraction: string;
  weekly_off_fraction: string;
  unpaid_off_fraction: string;
  lop_fraction: string;

  ot_minutes_detected: number;
  ot_minutes_approved: number;
  ot_pending: boolean;
  ot_classification: string | null;
  ot_day_class: string | null;
  comp_off_minutes_earned: number;

  calculation_version: number;
  computation_snapshot: Record<string, unknown> | null;
  calculated_at: string | null;

  is_locked: boolean;
  locked_at: string | null;
  locked_by: string | null;

  breaks: AttendanceBreak[];

  created_at: string;
  updated_at: string;
}

/** Labels + tone for `attendance_status` badges — display-only, not a second source of truth. */
export const ATTENDANCE_STATUS_LABELS: Record<AttendanceStatus, string> = {
  NOT_JOINED: "Not joined",
  EXITED: "Exited",
  NOT_EXPECTED: "Not expected",
  PRESENT: "Present",
  HALF_DAY: "Half day",
  ABSENT: "Absent",
  LEAVE: "On leave",
  ON_DUTY: "On duty",
  WFH: "WFH",
  INCOMPLETE: "Incomplete",
  CONFIG_ERROR: "Config error",
};

export type FaceProfileStatus = "PENDING_APPROVAL" | "ENROLLED" | "REJECTED" | "REVOKED";

/** A face profile — enrollment and review state only, never biometric data. */
export interface FaceProfile {
  id: string;
  employee_id: string;
  provider: string;
  status: FaceProfileStatus;
  reference_photo_count: number;
  consent_recorded_at: string;
  enrolled_at: string;
  enrolled_by_user_id: string | null;
  has_review_photo: boolean;
  reviewed_at: string | null;
  reviewed_by_user_id: string | null;
  review_note: string | null;
  revoked_at: string | null;
  revoked_by_user_id: string | null;
}

/** A one-time, HR-opened window in which the employee self-enrolls from the mobile app. */
export interface FaceEnrollmentWindow {
  id: string;
  employee_id: string;
  status: "OPEN" | "USED" | "CANCELLED" | "EXPIRED";
  opened_by_user_id: string | null;
  opened_at: string;
  expires_at: string;
}

/** `GET /v1/attendance/face-profiles/{employee_id}/enrollment`. `open_window` is set only while
 * a window is OPEN and unexpired. */
export interface FaceEnrollmentStatus {
  profile: FaceProfile | null;
  open_window: FaceEnrollmentWindow | null;
}

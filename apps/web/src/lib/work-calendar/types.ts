/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::WorkCalendarRead`. */
export interface WorkCalendar {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  description: string | null;
  weekly_off_pattern_id: string | null;
  restricted_holidays_are_off_by_default: boolean;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  holiday_calendar_ids: string[];
}

/** Mirrors `CalendarExceptionRead`. */
export interface CalendarException {
  id: string;
  company_id: string;
  work_calendar_id: string;
  exception_date: string;
  exception_type: "SPECIAL_WORKING" | "SHUTDOWN" | "SUBSTITUTE_HOLIDAY" | "CANCEL_HOLIDAY";
  name: string | null;
  reason: string | null;
  is_paid: boolean | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `DayTypeRead`. */
export interface DayType {
  date: string;
  day_type: "WORKING" | "WEEKLY_OFF" | "HOLIDAY" | "SPECIAL_WORKING" | "SHUTDOWN";
  holiday_name: string | null;
  exception_type: string | null;
  holiday_on_weekly_off: boolean;
  is_holiday_named: boolean;
  optional_holiday_name: string | null;
  restricted_holiday_name: string | null;
  /** Decimal serialised as a string or number; set only for a `WEEKLY_OFF` day. */
  weekly_off_fraction: string | number | null;
  holiday_type: string | null;
  holiday_is_paid: boolean | null;
}

/** Mirrors `calendar_setup.WorkCalendarDaysRead` (`GET /work-calendars/{id}/days`). */
export interface WorkCalendarDays {
  work_calendar_id: string;
  work_calendar_name: string;
  is_active: boolean;
  range_from: string;
  range_to: string;
  weekly_off_pattern_id: string | null;
  holiday_calendar_ids: string[];
  restricted_holidays_are_off_by_default: boolean;
  days: DayType[];
}

/** Mirrors `calendar_setup.WorkCalendarSetupStatus`. */
export interface WorkCalendarSetupStatus {
  state: "SETUP_REQUIRED" | "CONFIGURED";
  message: string;
  company_assignment: {
    assignment_id: string;
    work_calendar_id: string;
    scope_type: string;
    scope_id: string | null;
    effective_from: string;
    effective_to: string | null;
  } | null;
  holiday_calendar_count: number;
  suggestion: {
    confirmed: false;
    working_weekdays: number[];
    weekly_off_weekdays: number[];
    weekday_labels: string[];
    holidays_included: false;
    notice: string;
  } | null;
}

/** Mirrors `WorkCalendarSetupPreview`. Preview only: nothing is persisted. */
export interface WorkCalendarSetupPreview {
  preview_only: true;
  notice: string;
  effective_from: string;
  range_from: string;
  range_to: string;
  working_day_count: number;
  non_working_day_count: number;
  holiday_calendar_count: number;
  warnings: string[];
  days: DayType[];
}

/** Mirrors `WorkCalendarSetupConfirmed`. */
export interface WorkCalendarSetupConfirmed {
  work_calendar_id: string;
  weekly_off_pattern_id: string | null;
  assignment_id: string;
  scope_type: string;
  scope_id: string | null;
  effective_from: string;
  confirmed_at: string;
  confirmed_by: string | null;
}

export const EXCEPTION_TYPES = [
  "SPECIAL_WORKING",
  "SHUTDOWN",
  "SUBSTITUTE_HOLIDAY",
  "CANCEL_HOLIDAY",
] as const;

export const DAY_TYPE_LABELS: Record<DayType["day_type"], string> = {
  WORKING: "Working",
  WEEKLY_OFF: "Weekly off",
  HOLIDAY: "Holiday",
  SPECIAL_WORKING: "Special working day",
  SHUTDOWN: "Shutdown",
};

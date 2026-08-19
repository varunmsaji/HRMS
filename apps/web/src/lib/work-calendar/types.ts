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

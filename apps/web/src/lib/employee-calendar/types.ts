import type { DayType } from "@/lib/work-calendar/types";

/** Mirrors `apps/api/src/hrms/modules/organisation/employee_calendar.py::EmployeeCalendarLeave`.
 * Deliberately only display facts: no reason, leave type, attachment or reviewer. */
export interface EmployeeCalendarLeave {
  status: "APPROVED" | "PENDING";
  /** Decimal serialised as a string or number. */
  fraction: string | number;
  half: "FIRST_HALF" | "SECOND_HALF" | null;
}

/** Mirrors `EmployeeCalendarDay`. `configured=false` means no work calendar resolved for the
 * date (fail-closed); `day_type` is then null and the date must not be shown as working. */
export interface EmployeeCalendarDay {
  date: string;
  configured: boolean;
  day_type: DayType["day_type"] | null;
  holiday_name: string | null;
  holiday_type: string | null;
  holiday_on_weekly_off: boolean;
  is_holiday_named: boolean;
  optional_holiday_name: string | null;
  restricted_holiday_name: string | null;
  exception_type: string | null;
  weekly_off_fraction: string | number | null;
  leave: EmployeeCalendarLeave[];
}

/** Mirrors `EmployeeCalendarRead` (`GET /employee-calendar/me`). */
export interface EmployeeCalendar {
  from_date: string;
  to_date: string;
  configuration: "COMPLETE" | "PARTIAL" | "INCOMPLETE";
  leave_included: boolean;
  days: EmployeeCalendarDay[];
}

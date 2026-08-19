/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::HolidayCalendarRead`. */
export interface HolidayCalendar {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  kind: "NATIONAL" | "REGIONAL" | "COMPANY" | "LOCATION";
  state_code: string | null;
  valid_from: string | null;
  valid_to: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export const HOLIDAY_CALENDAR_KINDS = ["NATIONAL", "REGIONAL", "COMPANY", "LOCATION"] as const;

/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::HolidayRead`. */
export interface Holiday {
  id: string;
  company_id: string;
  calendar_id: string;
  date: string;
  name: string;
  is_optional: boolean;
  holiday_type: "PUBLIC" | "COMPANY" | "OPTIONAL" | "RESTRICTED" | "WORKING_HOLIDAY";
  is_paid: boolean;
  is_working: boolean;
  region_note: string | null;
  replaced_holiday_id: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export const HOLIDAY_TYPES = [
  "PUBLIC",
  "COMPANY",
  "OPTIONAL",
  "RESTRICTED",
  "WORKING_HOLIDAY",
] as const;

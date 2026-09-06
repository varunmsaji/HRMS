/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeaveYearSetting*` (LD-20). */

export const LEAVE_YEAR_TYPES = ["CALENDAR", "FINANCIAL", "ANNIVERSARY", "CUSTOM"] as const;
export type LeaveYearType = (typeof LEAVE_YEAR_TYPES)[number];

export interface LeaveYearSetting {
  id: string;
  company_id: string;
  leave_year_type: LeaveYearType;
  start_month: number | null;
  start_day: number | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `LeaveYearSettingUpsert`. */
export interface LeaveYearSettingUpsertPayload {
  leave_year_type: LeaveYearType;
  start_month?: number | null;
  start_day?: number | null;
}

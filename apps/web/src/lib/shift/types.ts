/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::ShiftRead`. `start_time`/
 * `end_time` are `"HH:MM"` strings on the wire (not minutes-since-midnight), per
 * `ShiftCreate`/`ShiftUpdate`'s own field pattern. */
export interface Shift {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  start_time: string;
  end_time: string;
  break_minutes_paid: number;
  break_minutes_unpaid: number;
  grace_in_minutes: number;
  grace_out_minutes: number;
  half_day_threshold_hours: number | null;
  min_hours_full_day: number | null;
  is_night_shift: boolean;
  is_cross_midnight: boolean;
  is_ot_eligible: boolean;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `ShiftCreate` / `ShiftUpdate` — both share the same editable field set. */
export interface ShiftWritableFields {
  name?: string;
  code?: string | null;
  start_time?: string;
  end_time?: string;
  break_minutes_paid?: number;
  break_minutes_unpaid?: number;
  grace_in_minutes?: number;
  grace_out_minutes?: number;
  half_day_threshold_hours?: number | null;
  min_hours_full_day?: number | null;
  is_night_shift?: boolean;
  is_cross_midnight?: boolean;
  is_ot_eligible?: boolean;
}

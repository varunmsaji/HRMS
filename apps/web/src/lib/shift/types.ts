/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::ShiftRead`. W2 trimmed `Shift`
 * to identity-only (name/code/active) — schedule now lives on `ShiftVersion`. The nine legacy
 * fields below are deprecated, read-only, frozen-at-migration-time (superseded by
 * `ShiftVersion`/`ShiftBreak`, never written again by W2+ code) — kept only for audit/
 * back-compat continuity, not surfaced in the identity-editing UI. */
export interface Shift {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  /** @deprecated frozen at W2 migration time — see ShiftVersion.start_time */
  start_time: string;
  /** @deprecated frozen at W2 migration time — see ShiftVersion.end_time */
  end_time: string;
  /** @deprecated frozen at W2 migration time — see ShiftBreak rows (is_paid=true) */
  break_minutes_paid: number;
  /** @deprecated frozen at W2 migration time — see ShiftBreak rows (is_paid=false) */
  break_minutes_unpaid: number;
  /** @deprecated frozen at W2 migration time — migrates to AttendancePolicy in W3 */
  grace_in_minutes: number;
  /** @deprecated frozen at W2 migration time — migrates to AttendancePolicy in W3 */
  grace_out_minutes: number;
  /** @deprecated frozen at W2 migration time — migrates to AttendancePolicy in W3 */
  half_day_threshold_hours: number | null;
  /** @deprecated frozen at W2 migration time — migrates to AttendancePolicy in W3 */
  min_hours_full_day: number | null;
  /** @deprecated frozen at W2 migration time — see ShiftVersion.is_night_shift */
  is_night_shift: boolean;
  /** @deprecated frozen at W2 migration time — see ShiftVersion.is_cross_midnight */
  is_cross_midnight: boolean;
  /** @deprecated frozen at W2 migration time — see ShiftVersion.is_ot_eligible */
  is_ot_eligible: boolean;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  /** The open (`effective_to` null) PUBLISHED version, if any. */
  current_version_id: string | null;
  /** The open DRAFT version, if any — at most one per shift. */
  draft_version_id: string | null;
}

/** Mirrors `ShiftCreate` / `ShiftUpdate` — identity-only. */
export interface ShiftWritableFields {
  name?: string;
  code?: string | null;
  is_active?: boolean;
}

export const SHIFT_VERSION_TYPES = ["FIXED", "FLEXIBLE", "SPLIT"] as const;
export type ShiftVersionType = (typeof SHIFT_VERSION_TYPES)[number];

export const SHIFT_BREAK_KINDS = ["FIXED_WINDOW", "FLEXIBLE_DURATION"] as const;
export type ShiftBreakKind = (typeof SHIFT_BREAK_KINDS)[number];

/** Mirrors `ShiftBreakRead`. */
export interface ShiftBreak {
  id: string;
  shift_version_id: string;
  name: string;
  break_kind: ShiftBreakKind;
  start_time: string | null;
  end_time: string | null;
  window_start: string | null;
  window_end: string | null;
  min_minutes: number | null;
  max_minutes: number | null;
  scheduled_minutes: number | null;
  is_paid: boolean;
  is_mandatory: boolean;
  allows_split: boolean;
  crosses_midnight: boolean;
  sort_order: number;
}

/** Mirrors `ShiftDutyBlockRead`. */
export interface ShiftDutyBlock {
  id: string;
  shift_version_id: string;
  sequence: number;
  start_time: string;
  end_time: string;
  crosses_midnight: boolean;
}

/** Mirrors `ShiftVersionRead`. `status` is `DRAFT`|`PUBLISHED`; `is_cross_midnight` is always
 * server-derived (never client-settable), `is_night_shift` is an explicit client-settable flag
 * (architecture §9.5). */
export interface ShiftVersion {
  id: string;
  company_id: string;
  shift_id: string;
  status: "DRAFT" | "PUBLISHED";
  version: number;
  effective_from: string | null;
  effective_to: string | null;
  shift_type: ShiftVersionType | null;
  timezone: string | null;
  start_time: string | null;
  end_time: string | null;
  window_start: string | null;
  window_end: string | null;
  core_start: string | null;
  core_end: string | null;
  required_minutes: number | null;
  scheduled_minutes: number | null;
  min_scheduled_minutes: number | null;
  max_scheduled_minutes: number | null;
  is_night_shift: boolean;
  is_cross_midnight: boolean;
  is_ot_eligible: boolean;
  operates_on_holiday: boolean;
  operates_on_weekly_off: boolean;
  weekly_off_pattern_id: string | null;
  publish_reason: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
  breaks: ShiftBreak[];
  duty_blocks: ShiftDutyBlock[];
}

export interface ShiftDeletionBlocker {
  code: string;
  message: string;
  count: number;
}

/** `GET /shifts/{id}/deletion-check` — why (not) the shift can be deleted. */
export interface ShiftDeletionCheck {
  can_delete: boolean;
  blockers: ShiftDeletionBlocker[];
  published_version_count: number;
  draft_version_count: number;
}

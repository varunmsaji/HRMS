/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::GradeRead`. Money fields
 * (`min_ctc`/`max_ctc`/`approval_limit`) are integer minor units (paise), per ADR-0006 —
 * never floats. */
export interface Grade {
  id: string;
  company_id: string;
  code: string;
  name: string;
  level: number | null;
  min_ctc: number | null;
  max_ctc: number | null;
  notice_period_days: number | null;
  probation_days: number | null;
  approval_limit: number | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `GradeCreate` / `GradeUpdate` — both share the same editable field set. */
export interface GradeWritableFields {
  name?: string;
  level?: number | null;
  min_ctc?: number | null;
  max_ctc?: number | null;
  notice_period_days?: number | null;
  probation_days?: number | null;
  approval_limit?: number | null;
}

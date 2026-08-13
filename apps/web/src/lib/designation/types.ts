/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::DesignationRead`. */
export interface Designation {
  id: string;
  company_id: string;
  department_id: string | null;
  grade_id: string | null;
  title: string;
  code: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `DesignationCreate` / `DesignationUpdate` — both share the same editable field set. */
export interface DesignationWritableFields {
  department_id?: string | null;
  grade_id?: string | null;
  title?: string;
  code?: string | null;
}

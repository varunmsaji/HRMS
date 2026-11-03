/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::DepartmentRead`. */
export interface Department {
  id: string;
  company_id: string;
  branch_id: string | null;
  parent_id: string | null;
  name: string;
  code: string | null;
  /** LEAVE_DECISION_LOG.md LD-23 — resolves Leave's third (HOD) approval stage. */
  head_employee_id: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `DepartmentCreate` / `DepartmentUpdate` — both share the same editable field set. */
export interface DepartmentWritableFields {
  branch_id?: string | null;
  parent_id?: string | null;
  name?: string;
  head_employee_id?: string | null;
}

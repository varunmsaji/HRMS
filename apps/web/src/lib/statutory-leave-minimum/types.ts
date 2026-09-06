import type { StatutoryLeaveCategory } from "@/lib/leave-type/types";

/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `StatutoryLeaveMinimum*` (LD-22). */

export interface StatutoryLeaveMinimum {
  id: string;
  company_id: string;
  state_code: string | null;
  establishment_type: string | null;
  leave_category: StatutoryLeaveCategory;
  min_days_per_year: string;
  note: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

/** Mirrors `StatutoryLeaveMinimumCreate`. */
export interface StatutoryLeaveMinimumCreatePayload {
  state_code: string | null;
  establishment_type: string | null;
  leave_category: StatutoryLeaveCategory;
  min_days_per_year: string;
  note: string | null;
}

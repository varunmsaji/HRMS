/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeaveCombinationRule*` (LD-16). */

export interface LeaveCombinationRule {
  id: string;
  company_id: string;
  leave_type_id_a: string;
  leave_type_id_b: string;
  allowed: boolean;
  reason: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

/** Mirrors `LeaveCombinationRuleCreate`. */
export interface LeaveCombinationRuleCreatePayload {
  leave_type_id_a: string;
  leave_type_id_b: string;
  allowed: boolean;
  reason?: string | null;
}

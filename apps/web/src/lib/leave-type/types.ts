/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeaveType*` (L1). */

export interface LeaveType {
  id: string;
  company_id: string;
  code: string;
  name: string;
  is_paid_default: boolean;
  requires_balance: boolean;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `LeaveTypeCreate`. */
export interface LeaveTypeCreatePayload {
  code: string;
  name: string;
  is_paid_default: boolean;
  requires_balance: boolean;
}

/** Mirrors `LeaveTypeUpdate`. */
export interface LeaveTypeUpdatePayload {
  name?: string;
  is_paid_default?: boolean;
  requires_balance?: boolean;
  is_active?: boolean;
}

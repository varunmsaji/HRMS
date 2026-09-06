/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeaveType*` (L1). */

/** Mirrors `STATUTORY_LEAVE_CATEGORIES` (LD-22). */
export const STATUTORY_LEAVE_CATEGORIES = [
  "EARNED",
  "SICK",
  "CASUAL",
  "MATERNITY",
  "PATERNITY",
] as const;
export type StatutoryLeaveCategory = (typeof STATUTORY_LEAVE_CATEGORIES)[number];

export interface LeaveType {
  id: string;
  company_id: string;
  code: string;
  name: string;
  is_paid_default: boolean;
  requires_balance: boolean;
  is_comp_off: boolean;
  statutory_category: StatutoryLeaveCategory | null;
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
  is_comp_off: boolean;
  statutory_category: StatutoryLeaveCategory | null;
}

/** Mirrors `LeaveTypeUpdate`. */
export interface LeaveTypeUpdatePayload {
  name?: string;
  is_paid_default?: boolean;
  requires_balance?: boolean;
  is_comp_off?: boolean;
  statutory_category?: StatutoryLeaveCategory | null;
  is_active?: boolean;
}

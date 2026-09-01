/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeaveLedger*`/`LeaveBalanceRead` (L2). */

export const LEDGER_ENTRY_TYPES = [
  "ACCRUAL",
  "APPLICATION",
  "ADJUSTMENT",
  "ENCASHMENT",
  "CARRY_FORWARD",
  "COMP_OFF_CREDIT",
] as const;
export type LedgerEntryType = (typeof LEDGER_ENTRY_TYPES)[number];

export interface LeaveLedgerEntry {
  id: string;
  company_id: string;
  employee_id: string;
  leave_type_id: string;
  entry_type: LedgerEntryType;
  amount: string;
  effective_date: string;
  reference_id: string | null;
  reason: string | null;
  created_by_user_id: string | null;
  created_at: string;
}

export interface LeaveBalance {
  employee_id: string;
  leave_type_id: string;
  leave_type_code: string;
  leave_type_name: string;
  balance: string;
}

/** Mirrors `LeaveLedgerAdjustmentCreate`. */
export interface LeaveLedgerAdjustmentPayload {
  employee_id: string;
  leave_type_id: string;
  amount: string;
  effective_date: string;
  reason: string;
}

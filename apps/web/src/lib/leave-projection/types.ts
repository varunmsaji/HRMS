/** Mirrors `apps/api/src/hrms/modules/attendance/schemas.py` `LeaveDayProjection*` (W9 —
 * architecture §21, decision log WD-31). This is the Attendance-owned mirror of Leave's
 * "approved day projection" contract, not the leave ledger — Leave, when it ships, owns
 * entitlement/balance/accrual/approval; this only carries what Attendance needs to overlay a
 * day's calculation and what the UI needs to show provenance for that overlay. */

export const LEAVE_PROJECTION_STATUSES = ["APPROVED", "CANCELLED"] as const;
export type LeaveProjectionStatus = (typeof LEAVE_PROJECTION_STATUSES)[number];

export const LEAVE_PROJECTION_HALVES = ["FIRST", "SECOND"] as const;
export type LeaveProjectionHalf = (typeof LEAVE_PROJECTION_HALVES)[number];

export interface LeaveDayProjection {
  id: string;
  company_id: string;
  employee_id: string;
  attendance_date: string;
  leave_application_id: string;
  leave_type_id: string | null;
  leave_type_code: string | null;
  fraction: string;
  half: LeaveProjectionHalf | null;
  is_paid: boolean;
  status: LeaveProjectionStatus;
  source_version: number;
  synced_at: string;
  cancelled_at: string | null;
  cancelled_reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export const LEAVE_PROJECTION_STATUS_LABELS: Record<LeaveProjectionStatus, string> = {
  APPROVED: "Approved",
  CANCELLED: "Cancelled",
};

import type { AccrualFrequency, ApprovalChain } from "@/lib/leave-policy/types";

export const LEAVE_APPROVAL_LABELS: Record<ApprovalChain, string> = {
  AUTO: "Approved automatically",
  MANAGER: "Manager approves",
  MANAGER_THEN_HR: "Manager approves, then HR",
  MANAGER_THEN_HOD_THEN_HR: "Manager, then department head, then HR",
  HR: "HR approves",
};

export const ACCRUAL_LABELS: Record<AccrualFrequency, string> = {
  NONE: "No automatic credit",
  MONTHLY: "Every month",
  YEARLY: "Once a year",
};

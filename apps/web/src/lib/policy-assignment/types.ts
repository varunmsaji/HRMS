/** Mirrors `hrms.modules.organisation.schemas.PolicyAssignment*` — widened by W3 to also carry
 * `ATTENDANCE_POLICY`/`OVERTIME_POLICY`/`REGULARIZATION_POLICY` (WD-24), and by Leave L1/LD-11 to
 * carry `LEAVE_POLICY`, which uniquely also needs `leave_type_id` — unlike every other kind,
 * a company can have multiple simultaneous `LEAVE_POLICY` assignments at the same scope, one per
 * leave type (LD-11). */

export const POLICY_KINDS = [
  "WORK_CALENDAR",
  "WEEKLY_OFF",
  "ATTENDANCE_POLICY",
  "OVERTIME_POLICY",
  "REGULARIZATION_POLICY",
  "LEAVE_POLICY",
] as const;
export type PolicyKind = (typeof POLICY_KINDS)[number];

export const SCOPE_TYPES = [
  "COMPANY",
  "LEGAL_ENTITY",
  "BRANCH",
  "DEPARTMENT",
  "GRADE",
  "DESIGNATION",
  "SHIFT",
  "EMPLOYEE",
] as const;
export type ScopeType = (typeof SCOPE_TYPES)[number];

export interface PolicyAssignment {
  id: string;
  company_id: string;
  policy_kind: PolicyKind;
  policy_id: string;
  leave_type_id: string | null;
  scope_type: ScopeType;
  scope_id: string | null;
  effective_from: string;
  effective_to: string | null;
  priority: number;
  reason: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export const POLICY_KIND_LABELS: Record<PolicyKind, string> = {
  WORK_CALENDAR: "Work Calendar",
  WEEKLY_OFF: "Weekly-Off Pattern",
  ATTENDANCE_POLICY: "Attendance Policy",
  OVERTIME_POLICY: "Overtime Policy",
  REGULARIZATION_POLICY: "Regularization Policy",
  LEAVE_POLICY: "Leave Policy",
};

/** The API path each policy_kind's identity list lives at — used to populate the `policy_id`
 * picker in the assignment form. */
export const POLICY_KIND_LIST_PATH: Record<PolicyKind, string> = {
  WORK_CALENDAR: "/work-calendars",
  WEEKLY_OFF: "/weekly-off-patterns",
  ATTENDANCE_POLICY: "/attendance-policies",
  OVERTIME_POLICY: "/overtime-policies",
  REGULARIZATION_POLICY: "/regularization-policies",
  LEAVE_POLICY: "/leave-policies",
};

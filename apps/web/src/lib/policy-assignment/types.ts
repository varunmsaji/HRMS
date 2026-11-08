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

export const SCOPE_TYPE_LABELS: Record<ScopeType, string> = {
  COMPANY: "Whole company",
  LEGAL_ENTITY: "Legal entity",
  BRANCH: "Branch",
  DEPARTMENT: "Department",
  GRADE: "Grade",
  DESIGNATION: "Designation",
  SHIFT: "Shift",
  EMPLOYEE: "Employee",
};

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
  REGULARIZATION_POLICY: "Correction Policy",
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

/** Mirrors `PolicyCoverageRead`: for one scope, what is set there and what applies on `as_of`. */
export interface PolicyCoverageOwn {
  assignment_id: string;
  policy_id: string;
  policy_name: string | null;
  effective_from: string;
  version: number;
}

export interface PolicyCoverageApplied {
  policy_id: string;
  policy_name: string | null;
  scope_type: ScopeType;
  scope_id: string | null;
  scope_name: string | null;
  effective_from: string;
  effective_to: string | null;
  has_rules: boolean;
}

export interface PolicyCoverageRow {
  policy_kind: PolicyKind;
  leave_type_id: string | null;
  leave_type_name: string | null;
  own: PolicyCoverageOwn | null;
  applied: PolicyCoverageApplied | null;
}

export interface PolicyCoverage {
  scope_type: ScopeType;
  scope_id: string | null;
  as_of: string;
  rows: PolicyCoverageRow[];
}

export function coveragePath(scopeType: ScopeType, scopeId: string | null, asOf: string): string {
  const query = new URLSearchParams({ scope_type: scopeType, as_of: asOf });
  if (scopeId) query.set("scope_id", scopeId);
  return `/policy-assignments/coverage?${query.toString()}`;
}

export function coverageRowKey(row: { policy_kind: PolicyKind; leave_type_id: string | null }): string {
  return row.leave_type_id ? `${row.policy_kind}:${row.leave_type_id}` : row.policy_kind;
}

export function coverageRowLabel(row: PolicyCoverageRow): string {
  return row.leave_type_name
    ? `Leave Policy — ${row.leave_type_name}`
    : POLICY_KIND_LABELS[row.policy_kind];
}

/** Work Calendar / Weekly-Off changes alter day types, so they go through the impact preview. */
export function needsImpactPreview(kind: PolicyKind): boolean {
  return kind === "WORK_CALENDAR" || kind === "WEEKLY_OFF";
}

/** Mirrors `end_policy_assignment`: the company-wide row is the safety net, and calendar kinds can
 * only be replaced through the impact preview. */
export function canEndAssignment(
  policyKind: PolicyKind,
  scopeType: ScopeType,
  effectiveTo: string | null = null,
): boolean {
  return effectiveTo === null && scopeType !== "COMPANY" && !needsImpactPreview(policyKind);
}

/** Where a coverage row's policy comes from, in words. */
export function appliedSourceLabel(applied: PolicyCoverageApplied): string {
  const label = SCOPE_TYPE_LABELS[applied.scope_type];
  return applied.scope_name ? `${label}: ${applied.scope_name}` : label;
}

/** Mirrors `_require_policy_assignment_permission`: the permissions needed to see and change
 * assignments of one kind. Leave policies currently need both, like an unfiltered list. */
export function assignmentPermissions(kind: PolicyKind): string[] {
  if (kind === "WORK_CALENDAR" || kind === "WEEKLY_OFF") return ["ORG.CALENDAR.MANAGE"];
  if (kind === "ATTENDANCE_POLICY" || kind === "OVERTIME_POLICY" || kind === "REGULARIZATION_POLICY") {
    return ["ATTENDANCE.POLICY_MANAGE"];
  }
  return ["ORG.CALENDAR.MANAGE", "ATTENDANCE.POLICY_MANAGE"];
}

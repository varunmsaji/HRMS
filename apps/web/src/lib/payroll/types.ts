/** Mirrors `apps/api/src/hrms/modules/payroll/schemas.py` (payroll Phase 5.1 — salary setup;
 * Phase 5.2 — pay runs; `docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`). Money is
 * integer paise (`*_minor`). */

export const COMPONENT_TYPES = ["EARNING", "DEDUCTION", "EMPLOYER_CONTRIBUTION"] as const;
export type ComponentType = (typeof COMPONENT_TYPES)[number];

export const COMPONENT_TYPE_LABELS: Record<ComponentType, string> = {
  EARNING: "Earning",
  DEDUCTION: "Deduction",
  EMPLOYER_CONTRIBUTION: "Employer contribution",
};

export const CALCULATION_TYPES = [
  "FIXED",
  "PERCENTAGE_OF_CTC",
  "PERCENTAGE_OF_GROSS",
  "PERCENTAGE_OF_COMPONENT",
  "BALANCING",
] as const;
export type CalculationType = (typeof CALCULATION_TYPES)[number];

export const CALCULATION_TYPE_LABELS: Record<CalculationType, string> = {
  FIXED: "Fixed amount",
  PERCENTAGE_OF_CTC: "% of monthly CTC",
  PERCENTAGE_OF_GROSS: "% of gross",
  PERCENTAGE_OF_COMPONENT: "% of another component",
  BALANCING: "Balance of gross",
};

export const APPLIES_WHEN = ["ALWAYS", "PF_APPLICABLE", "ESI_APPLICABLE"] as const;
export type AppliesWhen = (typeof APPLIES_WHEN)[number];

export const APPLIES_WHEN_LABELS: Record<AppliesWhen, string> = {
  ALWAYS: "Always",
  PF_APPLICABLE: "Only if PF applies",
  ESI_APPLICABLE: "Only if ESI applies",
};

export interface SalaryComponent {
  id: string;
  company_id: string;
  code: string;
  name: string;
  component_type: ComponentType;
  is_system: boolean;
  is_taxable: boolean;
  is_pf_wage: boolean;
  is_esi_wage: boolean;
  is_prorated: boolean;
  show_on_payslip: boolean;
  display_order: number;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SalaryStructureLine {
  id: string;
  salary_component_id: string;
  component_code: string;
  component_name: string;
  component_type: ComponentType;
  calculation_type: CalculationType;
  percentage: string | null;
  amount_monthly_minor: number | null;
  base_salary_component_id: string | null;
  max_monthly_minor: number | null;
  applies_when: AppliesWhen;
  display_order: number;
}

export interface SalaryStructureVersion {
  id: string;
  salary_structure_id: string;
  version_number: number;
  status: "DRAFT" | "PUBLISHED";
  effective_from: string | null;
  effective_to: string | null;
  published_at: string | null;
  version: number;
  lines: SalaryStructureLine[];
}

export interface SalaryStructure {
  id: string;
  company_id: string;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  version: number;
  versions: SalaryStructureVersion[];
  created_at: string;
  updated_at: string;
}

export interface SalaryStructureLineInput {
  salary_component_id: string;
  calculation_type: CalculationType;
  percentage?: string | null;
  amount_monthly_minor?: number | null;
  base_salary_component_id?: string | null;
  max_monthly_minor?: number | null;
  applies_when: AppliesWhen;
  display_order: number;
}

export interface SalaryBreakupLine {
  component_code: string;
  component_name: string;
  component_type: ComponentType;
  monthly_minor: number;
  annual_minor: number;
  basis: string;
}

export interface SalaryBreakup {
  annual_ctc_minor: number;
  monthly_ctc_minor: number;
  gross_monthly_minor: number;
  employer_contributions_monthly_minor: number;
  lines: SalaryBreakupLine[];
}

export interface EmployeeSalaryBreakup {
  employee_id: string;
  as_of: string;
  pay_basis: "MONTHLY" | "DAILY_WAGE";
  salary_structure_id: string | null;
  salary_structure_version_id: string | null;
  daily_rate_minor: number | null;
  pf_applicable: boolean;
  esi_applicable: boolean;
  breakup: SalaryBreakup | null;
}

export interface EmployeeSalary {
  id: string;
  company_id: string;
  employee_id: string;
  salary_structure_id: string | null;
  daily_rate_minor: number | null;
  effective_from: string;
  effective_to: string | null;
  reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface EmployeeSalaryBulkResult {
  assigned: string[];
  skipped: { employee_id: string; reason: string }[];
}

/** ₹ with Indian digit grouping; paise shown only when present. */
export function formatInr(minor: number): string {
  const rupees = minor / 100;
  return `₹${rupees.toLocaleString("en-IN", {
    minimumFractionDigits: Number.isInteger(rupees) ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

/** "12,00,000" / "1200000.50" → paise; `null` when not a valid non-negative amount. */
export function rupeesToMinor(value: string): number | null {
  const cleaned = value.replaceAll(",", "").trim();
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return Math.round(Number(cleaned) * 100);
}

export function currentVersion(structure: SalaryStructure): SalaryStructureVersion | null {
  return structure.versions.find((v) => v.status === "PUBLISHED" && v.effective_to === null) ?? null;
}

export function draftVersion(structure: SalaryStructure): SalaryStructureVersion | null {
  return structure.versions.find((v) => v.status === "DRAFT") ?? null;
}

// ---------------------------------------------------------------------------
// Phase 5.2 — pay runs
// ---------------------------------------------------------------------------

export const PAY_RUN_STATUSES = [
  "DRAFT",
  "INPUTS_LOCKED",
  "COMPUTED",
  "APPROVED",
  "FINALISED",
  "PAID",
] as const;
export type PayRunStatus = (typeof PAY_RUN_STATUSES)[number];

export const PAY_RUN_STATUS_LABELS: Record<PayRunStatus, string> = {
  DRAFT: "Draft",
  INPUTS_LOCKED: "Inputs locked",
  COMPUTED: "Computed",
  APPROVED: "Approved",
  FINALISED: "Finalised",
  PAID: "Paid",
};

export interface PayrollSetting {
  company_id: string;
  variance_threshold_percent: string;
  version: number;
}

export interface PayRun {
  id: string;
  company_id: string;
  legal_entity_id: string;
  /** `YYYY-MM` */
  month: string;
  period_start: string;
  period_end: string;
  days_in_month: number;
  status: PayRunStatus;
  pay_date: string;
  attendance_period_id: string | null;
  variance_threshold_percent: string | null;
  previous_pay_run_id: string | null;
  employee_count: number;
  gross_minor: number;
  deductions_minor: number;
  employer_contributions_minor: number;
  net_minor: number;
  error_count: number;
  warning_count: number;
  variance_flag_count: number;
  variance_open_count: number;
  created_by_user_id: string | null;
  inputs_locked_at: string | null;
  inputs_locked_by_user_id: string | null;
  computed_at: string | null;
  computed_by_user_id: string | null;
  approved_at: string | null;
  approved_by_user_id: string | null;
  finalised_at: string | null;
  finalised_by_user_id: string | null;
  paid_at: string | null;
  paid_by_user_id: string | null;
  last_rollback_reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PayRunIssue {
  code: string;
  severity: "ERROR" | "WARNING";
  message: string;
}

export interface PayRunEmployee {
  id: string;
  employee_id: string;
  employee_code: string | null;
  employee_name: string | null;
  pay_basis: "MONTHLY" | "DAILY_WAGE" | null;
  paid_days: string | null;
  lop_days: string | null;
  payable_days: string | null;
  is_computed: boolean;
  gross_minor: number;
  deductions_minor: number;
  employer_contributions_minor: number;
  rounding_minor: number;
  net_minor: number;
  issues: PayRunIssue[];
  has_error: boolean;
  previous_net_minor: number | null;
  variance_percent: string | null;
  variance_flagged: boolean;
  variance_reason: string | null;
  variance_acknowledged_by_user_id: string | null;
  variance_acknowledged_at: string | null;
}

export interface PayRunLine {
  component_code: string;
  component_name: string;
  line_type: "EARNING" | "DEDUCTION" | "EMPLOYER_CONTRIBUTION" | "ROUNDING";
  full_monthly_minor: number | null;
  amount_minor: number;
  display_order: number;
  trace: Record<string, unknown> & { formula?: string };
}

export interface PayRunEmployeeDetail extends PayRunEmployee {
  lines: PayRunLine[];
  snapshot: Record<string, unknown>;
}

/** "2026-09" → "September 2026". */
export function formatPayMonth(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1, 1)).toLocaleString("en-IN", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Which lifecycle actions a run's status allows — the backend still decides; this only hides
 * buttons that could never succeed. */
export function payRunActions(status: PayRunStatus): {
  lockInputs: boolean;
  compute: boolean;
  approve: boolean;
  finalise: boolean;
  markPaid: boolean;
  rollbackTo: ("DRAFT" | "INPUTS_LOCKED")[];
  editPayDate: boolean;
  remove: boolean;
} {
  return {
    lockInputs: status === "DRAFT",
    compute: status === "INPUTS_LOCKED" || status === "COMPUTED",
    approve: status === "COMPUTED",
    finalise: status === "APPROVED",
    markPaid: status === "FINALISED",
    rollbackTo:
      status === "COMPUTED" || status === "APPROVED"
        ? ["INPUTS_LOCKED", "DRAFT"]
        : status === "INPUTS_LOCKED"
          ? ["DRAFT"]
          : [],
    editPayDate: !["FINALISED", "PAID"].includes(status),
    remove: status === "DRAFT",
  };
}

// ---------------------------------------------------------------------------
// Phase 5.3 — statutory rates
// ---------------------------------------------------------------------------

export const STATUTORY_SCHEMES = ["PF", "ESI", "PT", "LWF"] as const;
export type StatutoryScheme = (typeof STATUTORY_SCHEMES)[number];

export const STATUTORY_SCHEME_LABELS: Record<StatutoryScheme, string> = {
  PF: "Provident Fund",
  ESI: "Employees' State Insurance",
  PT: "Professional tax",
  LWF: "Labour welfare fund",
};

export interface PtSlab {
  min_minor: number;
  max_minor: number | null;
  amount_minor: number;
  gender?: "MALE" | "FEMALE" | null;
  month_amounts?: Record<string, number> | null;
}

export interface LwfSlab {
  min_minor: number;
  max_minor: number | null;
  employee_minor: number;
  employer_minor: number;
}

export interface StatutoryRate {
  id: string;
  company_id: string;
  scheme: StatutoryScheme;
  state_code: string | null;
  effective_from: string;
  effective_to: string | null;
  parameters: Record<string, unknown>;
  notes: string | null;
  is_seeded: boolean;
  verified: boolean;
  verified_at: string | null;
  verified_by_user_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** One-line summary of a rate's figures for the list. */
export function summariseStatutoryRate(rate: StatutoryRate): string {
  const p = rate.parameters as Record<string, unknown>;
  switch (rate.scheme) {
    case "PF":
      return `Employee ${p.employee_percent}% · employer ${p.employer_percent}% (EPS ${p.eps_percent}%) · ceiling ${formatInr(Number(p.wage_ceiling_minor))}`;
    case "ESI":
      return `Employee ${p.employee_percent}% · employer ${p.employer_percent}% · ceiling ${formatInr(Number(p.wage_ceiling_minor))}`;
    case "PT": {
      const slabs = (p.slabs as PtSlab[] | undefined) ?? [];
      return slabs.length === 0 ? "No professional tax in this state" : `${slabs.length} slab(s)`;
    }
    case "LWF": {
      const months = (p.months as number[] | undefined) ?? [];
      return `Deducted in month(s) ${months.join(", ")}`;
    }
  }
}

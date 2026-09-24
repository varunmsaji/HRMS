/** Mirrors `apps/api/src/hrms/modules/payroll/schemas.py` (payroll Phase 5.1 — salary setup,
 * `docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`). Money is integer paise
 * (`*_minor`). */

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

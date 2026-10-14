/** Mirrors `apps/api/src/hrms/modules/employee/schemas.py`. Every interface/value tuple here
 * corresponds 1:1 to a Pydantic schema or Literal in that file — read it before changing this. */

// --- Employee (E-01) ---------------------------------------------------------------------

/** FR-EMP-014 — the authoritative 10-value enumeration. Not client-writable. */
export const EMPLOYEE_STATUS_VALUES = [
  "PRE_JOINING",
  "PROBATION",
  "ACTIVE",
  "ON_NOTICE",
  "SUSPENDED",
  "ON_LONG_LEAVE",
  "EXITED",
  "ABSCONDING",
  "RETIRED",
  "DECEASED",
] as const;
export type EmployeeStatus = (typeof EMPLOYEE_STATUS_VALUES)[number];

export interface Employee {
  id: string;
  company_id: string;
  employee_code: string;
  first_name: string;
  middle_name: string | null;
  last_name: string | null;
  display_name: string | null;
  date_of_birth: string | null;
  gender: string | null;
  blood_group: string | null;
  marital_status: string | null;
  nationality: string | null;
  personal_email: string | null;
  personal_mobile: string | null;
  photo_url: string | null;
  status: string;
  custom_fields: Record<string, unknown> | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `EmployeeCreate` / `EmployeeUpdate` — both share the same editable field set
 * (Update additionally allows `is_active`). */
export interface EmployeeWritableFields {
  first_name?: string;
  middle_name?: string | null;
  last_name?: string | null;
  date_of_birth?: string | null;
  gender?: string | null;
  blood_group?: string | null;
  marital_status?: string | null;
  nationality?: string | null;
  personal_email?: string | null;
  personal_mobile?: string | null;
  photo_url?: string | null;
  is_active?: boolean;
}

// --- Employment (E-03) --------------------------------------------------------------------

export const EMPLOYMENT_STATUS_VALUES = ["ACTIVE", "TERMINATED"] as const;
export type EmploymentStatus = (typeof EMPLOYMENT_STATUS_VALUES)[number];

export const PAY_BASIS_VALUES = ["MONTHLY", "DAILY_WAGE"] as const;
export type PayBasis = (typeof PAY_BASIS_VALUES)[number];

export const PAY_BASIS_LABELS: Record<PayBasis, string> = {
  MONTHLY: "Monthly salaried",
  DAILY_WAGE: "Daily wage",
};

export const PAY_BASIS_DESCRIPTIONS: Record<PayBasis, string> = {
  MONTHLY: "Holidays and weekly offs are paid.",
  DAILY_WAGE: "Paid for public holidays only; weekly offs and company holidays are unpaid.",
};

export interface Employment {
  id: string;
  company_id: string;
  employee_id: string;
  legal_entity_id: string;
  joining_date: string;
  last_working_day: string | null;
  /** Purely informational (Employee confirmation, minimal slice) — nothing reads or
   * auto-computes this; HR sets/corrects it directly. */
  probation_end_date: string | null;
  /** BUS-001 — decides which days off are paid (see `PAY_BASIS_LABELS`). */
  pay_basis: PayBasis;
  status: string;
  previous_employment_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

// --- Employee Assignment (E-04 / E-05) -----------------------------------------------------

export const ASSIGNMENT_CHANGE_TYPE_VALUES = [
  "INITIAL",
  "TRANSFER",
  "PROMOTION",
  "MANAGER_CHANGE",
  "SHIFT_CHANGE",
] as const;
export type AssignmentChangeType = (typeof ASSIGNMENT_CHANGE_TYPE_VALUES)[number];

export const WORK_LOCATION_TYPE_VALUES = ["OFFICE", "WFH", "HYBRID", "FIELD"] as const;
export type WorkLocationType = (typeof WORK_LOCATION_TYPE_VALUES)[number];

export interface Assignment {
  id: string;
  company_id: string;
  employee_id: string;
  branch_id: string | null;
  department_id: string | null;
  designation_id: string | null;
  grade_id: string | null;
  reporting_manager_id: string | null;
  dotted_line_manager_id: string | null;
  cost_centre_id: string | null;
  shift_id: string | null;
  work_location_type: string | null;
  change_type: string | null;
  change_reason: string | null;
  effective_from: string;
  effective_to: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

// --- Employee Compensation (E-06) -----------------------------------------------------------

export const REVISION_TYPE_VALUES = ["JOINING", "ANNUAL", "PROMOTION", "CORRECTION", "MARKET"] as const;
export type RevisionType = (typeof REVISION_TYPE_VALUES)[number];

export interface Compensation {
  id: string;
  company_id: string;
  employee_id: string;
  annual_ctc_minor: number;
  currency: string;
  revision_type: string;
  revision_reason: string | null;
  effective_from: string;
  effective_to: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

// --- Employee Statutory (E-07) ---------------------------------------------------------------

export const TAX_REGIME_VALUES = ["OLD", "NEW"] as const;
export type TaxRegime = (typeof TAX_REGIME_VALUES)[number];

export interface Statutory {
  id: string;
  company_id: string;
  employee_id: string;
  effective_from: string;
  effective_to: string | null;
  is_pf_applicable: boolean;
  pf_number: string | null;
  pf_wage_ceiling_opt_out: boolean;
  vpf_amount: number | null;
  vpf_percentage: number | null;
  is_esi_applicable: boolean;
  esi_ip_number: string | null;
  pt_state_code: string | null;
  is_lwf_applicable: boolean;
  tax_regime: string | null;
  is_director: boolean;
  is_international_worker: boolean;
  revision_reason: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

// --- Employee Bank (E-08) ---------------------------------------------------------------------

export const PAYMENT_MODE_VALUES = ["BANK", "CASH", "CHEQUE", "UPI"] as const;
export type PaymentMode = (typeof PAYMENT_MODE_VALUES)[number];

export interface Bank {
  id: string;
  company_id: string;
  employee_id: string;
  effective_from: string;
  effective_to: string | null;
  account_holder_name: string | null;
  /** Stored as plaintext TEXT server-side today despite the `_enc` suffix — see
   * docs/modules/employee/36_EMPLOYEE_BANKING_IMPLEMENTATION_REPORT.md §8. Never render this
   * unmasked, never log it, never persist it client-side. */
  account_number_enc: string | null;
  bank_name: string | null;
  ifsc: string | null;
  branch_name: string | null;
  payment_mode: string | null;
  is_primary: boolean;
  verification_status: string;
  penny_drop_reference: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

// --- Employee Document (post-onboarding document management) ------------------------------
//
// An employee's ongoing document store, independent of onboarding's own, separate
// `OnboardingDocument` (`@/lib/onboarding/types`). Same type list/labels as that module's
// `ONBOARDING_DOCUMENT_TYPES`/`ONBOARDING_DOCUMENT_TYPE_LABELS` — a document migrated from
// onboarding at activation keeps its original `document_type` as-is.

export const EMPLOYEE_DOCUMENT_TYPES = [
  "PHOTO",
  "PAN",
  "AADHAAR",
  "ADDRESS_PROOF",
  "EDUCATION_CERTIFICATE",
  "PREVIOUS_EMPLOYMENT_PROOF",
  "BANK_PROOF",
  "OTHER",
] as const;
export type EmployeeDocumentType = (typeof EMPLOYEE_DOCUMENT_TYPES)[number];

export const EMPLOYEE_DOCUMENT_TYPE_LABELS: Record<EmployeeDocumentType, string> = {
  PHOTO: "Photo",
  PAN: "PAN card",
  AADHAAR: "Aadhaar card",
  ADDRESS_PROOF: "Address proof",
  EDUCATION_CERTIFICATE: "Education certificate",
  PREVIOUS_EMPLOYMENT_PROOF: "Previous employment proof",
  BANK_PROOF: "Bank proof",
  OTHER: "Other",
};

/** `GET /employees/{id}/documents` — mirrors `EmployeeDocumentWithUrlRead`. Always carries a
 * presigned `download_url`, for both HR/Admin and the SELF-scoped employee alike (unlike
 * onboarding's candidate-facing list, there is no "might still replace an unreviewed upload"
 * case here that would justify withholding it). */
export interface EmployeeDocument {
  id: string;
  employee_id: string;
  document_type: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  status: string;
  verified_by_user_id: string | null;
  verified_at: string | null;
  rejection_reason: string | null;
  uploaded_at: string;
  download_url: string;
}

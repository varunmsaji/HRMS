import type { TaxRegime } from "@/lib/employee/types";

export interface StatutoryFormValues {
  effectiveFrom: string;
  isPfApplicable: boolean;
  pfNumber: string;
  pfWageCeilingOptOut: boolean;
  vpfAmount: string;
  vpfPercentage: string;
  isEsiApplicable: boolean;
  esiIpNumber: string;
  ptStateCode: string;
  isLwfApplicable: boolean;
  taxRegime: TaxRegime | "";
  isDirector: boolean;
  isInternationalWorker: boolean;
  revisionReason: string;
}

export type StatutoryFormErrors = Partial<Record<keyof StatutoryFormValues, string>>;

export const EMPTY_STATUTORY_FORM_VALUES: StatutoryFormValues = {
  effectiveFrom: "",
  isPfApplicable: false,
  pfNumber: "",
  pfWageCeilingOptOut: false,
  vpfAmount: "",
  vpfPercentage: "",
  isEsiApplicable: false,
  esiIpNumber: "",
  ptStateCode: "",
  isLwfApplicable: false,
  taxRegime: "",
  isDirector: false,
  isInternationalWorker: false,
  revisionReason: "",
};

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isNaN(parsed) ? null : Math.trunc(parsed);
}

function floatOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Full payload for `POST /employees/{id}/statutory` — no carry-forward, mirrors Compensation. */
export function buildStatutoryCreatePayload(values: StatutoryFormValues): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom,
    is_pf_applicable: values.isPfApplicable,
    pf_number: values.pfNumber.trim() || null,
    pf_wage_ceiling_opt_out: values.pfWageCeilingOptOut,
    vpf_amount: intOrNull(values.vpfAmount),
    vpf_percentage: floatOrNull(values.vpfPercentage),
    is_esi_applicable: values.isEsiApplicable,
    esi_ip_number: values.esiIpNumber.trim() || null,
    pt_state_code: values.ptStateCode.trim() || null,
    is_lwf_applicable: values.isLwfApplicable,
    tax_regime: values.taxRegime,
    is_director: values.isDirector,
    is_international_worker: values.isInternationalWorker,
    revision_reason: values.revisionReason.trim(),
  };
}

export function validateStatutoryForm(values: StatutoryFormValues): StatutoryFormErrors {
  const errors: StatutoryFormErrors = {};

  if (!values.effectiveFrom) errors.effectiveFrom = "Effective date is required.";
  if (!values.taxRegime) errors.taxRegime = "Select a tax regime.";
  if (!values.revisionReason.trim()) errors.revisionReason = "Revision reason is required.";

  return errors;
}

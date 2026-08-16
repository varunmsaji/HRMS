import type { RevisionType } from "@/lib/employee/types";

export interface CompensationFormValues {
  effectiveFrom: string;
  annualCtc: string;
  currency: string;
  revisionType: RevisionType | "";
  revisionReason: string;
}

export type CompensationFormErrors = Partial<Record<keyof CompensationFormValues, string>>;

export const EMPTY_COMPENSATION_FORM_VALUES: CompensationFormValues = {
  effectiveFrom: "",
  annualCtc: "",
  currency: "INR",
  revisionType: "",
  revisionReason: "",
};

/** `annual_ctc_minor` is integer minor units on the wire (e.g. paise), per this module's own
 * money-field convention (matches Grade's `min_ctc`/`max_ctc`, ADR-0006) — the form works in
 * whole currency units and converts at the boundary. */
function unitsToMinor(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const amount = Number(trimmed);
  if (Number.isNaN(amount)) return null;
  return Math.round(amount * 100);
}

export function minorToUnits(value: number): string {
  return String(value / 100);
}

/** Full payload for `POST /employees/{id}/compensation` — every field is required on every
 * write, no carry-forward (unlike Assignment). */
export function buildCompensationCreatePayload(values: CompensationFormValues): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom,
    annual_ctc_minor: unitsToMinor(values.annualCtc),
    currency: values.currency.trim().toUpperCase(),
    revision_type: values.revisionType,
    revision_reason: values.revisionReason.trim(),
  };
}

export function validateCompensationForm(values: CompensationFormValues): CompensationFormErrors {
  const errors: CompensationFormErrors = {};

  if (!values.effectiveFrom) errors.effectiveFrom = "Effective date is required.";

  const minor = unitsToMinor(values.annualCtc);
  if (minor === null || minor < 0) errors.annualCtc = "Enter a valid annual CTC.";

  if (values.currency.trim().length !== 3) errors.currency = "Enter a 3-letter currency code (e.g. INR).";
  if (!values.revisionType) errors.revisionType = "Select a revision type.";
  if (!values.revisionReason.trim()) errors.revisionReason = "Revision reason is required.";

  return errors;
}

export const REVISION_TYPE_LABELS: Record<RevisionType, string> = {
  JOINING: "Joining",
  ANNUAL: "Annual revision",
  PROMOTION: "Promotion",
  CORRECTION: "Correction",
  MARKET: "Market adjustment",
};

import type { Grade } from "@/lib/grade/types";

export interface GradeFormValues {
  name: string;
  level: string;
  minCtc: string;
  maxCtc: string;
  noticePeriodDays: string;
  probationDays: string;
  approvalLimit: string;
}

export type GradeFormErrors = Partial<Record<keyof GradeFormValues, string>>;

export const EMPTY_GRADE_FORM_VALUES: GradeFormValues = {
  name: "",
  level: "",
  minCtc: "",
  maxCtc: "",
  noticePeriodDays: "",
  probationDays: "",
  approvalLimit: "",
};

/** Money fields are integer minor units (paise) on the wire, per ADR-0006 — the form works
 * in whole rupees and converts at the boundary. */
function minorUnitsToRupees(value: number | null): string {
  if (value === null) return "";
  return String(value / 100);
}

function rupeesToMinorUnits(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const rupees = Number(trimmed);
  if (Number.isNaN(rupees)) return null;
  return Math.round(rupees * 100);
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return null;
  return Math.trunc(parsed);
}

export function gradeToFormValues(grade: Grade): GradeFormValues {
  return {
    name: grade.name,
    level: grade.level === null ? "" : String(grade.level),
    minCtc: minorUnitsToRupees(grade.min_ctc),
    maxCtc: minorUnitsToRupees(grade.max_ctc),
    noticePeriodDays: grade.notice_period_days === null ? "" : String(grade.notice_period_days),
    probationDays: grade.probation_days === null ? "" : String(grade.probation_days),
    approvalLimit: minorUnitsToRupees(grade.approval_limit),
  };
}

/** Full payload for `POST /grades` — every field the form collects. */
export function buildCreatePayload(values: GradeFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    level: intOrNull(values.level),
    min_ctc: rupeesToMinorUnits(values.minCtc),
    max_ctc: rupeesToMinorUnits(values.maxCtc),
    notice_period_days: intOrNull(values.noticePeriodDays),
    probation_days: intOrNull(values.probationDays),
    approval_limit: rupeesToMinorUnits(values.approvalLimit),
  };
}

/** Diff-only payload for `PATCH /grades/{id}` — mirrors `buildUpdatePatch` for Designation. */
export function buildUpdatePatch(values: GradeFormValues, grade: Grade): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.name.trim() !== grade.name) patch.name = values.name.trim();

  const level = intOrNull(values.level);
  if (level !== grade.level) patch.level = level;

  const minCtc = rupeesToMinorUnits(values.minCtc);
  if (minCtc !== grade.min_ctc) patch.min_ctc = minCtc;

  const maxCtc = rupeesToMinorUnits(values.maxCtc);
  if (maxCtc !== grade.max_ctc) patch.max_ctc = maxCtc;

  const noticePeriodDays = intOrNull(values.noticePeriodDays);
  if (noticePeriodDays !== grade.notice_period_days) patch.notice_period_days = noticePeriodDays;

  const probationDays = intOrNull(values.probationDays);
  if (probationDays !== grade.probation_days) patch.probation_days = probationDays;

  const approvalLimit = rupeesToMinorUnits(values.approvalLimit);
  if (approvalLimit !== grade.approval_limit) patch.approval_limit = approvalLimit;

  return patch;
}

export function validateGradeForm(values: GradeFormValues): GradeFormErrors {
  const errors: GradeFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "Grade name is required.";
  }

  const minCtc = rupeesToMinorUnits(values.minCtc);
  const maxCtc = rupeesToMinorUnits(values.maxCtc);
  if (minCtc !== null && maxCtc !== null && minCtc > maxCtc) {
    errors.maxCtc = "Max CTC must not be less than min CTC.";
  }

  return errors;
}

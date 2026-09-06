import type { ErrorDetail } from "@/lib/api/types";
import type { OvertimePolicy, OvertimePolicyVersion } from "@/lib/overtime-policy/types";

export interface OvertimePolicyFormValues {
  name: string;
  code: string;
}

export const EMPTY_OVERTIME_POLICY_FORM_VALUES: OvertimePolicyFormValues = { name: "", code: "" };

export interface OvertimePolicyFormErrors {
  name?: string;
  code?: string;
}

export function validateOvertimePolicyForm(
  values: OvertimePolicyFormValues,
): OvertimePolicyFormErrors {
  const errors: OvertimePolicyFormErrors = {};
  if (!values.name.trim()) errors.name = "Name is required.";
  return errors;
}

export function buildOvertimePolicyCreatePayload(
  values: OvertimePolicyFormValues,
): Record<string, unknown> {
  return { name: values.name.trim(), code: values.code.trim() || null };
}

export function buildOvertimePolicyUpdatePatch(
  values: OvertimePolicyFormValues,
  current: OvertimePolicy,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== current.name) patch.name = values.name.trim();
  const code = values.code.trim() || null;
  if (code !== current.code) patch.code = code;
  return patch;
}

export interface OvertimeRateRowFormValue {
  dayClass: string;
  classificationCode: string;
  multiplierDecimal: string;
}

export const EMPTY_RATE_ROW: OvertimeRateRowFormValue = {
  dayClass: "NORMAL",
  classificationCode: "",
  multiplierDecimal: "",
};

export interface OvertimePolicyVersionFormValues {
  effectiveFrom: string;
  eligibility: string;
  minOtMinutes: string;
  roundingMinutes: string;
  roundingMode: string;
  requiresPreApproval: boolean;
  requiresPostApproval: boolean;
  dailyCapMinutes: string;
  weeklyCapMinutes: string;
  monthlyCapMinutes: string;
  compOffInsteadOfPay: boolean;
  compOffExpiryDays: string;
  compOffDayLengthMinutes: string;
  nightOtMode: string;
  nightWindowStart: string;
  nightWindowEnd: string;
  approvalChain: string;
  rateRows: OvertimeRateRowFormValue[];
}

export const EMPTY_OVERTIME_POLICY_VERSION_FORM_VALUES: OvertimePolicyVersionFormValues = {
  effectiveFrom: "",
  eligibility: "SHIFT_FLAG",
  minOtMinutes: "0",
  roundingMinutes: "",
  roundingMode: "NONE",
  requiresPreApproval: false,
  requiresPostApproval: true,
  dailyCapMinutes: "",
  weeklyCapMinutes: "",
  monthlyCapMinutes: "",
  compOffInsteadOfPay: false,
  compOffExpiryDays: "",
  compOffDayLengthMinutes: "",
  nightOtMode: "SHIFT_FLAG",
  nightWindowStart: "",
  nightWindowEnd: "",
  approvalChain: "MANAGER",
  rateRows: [],
};

export interface OvertimePolicyVersionFormErrors {
  effectiveFrom?: string;
  rateRows?: string;
  nightWindow?: string;
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return null;
  return Math.trunc(parsed);
}

export function overtimePolicyVersionToFormValues(
  version: OvertimePolicyVersion,
): OvertimePolicyVersionFormValues {
  return {
    effectiveFrom: version.effective_from ?? "",
    eligibility: version.eligibility,
    minOtMinutes: String(version.min_ot_minutes),
    roundingMinutes: version.rounding_minutes === null ? "" : String(version.rounding_minutes),
    roundingMode: version.rounding_mode,
    requiresPreApproval: version.requires_pre_approval,
    requiresPostApproval: version.requires_post_approval,
    dailyCapMinutes: version.daily_cap_minutes === null ? "" : String(version.daily_cap_minutes),
    weeklyCapMinutes: version.weekly_cap_minutes === null ? "" : String(version.weekly_cap_minutes),
    monthlyCapMinutes:
      version.monthly_cap_minutes === null ? "" : String(version.monthly_cap_minutes),
    compOffInsteadOfPay: version.comp_off_instead_of_pay,
    compOffExpiryDays:
      version.comp_off_expiry_days === null ? "" : String(version.comp_off_expiry_days),
    compOffDayLengthMinutes:
      version.comp_off_day_length_minutes === null
        ? ""
        : String(version.comp_off_day_length_minutes),
    nightOtMode: version.night_ot_mode,
    nightWindowStart: version.night_window_start ?? "",
    nightWindowEnd: version.night_window_end ?? "",
    approvalChain: version.approval_chain,
    rateRows: version.rate_rows
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((r) => ({
        dayClass: r.day_class,
        classificationCode: r.classification_code,
        multiplierDecimal: r.multiplier_decimal ?? "",
      })),
  };
}

export function buildOvertimePolicyVersionPayload(
  values: OvertimePolicyVersionFormValues,
): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom || null,
    eligibility: values.eligibility,
    min_ot_minutes: intOrNull(values.minOtMinutes) ?? 0,
    rounding_minutes: intOrNull(values.roundingMinutes),
    rounding_mode: values.roundingMode,
    requires_pre_approval: values.requiresPreApproval,
    requires_post_approval: values.requiresPostApproval,
    daily_cap_minutes: intOrNull(values.dailyCapMinutes),
    weekly_cap_minutes: intOrNull(values.weeklyCapMinutes),
    monthly_cap_minutes: intOrNull(values.monthlyCapMinutes),
    comp_off_instead_of_pay: values.compOffInsteadOfPay,
    comp_off_expiry_days: intOrNull(values.compOffExpiryDays),
    comp_off_day_length_minutes: intOrNull(values.compOffDayLengthMinutes),
    night_ot_mode: values.nightOtMode,
    night_window_start: values.nightWindowStart.trim() || null,
    night_window_end: values.nightWindowEnd.trim() || null,
    approval_chain: values.approvalChain,
    rate_rows: values.rateRows.map((row) => ({
      day_class: row.dayClass,
      classification_code: row.classificationCode.trim(),
      multiplier_decimal: row.multiplierDecimal.trim() || null,
    })),
  };
}

/** Light client-side pre-check — the backend is authoritative. */
export function validateOvertimePolicyVersionForm(
  values: OvertimePolicyVersionFormValues,
): OvertimePolicyVersionFormErrors {
  const errors: OvertimePolicyVersionFormErrors = {};
  if ((values.nightWindowStart.trim() !== "") !== (values.nightWindowEnd.trim() !== "")) {
    errors.nightWindow = "Night window start and end must be given together.";
  }
  return errors;
}

export function mapOvertimePolicyVersionApiErrors(
  details: ErrorDetail[],
): OvertimePolicyVersionFormErrors {
  const errors: OvertimePolicyVersionFormErrors = {};
  for (const detail of details) {
    if (detail.field === "rate_rows") errors.rateRows = detail.message;
    if (detail.field === "effective_from") errors.effectiveFrom = detail.message;
  }
  return errors;
}

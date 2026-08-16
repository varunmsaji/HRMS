import type { PaymentMode } from "@/lib/employee/types";

export interface BankFormValues {
  effectiveFrom: string;
  accountHolderName: string;
  accountNumber: string;
  bankName: string;
  ifsc: string;
  branchName: string;
  paymentMode: PaymentMode | "";
}

export type BankFormErrors = Partial<Record<keyof BankFormValues, string>>;

export const EMPTY_BANK_FORM_VALUES: BankFormValues = {
  effectiveFrom: "",
  accountHolderName: "",
  accountNumber: "",
  bankName: "",
  ifsc: "",
  branchName: "",
  paymentMode: "",
};

/** Full payload for `POST /employees/{id}/bank`. No `revision_reason` field — Banking doesn't
 * have one (unlike Statutory/Compensation), per the backend schema. */
export function buildBankCreatePayload(values: BankFormValues): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom,
    account_holder_name: values.accountHolderName.trim() || null,
    account_number_enc: values.accountNumber.trim() || null,
    bank_name: values.bankName.trim() || null,
    ifsc: values.ifsc.trim() || null,
    branch_name: values.branchName.trim() || null,
    payment_mode: values.paymentMode,
  };
}

export function validateBankForm(values: BankFormValues): BankFormErrors {
  const errors: BankFormErrors = {};
  if (!values.effectiveFrom) errors.effectiveFrom = "Effective date is required.";
  if (!values.paymentMode) errors.paymentMode = "Select a payment mode.";
  return errors;
}

export const PAYMENT_MODE_LABELS: Record<PaymentMode, string> = {
  BANK: "Bank transfer",
  CASH: "Cash",
  CHEQUE: "Cheque",
  UPI: "UPI",
};

/** Never render `account_number_enc` unmasked — this is the only place a raw account number
 * should ever touch a display string, and even here only the last 4 digits survive. */
export function maskAccountNumber(value: string | null): string {
  if (!value) return "Not on file";
  const trimmed = value.trim();
  if (trimmed.length <= 4) return "•".repeat(trimmed.length);
  return `${"•".repeat(trimmed.length - 4)}${trimmed.slice(-4)}`;
}

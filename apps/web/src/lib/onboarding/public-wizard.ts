/** Form-value shapes for the candidate-facing wizard (O4) — one interface per section, each
 * mirroring `apps/api/src/hrms/modules/onboarding/schemas.py`'s section schemas field-for-field
 * (`PersonalInfoSection`/`AddressInfoSection`/`EmergencyContactSection`/`BankInfoSection`/
 * `StatutoryInfoSection`). Numeric/boolean/enum fields follow the same string-in-a-form,
 * typed-on-submit convention as `lib/employee/validate-statutory.ts`/`validate-bank.ts`. */

export type PaymentMode = "BANK" | "CASH" | "CHEQUE" | "UPI";
export const PAYMENT_MODE_VALUES: PaymentMode[] = ["BANK", "CASH", "CHEQUE", "UPI"];
export const PAYMENT_MODE_LABELS: Record<PaymentMode, string> = {
  BANK: "Bank transfer",
  CASH: "Cash",
  CHEQUE: "Cheque",
  UPI: "UPI",
};

export type TaxRegime = "OLD" | "NEW";
export const TAX_REGIME_VALUES: TaxRegime[] = ["OLD", "NEW"];

// --- Personal info -------------------------------------------------------------------------

export interface PersonalInfoFormValues {
  firstName: string;
  middleName: string;
  lastName: string;
  dateOfBirth: string;
  gender: string;
  bloodGroup: string;
  maritalStatus: string;
  nationality: string;
  photoUrl: string;
}

export const EMPTY_PERSONAL_INFO: PersonalInfoFormValues = {
  firstName: "",
  middleName: "",
  lastName: "",
  dateOfBirth: "",
  gender: "",
  bloodGroup: "",
  maritalStatus: "",
  nationality: "",
  photoUrl: "",
};

export function personalInfoFromSection(section: Record<string, unknown>): PersonalInfoFormValues {
  return {
    firstName: (section.first_name as string | undefined) ?? "",
    middleName: (section.middle_name as string | undefined) ?? "",
    lastName: (section.last_name as string | undefined) ?? "",
    dateOfBirth: (section.date_of_birth as string | undefined) ?? "",
    gender: (section.gender as string | undefined) ?? "",
    bloodGroup: (section.blood_group as string | undefined) ?? "",
    maritalStatus: (section.marital_status as string | undefined) ?? "",
    nationality: (section.nationality as string | undefined) ?? "",
    photoUrl: (section.photo_url as string | undefined) ?? "",
  };
}

export function personalInfoToPayload(values: PersonalInfoFormValues): Record<string, unknown> {
  return {
    first_name: values.firstName.trim(),
    middle_name: values.middleName.trim() || null,
    last_name: values.lastName.trim() || null,
    date_of_birth: values.dateOfBirth || null,
    gender: values.gender.trim() || null,
    blood_group: values.bloodGroup.trim() || null,
    marital_status: values.maritalStatus.trim() || null,
    nationality: values.nationality.trim() || null,
    photo_url: values.photoUrl.trim() || null,
  };
}

export function validatePersonalInfo(
  values: PersonalInfoFormValues,
): Partial<Record<keyof PersonalInfoFormValues, string>> {
  const errors: Partial<Record<keyof PersonalInfoFormValues, string>> = {};
  if (!values.firstName.trim()) errors.firstName = "First name is required.";
  return errors;
}

// --- Address info ----------------------------------------------------------------------------

export interface AddressInfoFormValues {
  addressLine1: string;
  addressLine2: string;
  city: string;
  stateCode: string;
  pincode: string;
  countryCode: string;
}

export const EMPTY_ADDRESS_INFO: AddressInfoFormValues = {
  addressLine1: "",
  addressLine2: "",
  city: "",
  stateCode: "",
  pincode: "",
  countryCode: "",
};

export function addressInfoFromSection(section: Record<string, unknown>): AddressInfoFormValues {
  return {
    addressLine1: (section.address_line1 as string | undefined) ?? "",
    addressLine2: (section.address_line2 as string | undefined) ?? "",
    city: (section.city as string | undefined) ?? "",
    stateCode: (section.state_code as string | undefined) ?? "",
    pincode: (section.pincode as string | undefined) ?? "",
    countryCode: (section.country_code as string | undefined) ?? "",
  };
}

export function addressInfoToPayload(values: AddressInfoFormValues): Record<string, unknown> {
  return {
    address_line1: values.addressLine1.trim() || null,
    address_line2: values.addressLine2.trim() || null,
    city: values.city.trim() || null,
    state_code: values.stateCode.trim() || null,
    pincode: values.pincode.trim() || null,
    country_code: values.countryCode.trim() || null,
  };
}

// --- Emergency contact -------------------------------------------------------------------------

export interface EmergencyContactFormValues {
  contactName: string;
  relationship: string;
  phone: string;
}

export const EMPTY_EMERGENCY_CONTACT: EmergencyContactFormValues = {
  contactName: "",
  relationship: "",
  phone: "",
};

export function emergencyContactFromSection(
  section: Record<string, unknown>,
): EmergencyContactFormValues {
  return {
    contactName: (section.contact_name as string | undefined) ?? "",
    relationship: (section.relationship as string | undefined) ?? "",
    phone: (section.phone as string | undefined) ?? "",
  };
}

export function emergencyContactToPayload(values: EmergencyContactFormValues): Record<string, unknown> {
  return {
    contact_name: values.contactName.trim(),
    relationship: values.relationship.trim() || null,
    phone: values.phone.trim(),
  };
}

export function validateEmergencyContact(
  values: EmergencyContactFormValues,
): Partial<Record<keyof EmergencyContactFormValues, string>> {
  const errors: Partial<Record<keyof EmergencyContactFormValues, string>> = {};
  if (!values.contactName.trim()) errors.contactName = "Contact name is required.";
  if (!values.phone.trim()) errors.phone = "Phone number is required.";
  return errors;
}

// --- Bank info -----------------------------------------------------------------------------

export interface BankInfoFormValues {
  accountHolderName: string;
  accountNumber: string;
  bankName: string;
  ifsc: string;
  branchName: string;
  paymentMode: PaymentMode | "";
}

export const EMPTY_BANK_INFO: BankInfoFormValues = {
  accountHolderName: "",
  accountNumber: "",
  bankName: "",
  ifsc: "",
  branchName: "",
  paymentMode: "",
};

export function bankInfoFromSection(section: Record<string, unknown>): BankInfoFormValues {
  return {
    accountHolderName: (section.account_holder_name as string | undefined) ?? "",
    accountNumber: (section.account_number_enc as string | undefined) ?? "",
    bankName: (section.bank_name as string | undefined) ?? "",
    ifsc: (section.ifsc as string | undefined) ?? "",
    branchName: (section.branch_name as string | undefined) ?? "",
    paymentMode: (section.payment_mode as PaymentMode | undefined) ?? "",
  };
}

export function bankInfoToPayload(values: BankInfoFormValues): Record<string, unknown> {
  return {
    account_holder_name: values.accountHolderName.trim() || null,
    account_number_enc: values.accountNumber.trim() || null,
    bank_name: values.bankName.trim() || null,
    ifsc: values.ifsc.trim() || null,
    branch_name: values.branchName.trim() || null,
    payment_mode: values.paymentMode || null,
  };
}

export function validateBankInfo(
  values: BankInfoFormValues,
): Partial<Record<keyof BankInfoFormValues, string>> {
  const errors: Partial<Record<keyof BankInfoFormValues, string>> = {};
  if (!values.paymentMode) errors.paymentMode = "Payment mode is required.";
  return errors;
}

// --- Statutory info --------------------------------------------------------------------------

export interface StatutoryInfoFormValues {
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
}

export const EMPTY_STATUTORY_INFO: StatutoryInfoFormValues = {
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
};

function numberToFormString(value: unknown): string {
  return typeof value === "number" ? String(value) : "";
}

export function statutoryInfoFromSection(section: Record<string, unknown>): StatutoryInfoFormValues {
  return {
    isPfApplicable: Boolean(section.is_pf_applicable),
    pfNumber: (section.pf_number as string | undefined) ?? "",
    pfWageCeilingOptOut: Boolean(section.pf_wage_ceiling_opt_out),
    vpfAmount: numberToFormString(section.vpf_amount),
    vpfPercentage: numberToFormString(section.vpf_percentage),
    isEsiApplicable: Boolean(section.is_esi_applicable),
    esiIpNumber: (section.esi_ip_number as string | undefined) ?? "",
    ptStateCode: (section.pt_state_code as string | undefined) ?? "",
    isLwfApplicable: Boolean(section.is_lwf_applicable),
    taxRegime: (section.tax_regime as TaxRegime | undefined) ?? "",
    isDirector: Boolean(section.is_director),
    isInternationalWorker: Boolean(section.is_international_worker),
  };
}

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

export function statutoryInfoToPayload(values: StatutoryInfoFormValues): Record<string, unknown> {
  return {
    is_pf_applicable: values.isPfApplicable,
    pf_number: values.pfNumber.trim() || null,
    pf_wage_ceiling_opt_out: values.pfWageCeilingOptOut,
    vpf_amount: intOrNull(values.vpfAmount),
    vpf_percentage: floatOrNull(values.vpfPercentage),
    is_esi_applicable: values.isEsiApplicable,
    esi_ip_number: values.esiIpNumber.trim() || null,
    pt_state_code: values.ptStateCode.trim() || null,
    is_lwf_applicable: values.isLwfApplicable,
    tax_regime: values.taxRegime || null,
    is_director: values.isDirector,
    is_international_worker: values.isInternationalWorker,
  };
}

export function validateStatutoryInfo(
  values: StatutoryInfoFormValues,
): Partial<Record<keyof StatutoryInfoFormValues, string>> {
  const errors: Partial<Record<keyof StatutoryInfoFormValues, string>> = {};
  if (!values.taxRegime) errors.taxRegime = "Tax regime is required.";
  return errors;
}

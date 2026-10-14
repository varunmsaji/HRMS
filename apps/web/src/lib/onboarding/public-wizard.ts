/** Form-value shapes for the candidate-facing wizard (O4) — one interface per section, each
 * mirroring `apps/api/src/hrms/modules/onboarding/schemas.py`'s section schemas field-for-field
 * (`PersonalInfoSection`/`AddressInfoSection`/`EmergencyContactSection`/`BankInfoSection`/
 * `StatutoryInfoSection`). Numeric/boolean/enum fields follow the same string-in-a-form,
 * typed-on-submit convention as `lib/employee/validate-statutory.ts`/`validate-bank.ts`. */

import { INDIA_STATE_CODES } from "@/lib/branch/validate-branch";

export { INDIA_STATE_CODES };

// --- Fixed option sets for dropdown fields ---------------------------------------------------
// Backend fields are plain free-text strings (schemas.py `gender`/`blood_group`/etc. are
// `str | None`), so these are a frontend-only closed list — no backend/migration change needed.

export const GENDER_VALUES = ["MALE", "FEMALE", "OTHER", "PREFER_NOT_TO_SAY"] as const;
export type Gender = (typeof GENDER_VALUES)[number];
export const GENDER_LABELS: Record<Gender, string> = {
  MALE: "Male",
  FEMALE: "Female",
  OTHER: "Other",
  PREFER_NOT_TO_SAY: "Prefer not to say",
};

export const BLOOD_GROUP_VALUES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] as const;

export const MARITAL_STATUS_VALUES = ["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"] as const;
export type MaritalStatus = (typeof MARITAL_STATUS_VALUES)[number];
export const MARITAL_STATUS_LABELS: Record<MaritalStatus, string> = {
  SINGLE: "Single",
  MARRIED: "Married",
  DIVORCED: "Divorced",
  WIDOWED: "Widowed",
};

export const RELATIONSHIP_VALUES = [
  "SPOUSE",
  "FATHER",
  "MOTHER",
  "SON",
  "DAUGHTER",
  "BROTHER",
  "SISTER",
  "GUARDIAN",
  "FRIEND",
  "OTHER",
] as const;
export type Relationship = (typeof RELATIONSHIP_VALUES)[number];
export const RELATIONSHIP_LABELS: Record<Relationship, string> = {
  SPOUSE: "Spouse",
  FATHER: "Father",
  MOTHER: "Mother",
  SON: "Son",
  DAUGHTER: "Daughter",
  BROTHER: "Brother",
  SISTER: "Sister",
  GUARDIAN: "Guardian",
  FRIEND: "Friend",
  OTHER: "Other",
};

export const QUALIFICATION_VALUES = [
  "10TH",
  "12TH",
  "DIPLOMA",
  "BACHELORS",
  "MASTERS",
  "DOCTORATE",
  "OTHER",
] as const;
export type QualificationLevel = (typeof QUALIFICATION_VALUES)[number];
export const QUALIFICATION_LABELS: Record<QualificationLevel, string> = {
  "10TH": "10th / Secondary",
  "12TH": "12th / Higher secondary",
  DIPLOMA: "Diploma",
  BACHELORS: "Bachelor's degree",
  MASTERS: "Master's degree",
  DOCTORATE: "Doctorate",
  OTHER: "Other",
};

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
  fatherOrHusbandName: string;
  panNumber: string;
  aadhaarNumber: string;
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
  fatherOrHusbandName: "",
  panNumber: "",
  aadhaarNumber: "",
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
    fatherOrHusbandName: (section.father_or_husband_name as string | undefined) ?? "",
    panNumber: (section.pan_number_enc as string | undefined) ?? "",
    aadhaarNumber: (section.aadhaar_number_enc as string | undefined) ?? "",
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
    father_or_husband_name: values.fatherOrHusbandName.trim() || null,
    pan_number_enc: values.panNumber.trim().toUpperCase() || null,
    aadhaar_number_enc: values.aadhaarNumber.trim().replace(/\s+/g, "") || null,
    photo_url: values.photoUrl.trim() || null,
  };
}

const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const AADHAAR_PATTERN = /^[0-9]{12}$/;

export function validatePersonalInfo(
  values: PersonalInfoFormValues,
): Partial<Record<keyof PersonalInfoFormValues, string>> {
  const errors: Partial<Record<keyof PersonalInfoFormValues, string>> = {};
  if (!values.firstName.trim()) errors.firstName = "First name is required.";
  const pan = values.panNumber.trim().toUpperCase();
  if (pan && !PAN_PATTERN.test(pan)) {
    errors.panNumber = "Enter a valid 10-character PAN (e.g. ABCDE1234F).";
  }
  const aadhaar = values.aadhaarNumber.trim().replace(/\s+/g, "");
  if (aadhaar && !AADHAAR_PATTERN.test(aadhaar)) {
    errors.aadhaarNumber = "Enter a valid 12-digit Aadhaar number.";
  }
  if (values.dateOfBirth) {
    const dob = new Date(values.dateOfBirth);
    const today = new Date();
    if (Number.isNaN(dob.getTime()) || dob > today) {
      errors.dateOfBirth = "Date of birth cannot be in the future.";
    } else {
      const ageYears = (today.getTime() - dob.getTime()) / (365.25 * 24 * 60 * 60 * 1000);
      if (ageYears < 15 || ageYears > 100) {
        errors.dateOfBirth = "Enter a realistic date of birth.";
      }
    }
  }
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
  permanentSameAsPresent: boolean;
  permanentAddressLine1: string;
  permanentAddressLine2: string;
  permanentCity: string;
  permanentStateCode: string;
  permanentPincode: string;
  permanentCountryCode: string;
}

export const EMPTY_ADDRESS_INFO: AddressInfoFormValues = {
  addressLine1: "",
  addressLine2: "",
  city: "",
  stateCode: "",
  pincode: "",
  countryCode: "",
  permanentSameAsPresent: true,
  permanentAddressLine1: "",
  permanentAddressLine2: "",
  permanentCity: "",
  permanentStateCode: "",
  permanentPincode: "",
  permanentCountryCode: "",
};

export function addressInfoFromSection(section: Record<string, unknown>): AddressInfoFormValues {
  return {
    addressLine1: (section.address_line1 as string | undefined) ?? "",
    addressLine2: (section.address_line2 as string | undefined) ?? "",
    city: (section.city as string | undefined) ?? "",
    stateCode: (section.state_code as string | undefined) ?? "",
    pincode: (section.pincode as string | undefined) ?? "",
    countryCode: (section.country_code as string | undefined) ?? "",
    permanentSameAsPresent:
      section.permanent_same_as_present === undefined
        ? true
        : Boolean(section.permanent_same_as_present),
    permanentAddressLine1: (section.permanent_address_line1 as string | undefined) ?? "",
    permanentAddressLine2: (section.permanent_address_line2 as string | undefined) ?? "",
    permanentCity: (section.permanent_city as string | undefined) ?? "",
    permanentStateCode: (section.permanent_state_code as string | undefined) ?? "",
    permanentPincode: (section.permanent_pincode as string | undefined) ?? "",
    permanentCountryCode: (section.permanent_country_code as string | undefined) ?? "",
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
    permanent_same_as_present: values.permanentSameAsPresent,
    permanent_address_line1: values.permanentSameAsPresent
      ? null
      : values.permanentAddressLine1.trim() || null,
    permanent_address_line2: values.permanentSameAsPresent
      ? null
      : values.permanentAddressLine2.trim() || null,
    permanent_city: values.permanentSameAsPresent ? null : values.permanentCity.trim() || null,
    permanent_state_code: values.permanentSameAsPresent
      ? null
      : values.permanentStateCode.trim() || null,
    permanent_pincode: values.permanentSameAsPresent
      ? null
      : values.permanentPincode.trim() || null,
    permanent_country_code: values.permanentSameAsPresent
      ? null
      : values.permanentCountryCode.trim() || null,
  };
}

const PINCODE_PATTERN = /^[1-9][0-9]{5}$/;

export function validateAddressInfo(
  values: AddressInfoFormValues,
): Partial<Record<keyof AddressInfoFormValues, string>> {
  const errors: Partial<Record<keyof AddressInfoFormValues, string>> = {};
  if (values.stateCode && !(values.stateCode.toUpperCase() in INDIA_STATE_CODES)) {
    errors.stateCode = "Select a valid state or union territory.";
  }
  if (values.pincode.trim() && !PINCODE_PATTERN.test(values.pincode.trim())) {
    errors.pincode = "Enter a valid 6-digit PIN code.";
  }
  if (!values.permanentSameAsPresent) {
    if (
      values.permanentStateCode &&
      !(values.permanentStateCode.toUpperCase() in INDIA_STATE_CODES)
    ) {
      errors.permanentStateCode = "Select a valid state or union territory.";
    }
    if (values.permanentPincode.trim() && !PINCODE_PATTERN.test(values.permanentPincode.trim())) {
      errors.permanentPincode = "Enter a valid 6-digit PIN code.";
    }
  }
  return errors;
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

const PHONE_PATTERN = /^[6-9]\d{9}$/;

export function validateEmergencyContact(
  values: EmergencyContactFormValues,
): Partial<Record<keyof EmergencyContactFormValues, string>> {
  const errors: Partial<Record<keyof EmergencyContactFormValues, string>> = {};
  if (!values.contactName.trim()) errors.contactName = "Contact name is required.";
  const phone = values.phone.trim().replace(/[\s-]/g, "").replace(/^\+?91/, "");
  if (!values.phone.trim()) {
    errors.phone = "Phone number is required.";
  } else if (!PHONE_PATTERN.test(phone)) {
    errors.phone = "Enter a valid 10-digit mobile number.";
  }
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

const IFSC_PATTERN = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const ACCOUNT_NUMBER_PATTERN = /^\d{9,18}$/;

export function validateBankInfo(
  values: BankInfoFormValues,
): Partial<Record<keyof BankInfoFormValues, string>> {
  const errors: Partial<Record<keyof BankInfoFormValues, string>> = {};
  if (!values.paymentMode) errors.paymentMode = "Payment mode is required.";

  const ifsc = values.ifsc.trim().toUpperCase();
  const accountNumber = values.accountNumber.trim();
  if (values.paymentMode === "BANK") {
    if (!accountNumber) {
      errors.accountNumber = "Account number is required for bank transfer.";
    } else if (!ACCOUNT_NUMBER_PATTERN.test(accountNumber)) {
      errors.accountNumber = "Enter a valid account number (9-18 digits).";
    }
    if (!ifsc) {
      errors.ifsc = "IFSC is required for bank transfer.";
    } else if (!IFSC_PATTERN.test(ifsc)) {
      errors.ifsc = "Enter a valid 11-character IFSC code (e.g. SBIN0001234).";
    }
  } else {
    if (accountNumber && !ACCOUNT_NUMBER_PATTERN.test(accountNumber)) {
      errors.accountNumber = "Enter a valid account number (9-18 digits).";
    }
    if (ifsc && !IFSC_PATTERN.test(ifsc)) {
      errors.ifsc = "Enter a valid 11-character IFSC code (e.g. SBIN0001234).";
    }
  }
  return errors;
}

// --- Statutory info --------------------------------------------------------------------------

export interface StatutoryInfoFormValues {
  isPfApplicable: boolean;
  pfNumber: string;
  uanNumber: string;
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
  uanNumber: "",
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
    uanNumber: (section.uan_number as string | undefined) ?? "",
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
    uan_number: values.uanNumber.trim() || null,
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

const UAN_PATTERN = /^\d{12}$/;
const ESI_IP_PATTERN = /^\d{10}$/;

export function validateStatutoryInfo(
  values: StatutoryInfoFormValues,
): Partial<Record<keyof StatutoryInfoFormValues, string>> {
  const errors: Partial<Record<keyof StatutoryInfoFormValues, string>> = {};
  if (!values.taxRegime) errors.taxRegime = "Tax regime is required.";
  const uan = values.uanNumber.trim();
  if (uan && !UAN_PATTERN.test(uan)) {
    errors.uanNumber = "Enter a valid 12-digit UAN.";
  }
  const esiIp = values.esiIpNumber.trim();
  if (esiIp && !ESI_IP_PATTERN.test(esiIp)) {
    errors.esiIpNumber = "Enter a valid 10-digit ESI IP number.";
  }
  if (values.ptStateCode && !(values.ptStateCode.toUpperCase() in INDIA_STATE_CODES)) {
    errors.ptStateCode = "Select a valid state or union territory.";
  }
  return errors;
}

// --- Compensation info (E-02 part 3) --------------------------------------------------------

export interface CompensationInfoFormValues {
  annualCtc: string;
  currency: string;
}

export const EMPTY_COMPENSATION_INFO: CompensationInfoFormValues = {
  annualCtc: "",
  currency: "",
};

/** `annual_ctc_minor` is integer minor units on the wire (e.g. paise) — matches
 * `lib/employee/validate-compensation.ts`'s own money-field convention exactly; the form works
 * in whole currency units and converts at the boundary. */
function ctcUnitsToMinor(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const amount = Number(trimmed);
  if (Number.isNaN(amount)) return null;
  return Math.round(amount * 100);
}

function ctcMinorToUnits(value: unknown): string {
  return typeof value === "number" ? String(value / 100) : "";
}

export function compensationInfoFromSection(
  section: Record<string, unknown>,
): CompensationInfoFormValues {
  return {
    annualCtc: ctcMinorToUnits(section.annual_ctc_minor),
    currency: (section.currency as string | undefined) ?? "",
  };
}

export function compensationInfoToPayload(
  values: CompensationInfoFormValues,
): Record<string, unknown> {
  // A blank currency is omitted: the server fills in the company's own configured currency.
  const currency = values.currency.trim().toUpperCase();
  return {
    annual_ctc_minor: ctcUnitsToMinor(values.annualCtc),
    ...(currency ? { currency } : {}),
  };
}

export function validateCompensationInfo(
  values: CompensationInfoFormValues,
): Partial<Record<keyof CompensationInfoFormValues, string>> {
  const errors: Partial<Record<keyof CompensationInfoFormValues, string>> = {};
  const minor = ctcUnitsToMinor(values.annualCtc);
  if (minor === null || minor < 0) errors.annualCtc = "Enter a valid annual CTC.";
  if (values.currency.trim() && values.currency.trim().length !== 3) {
    errors.currency = "Enter a 3-letter currency code (e.g. INR).";
  }
  return errors;
}

// --- Previous employment info (E-02 part 4) -------------------------------------------------

export interface PreviousEmploymentRowValues {
  companyName: string;
  designation: string;
  fromDate: string;
  toDate: string;
  lastCtc: string;
  reasonForLeaving: string;
  hadPriorPfMembership: boolean;
  previousUan: string;
  previousPfAccountNumber: string;
  previousEsiIpNumber: string;
}

export const EMPTY_PREVIOUS_EMPLOYMENT_ROW: PreviousEmploymentRowValues = {
  companyName: "",
  designation: "",
  fromDate: "",
  toDate: "",
  lastCtc: "",
  reasonForLeaving: "",
  hadPriorPfMembership: false,
  previousUan: "",
  previousPfAccountNumber: "",
  previousEsiIpNumber: "",
};

export interface PreviousEmploymentFormValues {
  items: PreviousEmploymentRowValues[];
}

export const EMPTY_PREVIOUS_EMPLOYMENT_INFO: PreviousEmploymentFormValues = { items: [] };

function rowFromItem(item: Record<string, unknown>): PreviousEmploymentRowValues {
  return {
    companyName: (item.company_name as string | undefined) ?? "",
    designation: (item.designation as string | undefined) ?? "",
    fromDate: (item.from_date as string | undefined) ?? "",
    toDate: (item.to_date as string | undefined) ?? "",
    lastCtc: ctcMinorToUnits(item.last_ctc_minor),
    reasonForLeaving: (item.reason_for_leaving as string | undefined) ?? "",
    hadPriorPfMembership: Boolean(item.had_prior_pf_membership),
    previousUan: (item.previous_uan as string | undefined) ?? "",
    previousPfAccountNumber: (item.previous_pf_account_number as string | undefined) ?? "",
    previousEsiIpNumber: (item.previous_esi_ip_number as string | undefined) ?? "",
  };
}

export function previousEmploymentFromSection(
  section: Record<string, unknown>,
): PreviousEmploymentFormValues {
  const items = Array.isArray(section.items) ? section.items : [];
  return { items: items.map((item) => rowFromItem(item as Record<string, unknown>)) };
}

function rowToPayload(row: PreviousEmploymentRowValues): Record<string, unknown> {
  return {
    company_name: row.companyName.trim(),
    designation: row.designation.trim() || null,
    from_date: row.fromDate || null,
    to_date: row.toDate || null,
    last_ctc_minor: ctcUnitsToMinor(row.lastCtc),
    reason_for_leaving: row.reasonForLeaving.trim() || null,
    had_prior_pf_membership: row.hadPriorPfMembership,
    previous_uan: row.previousUan.trim() || null,
    previous_pf_account_number: row.previousPfAccountNumber.trim() || null,
    previous_esi_ip_number: row.previousEsiIpNumber.trim() || null,
  };
}

export function previousEmploymentToPayload(
  values: PreviousEmploymentFormValues,
): Record<string, unknown> {
  return { items: values.items.map(rowToPayload) };
}

export function validatePreviousEmployment(
  values: PreviousEmploymentFormValues,
): Partial<Record<"items", string>> {
  const errors: Partial<Record<"items", string>> = {};
  const hasIncompleteRow = values.items.some(
    (row) => !row.companyName.trim() || !row.fromDate,
  );
  if (hasIncompleteRow) {
    errors.items = "Each entry needs at least a company name and a from date.";
    return errors;
  }
  const today = new Date().toISOString().slice(0, 10);
  const hasBadDates = values.items.some((row) => {
    if (row.fromDate > today) return true;
    if (row.toDate && (row.toDate < row.fromDate || row.toDate > today)) return true;
    return false;
  });
  if (hasBadDates) {
    errors.items = "Each entry's dates must be in order and not in the future.";
  }
  return errors;
}

// --- Education info (E-02 part 5) -----------------------------------------------------------

export interface EducationRowValues {
  qualification: string;
  institutionName: string;
  yearOfPassing: string;
}

export const EMPTY_EDUCATION_ROW: EducationRowValues = {
  qualification: "",
  institutionName: "",
  yearOfPassing: "",
};

export interface EducationFormValues {
  items: EducationRowValues[];
}

export const EMPTY_EDUCATION_INFO: EducationFormValues = { items: [] };

function educationRowFromItem(item: Record<string, unknown>): EducationRowValues {
  return {
    qualification: (item.qualification as string | undefined) ?? "",
    institutionName: (item.institution_name as string | undefined) ?? "",
    yearOfPassing:
      item.year_of_passing === null || item.year_of_passing === undefined
        ? ""
        : String(item.year_of_passing),
  };
}

export function educationFromSection(section: Record<string, unknown>): EducationFormValues {
  const items = Array.isArray(section.items) ? section.items : [];
  return { items: items.map((item) => educationRowFromItem(item as Record<string, unknown>)) };
}

function educationRowToPayload(row: EducationRowValues): Record<string, unknown> {
  return {
    qualification: row.qualification.trim(),
    institution_name: row.institutionName.trim() || null,
    year_of_passing: row.yearOfPassing ? Number(row.yearOfPassing) : null,
  };
}

export function educationToPayload(values: EducationFormValues): Record<string, unknown> {
  return { items: values.items.map(educationRowToPayload) };
}

export function validateEducation(
  values: EducationFormValues,
): Partial<Record<"items", string>> {
  const errors: Partial<Record<"items", string>> = {};
  const hasIncompleteRow = values.items.some((row) => !row.qualification.trim());
  if (hasIncompleteRow) {
    errors.items = "Each entry needs at least a qualification.";
    return errors;
  }
  const currentYear = new Date().getFullYear();
  const hasBadYear = values.items.some((row) => {
    if (!row.yearOfPassing) return false;
    const year = Number(row.yearOfPassing);
    return !Number.isInteger(year) || year < 1950 || year > currentYear + 1;
  });
  if (hasBadYear) {
    errors.items = `Year of passing must be between 1950 and ${currentYear + 1}.`;
  }
  return errors;
}

// --- Nominee info (market-parity onboarding-data pass, part 6) ------------------------------
//
// PF/Gratuity nominee declaration + ESI family details — mirrors `PreviousEmploymentFormValues`/
// `EducationFormValues`'s exact repeatable-rows shape, plus a minor/guardian conditional block
// and two independent nominee-scheme percentages, each validated to sum to <=100 across the
// submitted list (mirroring `apps.api.../onboarding/schemas.py`'s `NomineeInfoSection` validator).

export interface NomineeRowValues {
  fullName: string;
  relationship: string;
  dateOfBirth: string;
  gender: string;
  isMinor: boolean;
  guardianName: string;
  guardianRelationship: string;
  aadhaarNumber: string;
  isPfNominee: boolean;
  pfNomineeSharePercentage: string;
  isGratuityNominee: boolean;
  gratuityNomineeSharePercentage: string;
  isEsiDependent: boolean;
}

export const EMPTY_NOMINEE_ROW: NomineeRowValues = {
  fullName: "",
  relationship: "",
  dateOfBirth: "",
  gender: "",
  isMinor: false,
  guardianName: "",
  guardianRelationship: "",
  aadhaarNumber: "",
  isPfNominee: false,
  pfNomineeSharePercentage: "",
  isGratuityNominee: false,
  gratuityNomineeSharePercentage: "",
  isEsiDependent: false,
};

export interface NomineeFormValues {
  items: NomineeRowValues[];
}

export const EMPTY_NOMINEE_INFO: NomineeFormValues = { items: [] };

function nomineeRowFromItem(item: Record<string, unknown>): NomineeRowValues {
  return {
    fullName: (item.full_name as string | undefined) ?? "",
    relationship: (item.relationship as string | undefined) ?? "",
    dateOfBirth: (item.date_of_birth as string | undefined) ?? "",
    gender: (item.gender as string | undefined) ?? "",
    isMinor: Boolean(item.is_minor),
    guardianName: (item.guardian_name as string | undefined) ?? "",
    guardianRelationship: (item.guardian_relationship as string | undefined) ?? "",
    aadhaarNumber: (item.aadhaar_number_enc as string | undefined) ?? "",
    isPfNominee: Boolean(item.is_pf_nominee),
    pfNomineeSharePercentage:
      item.pf_nominee_share_percentage === null || item.pf_nominee_share_percentage === undefined
        ? ""
        : String(item.pf_nominee_share_percentage),
    isGratuityNominee: Boolean(item.is_gratuity_nominee),
    gratuityNomineeSharePercentage:
      item.gratuity_nominee_share_percentage === null ||
      item.gratuity_nominee_share_percentage === undefined
        ? ""
        : String(item.gratuity_nominee_share_percentage),
    isEsiDependent: Boolean(item.is_esi_dependent),
  };
}

export function nomineeFromSection(section: Record<string, unknown>): NomineeFormValues {
  const items = Array.isArray(section.items) ? section.items : [];
  return { items: items.map((item) => nomineeRowFromItem(item as Record<string, unknown>)) };
}

function nomineeRowToPayload(row: NomineeRowValues): Record<string, unknown> {
  return {
    full_name: row.fullName.trim(),
    relationship: row.relationship.trim(),
    date_of_birth: row.dateOfBirth || null,
    gender: row.gender.trim() || null,
    is_minor: row.isMinor,
    guardian_name: row.isMinor ? row.guardianName.trim() || null : null,
    guardian_relationship: row.isMinor ? row.guardianRelationship.trim() || null : null,
    aadhaar_number_enc: row.aadhaarNumber.trim() || null,
    is_pf_nominee: row.isPfNominee,
    pf_nominee_share_percentage: row.isPfNominee ? Number(row.pfNomineeSharePercentage) : null,
    is_gratuity_nominee: row.isGratuityNominee,
    gratuity_nominee_share_percentage: row.isGratuityNominee
      ? Number(row.gratuityNomineeSharePercentage)
      : null,
    is_esi_dependent: row.isEsiDependent,
  };
}

export function nomineeToPayload(values: NomineeFormValues): Record<string, unknown> {
  return { items: values.items.map(nomineeRowToPayload) };
}

/** Running totals across the submitted list — also what `NomineeInfoStep` renders as a live
 * indicator next to each scheme's rows, so the candidate sees the 100% ceiling before submitting
 * rather than only after a rejected PATCH. */
export function nomineePfPercentageTotal(values: NomineeFormValues): number {
  return values.items
    .filter((row) => row.isPfNominee)
    .reduce((sum, row) => sum + (Number(row.pfNomineeSharePercentage) || 0), 0);
}

export function nomineeGratuityPercentageTotal(values: NomineeFormValues): number {
  return values.items
    .filter((row) => row.isGratuityNominee)
    .reduce((sum, row) => sum + (Number(row.gratuityNomineeSharePercentage) || 0), 0);
}

export function validateNominee(values: NomineeFormValues): Partial<Record<"items", string>> {
  const errors: Partial<Record<"items", string>> = {};
  const hasIncompleteRow = values.items.some((row) => {
    if (!row.fullName.trim() || !row.relationship.trim()) return true;
    if (row.isMinor && !row.guardianName.trim()) return true;
    if (row.isPfNominee && !row.pfNomineeSharePercentage) return true;
    if (row.isGratuityNominee && !row.gratuityNomineeSharePercentage) return true;
    return false;
  });
  if (hasIncompleteRow) {
    errors.items =
      "Each entry needs a name and relationship; minors need a guardian name, and a " +
      "nominee scheme needs its share percentage.";
    return errors;
  }
  const hasBadAadhaar = values.items.some((row) => {
    const aadhaar = row.aadhaarNumber.trim().replace(/\s+/g, "");
    return aadhaar !== "" && !AADHAAR_PATTERN.test(aadhaar);
  });
  if (hasBadAadhaar) {
    errors.items = "Enter a valid 12-digit Aadhaar number for each nominee that has one.";
    return errors;
  }
  if (nomineePfPercentageTotal(values) > 100) {
    errors.items = "PF nominee share percentages add up to more than 100%.";
  } else if (nomineeGratuityPercentageTotal(values) > 100) {
    errors.items = "Gratuity nominee share percentages add up to more than 100%.";
  }
  return errors;
}

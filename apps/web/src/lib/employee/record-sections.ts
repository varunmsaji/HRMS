/** The employee-record sections mobile already has and web lacked: identity, experience, education
 * and dependents / nominees. Field lists, wording and permissions mirror the mobile app
 * (`apps/mobile/lib/features/profile/presentation/employee_record_sections.dart` and
 * `employees/domain/employee_forms.dart`) and the API schemas (`EmployeeIdentityUpdate`,
 * `EmployeeExperienceCreate`, `EmployeeEducationCreate`, `EmployeeDependentCreate`). */

import { GENDER_OPTIONS } from "@/lib/employee/validate-employee";

export type RecordFieldKind =
  | "text"
  | "multiline"
  | "date"
  | "money"
  | "integer"
  | "decimal"
  | "toggle"
  | "select"
  | "pan"
  | "aadhaar";

/** One input on a section's form. `showWhen` names a toggle that must be on for it to apply. */
export interface RecordFormField {
  key: string;
  label: string;
  kind: RecordFieldKind;
  required?: boolean;
  showWhen?: string;
  options?: readonly string[];
  hint?: string;
  maxLength?: number;
}

/** One value shown on a record card. */
export interface RecordDisplayField {
  key: string;
  label: string;
  format?: "text" | "yesNo" | "money";
}

export type RecordRow = Record<string, unknown> & { id?: string; version?: number };

export interface ListSectionConfig {
  key: "experience" | "education" | "dependents";
  title: string;
  /** Appended to `/employees/{id}`. */
  path: string;
  viewPermission: string;
  note: string;
  addLabel: string;
  deleteConfirm: string;
  emptyTitle: string;
  savedToast: string;
  cardTitle: (row: RecordRow) => string;
  display: RecordDisplayField[];
  form: RecordFormField[];
}

export const UPDATE_SENSITIVE = "EMPLOYEE.UPDATE_SENSITIVE";

const str = (row: RecordRow, key: string) => (row[key] == null ? "" : String(row[key]));

export const EXPERIENCE_SECTION: ListSectionConfig = {
  key: "experience",
  title: "Experience",
  path: "/experience",
  viewPermission: "EMPLOYEE.VIEW_EXPERIENCE",
  note: "Previous employment is visible only to holders of EMPLOYEE.VIEW_EXPERIENCE.",
  addLabel: "Add experience",
  deleteConfirm: "Delete this experience entry?",
  emptyTitle: "No previous employment on record.",
  savedToast: "Experience added",
  cardTitle: (row) => str(row, "company_name"),
  display: [
    { key: "designation", label: "Designation" },
    { key: "from_date", label: "From" },
    { key: "to_date", label: "To" },
    { key: "last_ctc_minor", label: "Last CTC", format: "money" },
    { key: "reason_for_leaving", label: "Reason for leaving" },
    { key: "had_prior_pf_membership", label: "Prior PF membership", format: "yesNo" },
    { key: "previous_uan", label: "Previous UAN" },
    { key: "previous_pf_account_number", label: "Previous PF account" },
    { key: "previous_esi_ip_number", label: "Previous ESI IP" },
  ],
  form: [
    { key: "company_name", label: "Company name", kind: "text", required: true, maxLength: 200 },
    { key: "designation", label: "Designation", kind: "text", maxLength: 150 },
    { key: "from_date", label: "From", kind: "date", required: true },
    { key: "to_date", label: "To", kind: "date" },
    { key: "last_ctc_minor", label: "Last CTC", kind: "money" },
    { key: "reason_for_leaving", label: "Reason for leaving", kind: "multiline" },
    { key: "had_prior_pf_membership", label: "Had a prior PF membership", kind: "toggle" },
    { key: "previous_uan", label: "Previous UAN", kind: "text", maxLength: 20 },
    { key: "previous_pf_account_number", label: "Previous PF account number", kind: "text", maxLength: 30 },
    { key: "previous_esi_ip_number", label: "Previous ESI IP number", kind: "text", maxLength: 30 },
  ],
};

export const EDUCATION_SECTION: ListSectionConfig = {
  key: "education",
  title: "Education",
  path: "/education",
  viewPermission: "EMPLOYEE.VIEW_EXPERIENCE",
  note: "Education is visible only to holders of EMPLOYEE.VIEW_EXPERIENCE.",
  addLabel: "Add education",
  deleteConfirm: "Delete this education entry?",
  emptyTitle: "No education on record.",
  savedToast: "Education added",
  cardTitle: (row) => str(row, "qualification"),
  display: [
    { key: "institution_name", label: "Institution" },
    { key: "year_of_passing", label: "Year of passing" },
  ],
  form: [
    { key: "qualification", label: "Qualification", kind: "text", required: true, maxLength: 150 },
    { key: "institution_name", label: "Institution", kind: "text", maxLength: 200 },
    { key: "year_of_passing", label: "Year of passing", kind: "integer" },
  ],
};

export const DEPENDENTS_SECTION: ListSectionConfig = {
  key: "dependents",
  title: "Dependents",
  path: "/dependents",
  viewPermission: "EMPLOYEE.VIEW_NOMINEE",
  note: "Dependents and nominees are visible only to holders of EMPLOYEE.VIEW_NOMINEE.",
  addLabel: "Add dependent / nominee",
  deleteConfirm: "Delete this dependent?",
  emptyTitle: "No dependents or nominees on record.",
  savedToast: "Dependent added",
  cardTitle: (row) => `${str(row, "full_name")} (${str(row, "relationship")})`,
  display: [
    { key: "date_of_birth", label: "Date of birth" },
    { key: "gender", label: "Gender" },
    { key: "is_minor", label: "Minor", format: "yesNo" },
    { key: "guardian_name", label: "Guardian" },
    { key: "guardian_relationship", label: "Guardian relationship" },
    { key: "aadhaar_number_enc", label: "Aadhaar" },
    { key: "is_pf_nominee", label: "PF nominee", format: "yesNo" },
    { key: "pf_nominee_share_percentage", label: "PF share %" },
    { key: "is_gratuity_nominee", label: "Gratuity nominee", format: "yesNo" },
    { key: "gratuity_nominee_share_percentage", label: "Gratuity share %" },
    { key: "is_esi_dependent", label: "ESI dependent", format: "yesNo" },
  ],
  form: [
    { key: "full_name", label: "Full name", kind: "text", required: true, maxLength: 150 },
    { key: "relationship", label: "Relationship", kind: "text", required: true, maxLength: 50 },
    { key: "date_of_birth", label: "Date of birth", kind: "date" },
    { key: "gender", label: "Gender", kind: "select", options: GENDER_OPTIONS },
    { key: "is_minor", label: "Is a minor", kind: "toggle" },
    { key: "guardian_name", label: "Guardian name", kind: "text", showWhen: "is_minor", maxLength: 150 },
    { key: "guardian_relationship", label: "Guardian relationship", kind: "text", showWhen: "is_minor", maxLength: 50 },
    { key: "aadhaar_number_enc", label: "Aadhaar", kind: "aadhaar", hint: "12 digits" },
    { key: "is_pf_nominee", label: "PF nominee", kind: "toggle" },
    { key: "pf_nominee_share_percentage", label: "PF share %", kind: "decimal", showWhen: "is_pf_nominee" },
    { key: "is_gratuity_nominee", label: "Gratuity nominee", kind: "toggle" },
    { key: "gratuity_nominee_share_percentage", label: "Gratuity share %", kind: "decimal", showWhen: "is_gratuity_nominee" },
    { key: "is_esi_dependent", label: "ESI dependent", kind: "toggle" },
  ],
};

/** `GET/PATCH /employees/{id}/identity` — one record, edited in place with its version. */
export const IDENTITY_VIEW_PERMISSION = "EMPLOYEE.VIEW_SENSITIVE";
export const IDENTITY_DISPLAY: RecordDisplayField[] = [
  { key: "pan_number", label: "PAN" },
  { key: "aadhaar_number", label: "Aadhaar" },
  { key: "uan_number", label: "UAN" },
  { key: "father_or_husband_name", label: "Father / husband name" },
];
export const IDENTITY_FORM: RecordFormField[] = [
  { key: "pan_number", label: "PAN", kind: "pan", hint: "e.g. ABCDE1234F" },
  { key: "aadhaar_number", label: "Aadhaar", kind: "aadhaar", hint: "12 digits" },
  { key: "uan_number", label: "UAN", kind: "text", maxLength: 20 },
  { key: "father_or_husband_name", label: "Father's / husband's name", kind: "text", maxLength: 150 },
];

export type RecordFormValues = Record<string, string | boolean>;

export function emptyValues(fields: RecordFormField[]): RecordFormValues {
  return Object.fromEntries(fields.map((f) => [f.key, f.kind === "toggle" ? false : ""]));
}

/** Form values from a stored record (identity edit): money back to whole units, nulls to "". */
export function valuesFromRow(fields: RecordFormField[], row: RecordRow | null): RecordFormValues {
  const values = emptyValues(fields);
  if (!row) return values;
  for (const f of fields) {
    const raw = row[f.key];
    if (raw == null) continue;
    if (f.kind === "toggle") values[f.key] = raw === true;
    else if (f.kind === "money") values[f.key] = String(Number(raw) / 100);
    else values[f.key] = String(raw);
  }
  return values;
}

export function isShown(field: RecordFormField, values: RecordFormValues): boolean {
  return !field.showWhen || values[field.showWhen] === true;
}

const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const AADHAAR = /^[0-9]{12}$/;

/** Field errors, keyed by field. Hidden fields are not checked. */
export function validateRecord(fields: RecordFormField[], values: RecordFormValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of fields) {
    if (!isShown(f, values) || f.kind === "toggle") continue;
    const v = String(values[f.key] ?? "").trim();
    if (!v) {
      if (f.required) errors[f.key] = `${f.label} is required.`;
      continue;
    }
    if (f.maxLength && v.length > f.maxLength) errors[f.key] = `Use at most ${f.maxLength} characters.`;
    else if (f.kind === "pan" && !PAN.test(v.toUpperCase())) errors[f.key] = "Enter a valid PAN, e.g. ABCDE1234F.";
    else if (f.kind === "aadhaar" && !AADHAAR.test(v)) errors[f.key] = "Aadhaar must be 12 digits.";
    else if (f.kind === "money" && (Number.isNaN(Number(v)) || Number(v) < 0)) errors[f.key] = "Enter a valid amount.";
    else if (f.kind === "integer" && f.key === "year_of_passing" && (!/^[0-9]{4}$/.test(v) || Number(v) < 1950 || Number(v) > 2100))
      errors[f.key] = "Enter a year between 1950 and 2100.";
    else if (f.kind === "integer" && !/^-?[0-9]+$/.test(v)) errors[f.key] = "Enter a whole number.";
    else if (f.kind === "decimal" && (Number.isNaN(Number(v)) || Number(v) <= 0 || Number(v) > 100))
      errors[f.key] = "Enter a share above 0 and up to 100.";
  }
  return errors;
}

function wireValue(f: RecordFormField, values: RecordFormValues): unknown {
  if (f.kind === "toggle") return values[f.key] === true;
  const v = String(values[f.key] ?? "").trim();
  if (!v) return null;
  switch (f.kind) {
    case "money":
      return Math.round(Number(v) * 100);
    case "integer":
      return Number.parseInt(v, 10);
    case "decimal":
      return Number(v);
    case "pan":
      return v.toUpperCase();
    default:
      return v;
  }
}

/** Create body: every shown field, blanks omitted; hidden fields left out. */
export function buildCreatePayload(fields: RecordFormField[], values: RecordFormValues): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    if (!isShown(f, values)) continue;
    const value = wireValue(f, values);
    if (value !== null) body[f.key] = value;
  }
  return body;
}

/** Edit body: only fields whose wire value differs from the stored row (cleared fields send null). */
export function buildChangedPayload(
  fields: RecordFormField[],
  values: RecordFormValues,
  row: RecordRow | null,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    const value = wireValue(f, values);
    const before = row?.[f.key] ?? null;
    if (value !== before) body[f.key] = value;
  }
  return body;
}

/** A stored value as shown on a card. */
export function formatRecordValue(field: RecordDisplayField, raw: unknown): string {
  if (raw == null || String(raw).trim() === "") return "—";
  if (field.format === "yesNo") return raw === true ? "Yes" : "No";
  if (field.format === "money") {
    const minor = Number(raw);
    return Number.isNaN(minor) ? String(raw) : (minor / 100).toFixed(2);
  }
  return String(raw);
}

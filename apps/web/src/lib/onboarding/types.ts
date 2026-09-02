/** Mirrors `apps/api/src/hrms/modules/onboarding/schemas.py` — O1 (case create/list/detail)
 * only. Every interface/value tuple here corresponds 1:1 to a Pydantic schema or tuple in that
 * file — read it before changing this. */

// `docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` §6 — the full state machine. Not
// client-writable; O1 only ever produces `DRAFT` (no send-invite/token flow yet, that's O2/O3).
export const ONBOARDING_CASE_STATUS_VALUES = [
  "DRAFT",
  "INVITED",
  "IN_PROGRESS",
  "SUBMITTED",
  "UNDER_REVIEW",
  "CHANGES_REQUESTED",
  "VERIFIED",
  "ACTIVATED",
  "EXPIRED",
  "CANCELLED",
] as const;
export type OnboardingCaseStatus = (typeof ONBOARDING_CASE_STATUS_VALUES)[number];

export interface OnboardingCase {
  id: string;
  company_id: string;
  status: string;
  candidate_first_name: string;
  candidate_last_name: string | null;
  personal_email: string;
  personal_mobile: string | null;
  designation_id: string | null;
  department_id: string | null;
  branch_id: string | null;
  legal_entity_id: string | null;
  proposed_joining_date: string;
  created_by_user_id: string;
  employee_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** `POST /onboarding-cases/{id}/send-invite` response (O3). */
export interface OnboardingInvite {
  case: OnboardingCase;
  invite_url: string;
  email_sent: boolean;
}

/** Statuses `send-invite` may act on — mirrors `ONBOARDING_CASE_INVITABLE_STATUSES`
 * (`hrms.modules.onboarding.service`). Used only to decide whether to show
 * "Send invite" vs "Resend invite" as the button label. */
export const ONBOARDING_CASE_INVITABLE_STATUSES = ["DRAFT", "EXPIRED", "INVITED", "IN_PROGRESS"];

/** `GET /public/onboarding/{token}` response (O2/O4) — mirrors `PublicOnboardingCaseRead`.
 * Deliberately narrower than `OnboardingCase`: no internal IDs, the candidate has no session to
 * look anything else up with. */
export interface PublicOnboardingCase {
  status: string;
  candidate_first_name: string;
  candidate_last_name: string | null;
  proposed_joining_date: string;
  writable: boolean;
  personal_info: Record<string, unknown>;
  address_info: Record<string, unknown>;
  emergency_contact: Record<string, unknown>;
  bank_info: Record<string, unknown>;
  statutory_info: Record<string, unknown>;
}

// --- O5: documents ---------------------------------------------------------------------------

export const ONBOARDING_DOCUMENT_TYPES = [
  "PHOTO",
  "PAN",
  "AADHAAR",
  "ADDRESS_PROOF",
  "EDUCATION_CERTIFICATE",
  "PREVIOUS_EMPLOYMENT_PROOF",
  "BANK_PROOF",
  "OTHER",
] as const;
export type OnboardingDocumentType = (typeof ONBOARDING_DOCUMENT_TYPES)[number];

export const ONBOARDING_DOCUMENT_TYPE_LABELS: Record<OnboardingDocumentType, string> = {
  PHOTO: "Photo",
  PAN: "PAN card",
  AADHAAR: "Aadhaar card",
  ADDRESS_PROOF: "Address proof",
  EDUCATION_CERTIFICATE: "Education certificate",
  PREVIOUS_EMPLOYMENT_PROOF: "Previous employment proof",
  BANK_PROOF: "Bank proof",
  OTHER: "Other",
};

/** Mirrors `OnboardingDocumentRead` — used by both the candidate wizard (no download URL, they
 * already have the file) and as the base shape for the admin list. */
export interface OnboardingDocument {
  id: string;
  document_type: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  status: string;
  rejection_reason: string | null;
  uploaded_at: string;
}

/** `GET /onboarding-cases/{id}/documents` (admin, O5) — mirrors `OnboardingDocumentWithUrlRead`. */
export interface OnboardingDocumentWithUrl extends OnboardingDocument {
  download_url: string;
}

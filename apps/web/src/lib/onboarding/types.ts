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
  /** `null` only for a replayed duplicate request (the raw link is not retrievable again). */
  invite_url: string | null;
  /** DEPRECATED name: means "queued for delivery", NOT "delivered". Use `email_queued`. */
  email_sent: boolean;
  email_queued: boolean;
  email_delivery_status: "QUEUED" | "NOT_QUEUED";
  message_id: string | null;
  message_status: string | null;
  replayed: boolean;
  invitation_expires_at: string | null;
}

export interface InvitationPlaceholder {
  key: string;
  label: string;
  description: string;
  required: boolean;
  example: string;
}

/** `GET /onboarding-cases/{id}/invitation/compose`. */
export interface InvitationTemplate {
  key: string;
  name: string;
  description: string;
  subject: string;
  body: string;
}

export interface InvitationCompose {
  case_id: string;
  recipient_email: string;
  candidate_name: string;
  company_name: string;
  designation: string | null;
  department: string | null;
  proposed_joining_date: string;
  invitable: boolean;
  has_active_link: boolean;
  active_link_expires_at: string | null;
  link_valid_days: number;
  default_subject: string;
  default_body: string;
  /** Built-in starting points; the first is the default. May be absent on older servers. */
  templates?: InvitationTemplate[];
  subject_max_length: number;
  body_max_length: number;
  placeholders: InvitationPlaceholder[];
}

/** `POST /onboarding-cases/{id}/invitation/preview` — rendered server-side, inert link. */
export interface InvitationPreview {
  recipient_email: string;
  subject: string;
  html_body: string;
  text_body: string;
  /** Message with candidate details filled in; only `{{onboarding_url}}` stays a token. */
  editable_body?: string | null;
  link_is_placeholder: boolean;
}

export type OnboardingMessageStatus =
  | "NOT_QUEUED"
  | "QUEUED"
  | "RETRYING"
  | "SENDING"
  | "PROVIDER_ACCEPTED"
  | "FAILED"
  | "UNKNOWN";

/** `GET /onboarding-cases/{id}/messages`. */
export interface OnboardingMessage {
  id: string;
  message_type: string;
  recipient_email: string;
  subject: string;
  body_text: string;
  created_by_user_id: string;
  created_at: string;
  queued_at: string | null;
  status: OnboardingMessageStatus;
  attempts: number;
  last_attempt_at: string | null;
  provider_accepted_at: string | null;
  failed_at: string | null;
  failure_class: string | null;
}

/** Statuses `send-invite` may act on — mirrors `ONBOARDING_CASE_INVITABLE_STATUSES`
 * (`hrms.modules.onboarding.service`). Used to decide whether to show the invite button at all,
 * and which label it gets. `ACTIVATED` is included even though the case is otherwise terminal —
 * the resulting link resolves read-only (the backend's `ONBOARDING_CASE_WRITABLE_STATUSES`
 * excludes `ACTIVATED`), it just lets HR hand back a working link post-activation. */
export const ONBOARDING_CASE_INVITABLE_STATUSES = [
  "DRAFT",
  "EXPIRED",
  "INVITED",
  "IN_PROGRESS",
  "ACTIVATED",
];

/** Mirrors `OnboardingSectionReviewRead` (O6) — `section` is one of `ONBOARDING_SECTION_NAMES`. */
export interface OnboardingSectionReview {
  section: string;
  status: string;
  rejection_reason: string | null;
}

export const ONBOARDING_SECTION_NAMES = [
  "personal_info",
  "address_info",
  "emergency_contact",
  "bank_info",
  "statutory_info",
  "previous_employment_info",
  "education_info",
  "nominee_info",
] as const;
export type OnboardingSectionName = (typeof ONBOARDING_SECTION_NAMES)[number];

export const ONBOARDING_SECTION_LABELS: Record<OnboardingSectionName, string> = {
  personal_info: "Personal Info",
  address_info: "Address",
  emergency_contact: "Emergency Contact",
  bank_info: "Bank Details",
  statutory_info: "Statutory Details",
  previous_employment_info: "Previous Employment",
  education_info: "Education",
  nominee_info: "Nominees & Family Details",
};

/** `GET /public/onboarding/{token}` response (O2/O4/O6) — mirrors `PublicOnboardingCaseRead`.
 * Deliberately narrower than `OnboardingCase`: no internal IDs, the candidate has no session to
 * look anything else up with. `section_reviews` (O6) lets the wizard show which sections are
 * locked (verified) versus need fixing (rejected, with a reason). */
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
  compensation_info: Record<string, unknown>;
  previous_employment_info: Record<string, unknown>;
  education_info: Record<string, unknown>;
  nominee_info: Record<string, unknown>;
  section_reviews: OnboardingSectionReview[];
}

/** `GET /onboarding-cases/{id}` (admin, O6) — mirrors `OnboardingCaseDetailRead`: the case
 * fields plus the seven section JSON blobs and their review status. */
export interface OnboardingCaseDetail extends OnboardingCase {
  personal_info: Record<string, unknown>;
  address_info: Record<string, unknown>;
  emergency_contact: Record<string, unknown>;
  bank_info: Record<string, unknown>;
  statutory_info: Record<string, unknown>;
  compensation_info: Record<string, unknown>;
  previous_employment_info: Record<string, unknown>;
  education_info: Record<string, unknown>;
  nominee_info: Record<string, unknown>;
  section_reviews: OnboardingSectionReview[];
  token_status: "ACTIVE" | "EXPIRED" | "REVOKED" | null;
  token_expires_at: string | null;
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

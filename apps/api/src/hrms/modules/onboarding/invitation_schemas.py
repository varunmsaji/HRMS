"""Request/response schemas for the HR-editable invitation (compose / preview / history)."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InvitationPlaceholderRead(BaseModel):
    key: str
    label: str
    description: str
    required: bool
    example: str


class InvitationComposeRead(BaseModel):
    case_id: UUID
    recipient_email: str
    candidate_name: str
    company_name: str
    designation: str | None
    department: str | None
    proposed_joining_date: date
    #: False once the case is in a status a link can no longer be sent for.
    invitable: bool
    #: A live (unrevoked, unexpired) link exists: sending again REVOKES it.
    has_active_link: bool
    active_link_expires_at: datetime | None
    link_valid_days: int
    default_subject: str
    default_body: str
    subject_max_length: int
    body_max_length: int
    placeholders: list[InvitationPlaceholderRead]


class InvitationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(max_length=2000)
    body: str = Field(max_length=20000)


class InvitationPreviewRead(BaseModel):
    recipient_email: str
    subject: str
    html_body: str
    text_body: str
    #: The preview never contains a real credential: the link in it is inert.
    link_is_placeholder: bool = True


class OnboardingInviteSendRequest(BaseModel):
    """Optional body of `send-invite`. Absent (or fields omitted) = the built-in default invitation,
    which is what clients that predate the editor get."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=20000)
    #: Client-generated per compose session. A repeat of the same value is a duplicate request and
    #: returns the first result instead of issuing another link.
    send_request_id: UUID | None = None


class OnboardingMessageRead(BaseModel):
    id: UUID
    message_type: str
    recipient_email: str
    subject: str
    #: Plain text, with the secure link redacted.
    body_text: str
    created_by_user_id: UUID
    created_at: str
    queued_at: str | None
    #: NOT_QUEUED | QUEUED | RETRYING | SENDING | PROVIDER_ACCEPTED | FAILED | UNKNOWN.
    #: PROVIDER_ACCEPTED means the mail provider accepted the message - NOT that it reached the
    #: inbox (no delivery/bounce events are processed).
    status: str
    attempts: int
    last_attempt_at: str | None
    provider_accepted_at: str | None
    failed_at: str | None
    #: Coarse failure class only (never provider error text). Set for RETRYING/FAILED.
    failure_class: str | None

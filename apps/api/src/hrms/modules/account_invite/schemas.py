"""Pydantic request/response models for the account-invite module."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from hrms.core.auth.passwords import PASSWORD_MAX_LENGTH


class AccountInviteRead(BaseModel):
    """Returned by both issue endpoints — same "raw link is only ever available here" shape as
    `OnboardingInviteRead` (only the token's SHA-256 hash is persisted)."""

    id: UUID
    email: str
    role_code: str
    expires_at: datetime
    invite_url: str
    #: DEPRECATED name, kept for existing clients. Since B12 it means "the e-mail was queued", NOT
    #: "the provider accepted it" (identical to `email_queued`); it never reports a delivery
    #: failure.
    email_sent: bool
    #: True when the e-mail was stored in the transactional outbox with this request.
    email_queued: bool = True
    #: Delivery state at response time: `QUEUED`, or `NOT_QUEUED` if the outbox write failed.
    #: Later states (SENT / retrying / FAILED) live in `email_outbox` and are not part of this
    #: response.
    email_delivery_status: Literal["QUEUED", "NOT_QUEUED"] = "QUEUED"


class PublicAccountInviteRead(BaseModel):
    """Shown by the public `GET .../{token}` route before the accept form — enough for the
    invitee to recognize what they're accepting, nothing more (no role/permission detail).

    `existing_account` (SEC-08) tells the frontend whether `POST .../accept` will create a new
    account or authenticate an existing one — the invitee's own email is already known to them
    (it's the address the invite was sent to), so surfacing this is not an enumeration risk; it
    lets the accept form ask for a login password instead of a new one."""

    email: str
    company_name: str
    expires_at: datetime
    existing_account: bool


class AcceptInviteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class UserInviteRequest(BaseModel):
    """`POST /users/invite` — invites someone as a second admin/HR user, with no `Employee`
    record required. `email` is lowercased before use (`OrganisationService.register_company`'s
    own convention)."""

    email: EmailStr
    role_code: str


class UserSummary(BaseModel):
    """`GET /users` row — backs the minimal Settings > Users screen (doc 41 Phase 4)."""

    user_id: UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    is_primary: bool
    status: str
    role_codes: list[str]


class RoleAssignmentRequest(BaseModel):
    """`PATCH /users/{user_id}/roles` — full replace, not a diff (module docstring,
    `repository.replace_user_roles`)."""

    role_codes: list[str] = Field(default_factory=list)

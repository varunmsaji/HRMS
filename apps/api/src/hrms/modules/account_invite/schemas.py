"""Pydantic request/response models for the account-invite module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AccountInviteRead(BaseModel):
    """Returned by both issue endpoints — same "raw link is only ever available here" shape as
    `OnboardingInviteRead` (only the token's SHA-256 hash is persisted)."""

    id: UUID
    email: str
    role_code: str
    expires_at: datetime
    invite_url: str
    email_sent: bool


class PublicAccountInviteRead(BaseModel):
    """Shown by the public `GET .../{token}` route before the accept form — enough for the
    invitee to recognize what they're accepting, nothing more (no role/permission detail)."""

    email: str
    company_name: str
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    password: str = Field(min_length=1)
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

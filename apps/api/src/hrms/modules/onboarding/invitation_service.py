"""HR-editable invitation: compose metadata, side-effect-free preview, and the message history.

The send itself stays in `OnboardingTokenService.send_invite` (token lifecycle + outbox) and uses
the helpers here, so preview and send share `resolve_values` and `render_invitation`.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.errors.base import NotFoundError
from hrms.modules.onboarding.invitation_compose import (
    BODY_MAX_LENGTH,
    DEFAULT_BODY,
    DEFAULT_SUBJECT,
    PLACEHOLDERS,
    PREVIEW_LINK,
    REDACTED_LINK,
    SUBJECT_MAX_LENGTH,
    InvitationValues,
    RenderedInvitation,
    format_date,
    format_expiry,
    render_editable_body,
    render_invitation,
)
from hrms.modules.onboarding.invitation_rich_text import render_invitation_document
from hrms.modules.onboarding.invitation_schemas import (
    InvitationComposeRead,
    InvitationPlaceholderRead,
    InvitationPreviewRead,
    InvitationTemplateRead,
    OnboardingMessageRead,
)
from hrms.modules.onboarding.invitation_templates import INVITATION_TEMPLATES
from hrms.modules.onboarding.models import OnboardingMessage
from hrms.modules.onboarding.repository import OnboardingCaseRepository, OnboardingTokenRepository

if TYPE_CHECKING:
    from hrms.modules.onboarding.models import OnboardingCase


#: Public-link lifetime (kept equal to `service.DEFAULT_TOKEN_TTL_DAYS`, imported lazily to avoid a
#: module cycle - `service` imports this module's helpers inside `send_invite`).
def _ttl_days() -> int:
    from hrms.modules.onboarding.service import DEFAULT_TOKEN_TTL_DAYS

    return DEFAULT_TOKEN_TTL_DAYS


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def candidate_display_name(case: "OnboardingCase") -> str:
    return " ".join(p for p in (case.candidate_first_name, case.candidate_last_name) if p)


class OnboardingInvitationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._case_repo = OnboardingCaseRepository()
        self._token_repo = OnboardingTokenRepository()

    # ----------------------------------------------------------------- shared with send

    async def resolve_values(
        self, company_id: UUID, case: "OnboardingCase", *, expires_at: datetime
    ) -> tuple[InvitationValues, str]:
        """Server-side resolution from the tenant's own records only; nothing here comes from the
        client. Returns the values and the company name."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        company = await organisation.get_company_profile(company_id)
        designation: str | None = None
        department: str | None = None
        if case.designation_id is not None:
            try:
                designation = (
                    await organisation.get_designation(company_id, case.designation_id)
                ).title
            except NotFoundError:
                designation = None
        if case.department_id is not None:
            try:
                department = (
                    await organisation.get_department(company_id, case.department_id)
                ).name
            except NotFoundError:
                department = None
        values = InvitationValues(
            {
                "candidate_first_name": case.candidate_first_name,
                "candidate_last_name": case.candidate_last_name or None,
                "candidate_name": candidate_display_name(case),
                "company_name": company.name,
                "designation": designation,
                "department": department,
                "joining_date": format_date(case.proposed_joining_date),
                "invitation_expiry": format_expiry(expires_at),
            }
        )
        return values, company.name

    def render(
        self,
        *,
        subject: str | None,
        body: str | None,
        body_doc: dict[str, Any] | None = None,
        values: InvitationValues,
        onboarding_url: str,
        mobile_url: str | None,
    ) -> RenderedInvitation:
        """`body_doc` (structured rich text) and `body` (plain text) are mutually exclusive; the
        API schemas enforce that, and it is re-checked here so no caller can blur the two."""
        if body_doc is not None:
            if body is not None:
                raise ValueError("body and body_doc are mutually exclusive")
            return render_invitation_document(
                subject_template=DEFAULT_SUBJECT if subject is None else subject,
                body_doc=body_doc,
                values=values,
                onboarding_url=onboarding_url,
                mobile_url=mobile_url,
            )
        return render_invitation(
            subject_template=DEFAULT_SUBJECT if subject is None else subject,
            body_template=DEFAULT_BODY if body is None else body,
            values=values,
            onboarding_url=onboarding_url,
            mobile_url=mobile_url,
        )

    def redacted_text(
        self,
        *,
        subject: str | None,
        body: str | None,
        body_doc: dict[str, Any] | None = None,
        values: InvitationValues,
    ) -> str:
        """The retained copy: same text, credential link replaced, mobile link dropped."""
        return self.render(
            subject=subject,
            body=body,
            body_doc=body_doc,
            values=values,
            onboarding_url=REDACTED_LINK_URL,
            mobile_url=None,
        ).text_body.replace(REDACTED_LINK_URL, REDACTED_LINK)

    async def find_by_request_id(
        self, case_id: UUID, send_request_id: UUID
    ) -> OnboardingMessage | None:
        stmt = select(OnboardingMessage).where(
            OnboardingMessage.onboarding_case_id == case_id,
            OnboardingMessage.send_request_id == send_request_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def record_message(
        self,
        *,
        company_id: UUID,
        case: "OnboardingCase",
        subject: str,
        text_body: str,
        actor_user_id: UUID,
        outbox_message_key: str | None,
        send_request_id: UUID | None,
        now: datetime,
    ) -> OnboardingMessage:
        row = OnboardingMessage(
            id=uuid4(),
            company_id=company_id,
            onboarding_case_id=case.id,
            message_type="INVITATION",
            recipient_email=case.personal_email,
            subject=subject,
            rendered_text_body=text_body,
            created_by_user_id=actor_user_id,
            outbox_message_key=outbox_message_key,
            send_request_id=send_request_id,
            queued_at=now if outbox_message_key else None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    # ------------------------------------------------------------------------- endpoints

    async def _case(self, company_id: UUID, case_id: UUID) -> "OnboardingCase":
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        return case

    async def get_compose(self, company_id: UUID, case_id: UUID) -> InvitationComposeRead:
        from hrms.modules.onboarding.service import ONBOARDING_CASE_INVITABLE_STATUSES

        case = await self._case(company_id, case_id)
        now = datetime.now(UTC)
        latest = await self._token_repo.get_latest_for_case(self._session, case_id=case_id)
        live = latest is not None and latest.revoked_at is None and latest.expires_at > now
        values, company_name = await self.resolve_values(
            company_id, case, expires_at=now + timedelta(days=_ttl_days())
        )
        return InvitationComposeRead(
            case_id=case.id,
            recipient_email=case.personal_email,
            candidate_name=candidate_display_name(case),
            company_name=company_name,
            designation=values.values["designation"],
            department=values.values["department"],
            proposed_joining_date=case.proposed_joining_date,
            invitable=case.status in ONBOARDING_CASE_INVITABLE_STATUSES,
            has_active_link=live,
            active_link_expires_at=latest.expires_at if live and latest else None,
            link_valid_days=_ttl_days(),
            default_subject=DEFAULT_SUBJECT,
            default_body=DEFAULT_BODY,
            templates=[
                InvitationTemplateRead(
                    key=t.key,
                    name=t.name,
                    description=t.description,
                    subject=t.subject,
                    body=t.body,
                )
                for t in INVITATION_TEMPLATES
            ],
            subject_max_length=SUBJECT_MAX_LENGTH,
            body_max_length=BODY_MAX_LENGTH,
            placeholders=[
                InvitationPlaceholderRead(
                    key=p.key,
                    label=p.label,
                    description=p.description,
                    required=p.required,
                    example=p.example,
                )
                for p in PLACEHOLDERS
            ],
        )

    async def preview(
        self,
        company_id: UUID,
        case_id: UUID,
        *,
        subject: str,
        body: str | None = None,
        body_doc: dict[str, Any] | None = None,
    ) -> InvitationPreviewRead:
        """Reads only: no token is minted or revoked, no outbox row, no audit/history row."""
        case = await self._case(company_id, case_id)
        now = datetime.now(UTC)
        values, _ = await self.resolve_values(
            company_id, case, expires_at=now + timedelta(days=_ttl_days())
        )
        rendered = self.render(
            subject=subject,
            body=body,
            body_doc=body_doc,
            values=values,
            onboarding_url=f"{self._settings.web_app_base_url}/onboarding/{PREVIEW_LINK}",
            mobile_url=None,
        )
        return InvitationPreviewRead(
            recipient_email=case.personal_email,
            subject=rendered.subject,
            html_body=rendered.html_body,
            text_body=rendered.text_body,
            editable_body=(
                render_editable_body(DEFAULT_BODY if body is None else body, values)
                if body_doc is None
                else None
            ),
        )

    async def list_messages(self, company_id: UUID, case_id: UUID) -> list[OnboardingMessageRead]:
        await self._case(company_id, case_id)  # 404 for another tenant's case
        rows = (
            (
                await self._session.execute(
                    select(OnboardingMessage)
                    .where(
                        OnboardingMessage.company_id == company_id,
                        OnboardingMessage.onboarding_case_id == case_id,
                    )
                    .order_by(OnboardingMessage.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        keys = [r.outbox_message_key for r in rows if r.outbox_message_key]
        outbox: dict[str, dict[str, object]] = {}
        if keys:
            result = await self._session.execute(
                text(
                    "SELECT message_id, status, attempts, last_attempt_at, sent_at, failed_at, "
                    "last_failure_class FROM email_outbox "
                    "WHERE company_id = :cid AND message_id = ANY(:keys)"
                ),
                {"cid": company_id, "keys": keys},
            )
            outbox = {r.message_id: dict(r._mapping) for r in result}
        return [self._to_read(r, outbox.get(r.outbox_message_key or "")) for r in rows]

    @staticmethod
    def _to_read(row: OnboardingMessage, ob: dict[str, object] | None) -> OnboardingMessageRead:
        if row.outbox_message_key is None:
            status = "NOT_QUEUED"
        elif ob is None:
            status = "UNKNOWN"
        else:
            raw = str(ob["status"])
            attempts = int(ob["attempts"])  # type: ignore[call-overload]
            status = {
                "PENDING": "RETRYING" if attempts > 0 else "QUEUED",
                "SENDING": "SENDING",
                "SENT": "PROVIDER_ACCEPTED",
                "FAILED": "FAILED",
            }.get(raw, "UNKNOWN")
        return OnboardingMessageRead(
            id=row.id,
            message_type=row.message_type,
            recipient_email=row.recipient_email,
            subject=row.subject,
            body_text=row.rendered_text_body,
            created_by_user_id=row.created_by_user_id,
            created_at=_iso(row.created_at) or "",
            queued_at=_iso(row.queued_at),
            status=status,
            attempts=int(ob["attempts"]) if ob else 0,  # type: ignore[call-overload]
            last_attempt_at=_iso(ob["last_attempt_at"]) if ob else None,  # type: ignore[arg-type]
            provider_accepted_at=_iso(ob["sent_at"]) if ob else None,  # type: ignore[arg-type]
            failed_at=_iso(ob["failed_at"]) if ob else None,  # type: ignore[arg-type]
            failure_class=(
                str(ob["last_failure_class"])
                if ob and ob["last_failure_class"] and status in ("RETRYING", "FAILED")
                else None
            ),
        )


#: Sentinel substituted for the credential link while building the retained copy.
REDACTED_LINK_URL = "https://redacted.invalid/onboarding-link"

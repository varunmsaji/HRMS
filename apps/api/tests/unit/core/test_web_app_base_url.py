"""FINDING-001 — production email links must not be the development localhost origin.

The builders in identity, account invite, onboarding, and attendance reminders all embed
`Settings.web_app_base_url`. These tests prove:

- development still boots and still emits `http://localhost:3000`
- staging/production refuse the default, other loopback hosts, and cleartext
- an explicit https origin is the prefix of every affected link
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings
from hrms.modules.account_invite.service import AccountInviteService
from hrms.modules.attendance.reminders import IncompleteDayReminderService
from hrms.modules.identity.service import IdentityService
from hrms.modules.onboarding.service import OnboardingTokenService

_STRONG_ACCESS_SECRET = "Zx7!qP9$mK2#vL5^rT8&nB1@wD4%yF6*hJ0"
_STRONG_REFRESH_SECRET = "Qm3&zR8!kX1#pL6^bN9$vT2@yH5%wD0*jF4"
_TEST_PII_MASTER_KEY = "Nb4$hK7!wQ2#xM9^rF3&tY6@pL1%vD8*sG5"
_PRODUCTION_ORIGIN = "https://hr.example.com"


def _production_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "jwt_access_secret": _STRONG_ACCESS_SECRET,
        "jwt_refresh_secret": _STRONG_REFRESH_SECRET,
        "cors_allowed_origins": ("https://hr.example.com",),
        "pii_master_key": _TEST_PII_MASTER_KEY,
        "s3_endpoint_url": "http://minio:9000",
        "s3_bucket_documents": "hrms-test-documents",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "email_provider": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "hrms-app",
        "smtp_password": "test-smtp-password",
        "smtp_from_email": "onboarding@hr.example.com",
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
        "web_app_base_url": _PRODUCTION_ORIGIN,
    }
    base.update(overrides)
    return Settings(**base)


def _assert_rejected(url: str) -> None:
    marker = "secret-marker-must-not-leak"
    try:
        _production_settings(web_app_base_url=f"{url}{marker}" if "://" not in url else url)
        raised = False
        message = ""
    except ValidationError as exc:
        raised = True
        message = str(exc)
    assert raised
    assert "web_app_base_url" in message
    assert marker not in message


# --- Boot guard --------------------------------------------------------------------------


def test_development_keeps_the_localhost_default() -> None:
    settings = Settings(
        environment="development",
        web_app_base_url="http://localhost:3000",
    )
    assert settings.web_app_base_url == "http://localhost:3000"
    assert settings.is_development


def test_development_accepts_an_explicit_localhost_origin_with_a_trailing_slash() -> None:
    settings = Settings(environment="development", web_app_base_url="http://localhost:3000/")
    assert settings.web_app_base_url == "http://localhost:3000"


def test_production_rejects_the_localhost_default() -> None:
    with pytest.raises(ValidationError, match="web_app_base_url"):
        _production_settings(web_app_base_url="http://localhost:3000")


def test_staging_rejects_the_localhost_default() -> None:
    with pytest.raises(ValidationError, match="web_app_base_url"):
        _production_settings(environment="staging", web_app_base_url="http://localhost:3000")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "http://localhost:3000",
        "https://localhost",
        "https://localhost:3000",
        "http://127.0.0.1:3000",
        "https://127.0.0.1",
        "https://0.0.0.0",
        "https://[::1]",
        "https://app.localhost",
        "http://hr.example.com",
        "hr.example.com",
        "/reset-password",
        "https://user:secret-marker-must-not-leak@hr.example.com",
        "https://hr.example.com/app?next=/home",
        "https://hr.example.com/app#section",
    ],
)
def test_production_rejects_unsafe_web_origins(url: str) -> None:
    with pytest.raises(ValidationError, match="web_app_base_url"):
        _production_settings(web_app_base_url=url)


def test_production_rejection_does_not_echo_a_credential_in_the_url() -> None:
    _assert_rejected("https://user:secret-marker-must-not-leak@hr.example.com")


def test_production_accepts_an_explicit_https_origin_and_strips_a_trailing_slash() -> None:
    settings = _production_settings(web_app_base_url="https://hr.example.com/")
    assert settings.web_app_base_url == "https://hr.example.com"


def test_production_accepts_an_https_origin_with_a_path_prefix() -> None:
    settings = _production_settings(web_app_base_url="https://hr.example.com/hr/")
    assert settings.web_app_base_url == "https://hr.example.com/hr"


# --- Link flows --------------------------------------------------------------------------


class _Sent:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def send(self, **kwargs: object) -> None:
        text = kwargs.get("text_body")
        html = kwargs.get("html_body")
        self.bodies.append(str(text))
        self.bodies.append(str(html))


def _assert_link(bodies: list[str], prefix: str) -> None:
    joined = "\n".join(bodies)
    assert prefix in joined
    assert "localhost" not in joined
    assert "127.0.0.1" not in joined
    assert "//reset-password" not in joined
    assert "//verify-email" not in joined
    assert "//accept-invite" not in joined
    assert "//onboarding" not in joined


async def test_development_password_reset_link_uses_localhost() -> None:
    settings = Settings(environment="development", web_app_base_url="http://localhost:3000")
    service = IdentityService(AsyncMock(), settings)
    user = SimpleNamespace(
        id=uuid4(),
        email="ada@example.com",
        first_name="Ada",
        deleted_at=None,
        status="ACTIVE",
    )
    service._repo.get_user_by_email = AsyncMock(return_value=user)
    service._repo.create_password_reset_token = AsyncMock()
    sent = _Sent()
    with patch("hrms.modules.identity.service.get_email_sender", return_value=sent):
        await service.forgot_password("ada@example.com")
    assert "http://localhost:3000/reset-password/" in "\n".join(sent.bodies)


async def test_production_verification_and_reset_links_use_the_configured_origin() -> None:
    settings = _production_settings()
    service = IdentityService(AsyncMock(), settings)
    user = SimpleNamespace(
        id=uuid4(),
        email="ada@example.com",
        first_name="Ada",
        deleted_at=None,
        status="ACTIVE",
        email_verified_at=None,
    )
    service._repo.get_user_by_email = AsyncMock(return_value=user)
    service._repo.create_password_reset_token = AsyncMock()
    service._repo.create_email_verification_token = AsyncMock()
    sent = _Sent()
    with patch("hrms.modules.identity.service.get_email_sender", return_value=sent):
        await service.forgot_password("ada@example.com")
        await service.resend_verification_email("ada@example.com")
    _assert_link(sent.bodies, f"{_PRODUCTION_ORIGIN}/reset-password/")
    _assert_link(sent.bodies, f"{_PRODUCTION_ORIGIN}/verify-email/")


async def test_production_account_invite_link_uses_the_configured_origin() -> None:
    settings = _production_settings()
    service = AccountInviteService(AsyncMock(), settings)
    service._repo.get_role_by_code = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    service._repo.revoke_live_invites_for_email = AsyncMock()
    service._repo.insert_invite = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    service._audit.record = AsyncMock()
    sent = _Sent()
    company = SimpleNamespace(name="Acme")
    with (
        patch("hrms.modules.account_invite.service.get_email_sender", return_value=sent),
        patch("hrms.modules.organisation.service.OrganisationService") as organisation,
    ):
        organisation.return_value.get_company_profile = AsyncMock(return_value=company)
        read = await service.issue_for_user(
            uuid4(),
            SimpleNamespace(email="ada@example.com", role_code="EMPLOYEE"),
            actor_user_id=uuid4(),
        )
    assert read.invite_url.startswith(f"{_PRODUCTION_ORIGIN}/accept-invite/")
    _assert_link(sent.bodies, read.invite_url)


async def test_production_onboarding_invite_link_uses_the_configured_origin() -> None:
    settings = _production_settings()
    service = OnboardingTokenService(AsyncMock(), settings)
    now = datetime.now(UTC)
    company_id = uuid4()
    case = SimpleNamespace(
        id=uuid4(),
        company_id=company_id,
        status="DRAFT",
        candidate_first_name="Ada",
        candidate_last_name="Lovelace",
        personal_email="ada@example.com",
        personal_mobile=None,
        designation_id=None,
        department_id=None,
        branch_id=None,
        legal_entity_id=None,
        proposed_joining_date=date(2026, 5, 1),
        created_by_user_id=uuid4(),
        employee_id=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    service._case_repo.get_case = AsyncMock(return_value=case)
    service._case_repo.get_case_for_update = AsyncMock(return_value=case)
    service.issue_token_with_expiry = AsyncMock(
        return_value=("raw-onboarding-token", now + timedelta(days=7))
    )
    service._audit.record = AsyncMock()
    sent = _Sent()
    company = SimpleNamespace(name="Acme")
    with (
        patch("hrms.modules.onboarding.service.get_email_sender", return_value=sent),
        patch("hrms.modules.organisation.service.OrganisationService") as organisation,
    ):
        organisation.return_value.get_company_profile = AsyncMock(return_value=company)
        read = await service.send_invite(company_id, case.id, actor_user_id=uuid4())
    assert read.invite_url == f"{_PRODUCTION_ORIGIN}/onboarding/raw-onboarding-token"
    _assert_link(sent.bodies, read.invite_url)


async def test_production_attendance_reminder_links_use_the_configured_origin() -> None:
    settings = _production_settings()
    sent = _Sent()
    session = AsyncMock()
    employee_id = uuid4()
    period_id = uuid4()
    period = SimpleNamespace(
        id=period_id,
        label="April 2026",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        legal_entity_id=uuid4(),
    )

    class _Result:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def all(self) -> list[object]:
            return self._rows

        def scalars(self) -> list[object]:
            return self._rows

    session.execute = AsyncMock(
        side_effect=[
            _Result([(employee_id, date(2026, 4, 2), "Ada", "ada@example.com", "ACTIVE")]),
            _Result(["hr@example.com"]),
        ]
    )
    service = IncompleteDayReminderService(session, settings, sent)  # type: ignore[arg-type]
    service._already_sent = AsyncMock(return_value=False)  # type: ignore[method-assign]
    with (
        patch("hrms.modules.attendance.reminders.RbacRepository") as rbac,
        patch("hrms.modules.attendance.reminders.AuditService") as audit,
    ):
        rbac.return_value.list_user_ids_with_permission = AsyncMock(return_value=[uuid4()])
        audit.return_value.record = AsyncMock()
        await service._send_for_period(uuid4(), period, today=date(2026, 4, 10))  # type: ignore[arg-type]
    _assert_link(sent.bodies, f"{_PRODUCTION_ORIGIN}/app/regularizations")
    _assert_link(sent.bodies, f"{_PRODUCTION_ORIGIN}/app/attendance-periods/{period_id}")

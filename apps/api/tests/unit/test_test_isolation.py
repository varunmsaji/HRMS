"""Test-isolation gate: the suite must never reach a real email provider, the real Face++ API,
or the developer's Celery broker DB (which may hold a real backlog). `tests/conftest.py` forces
these values; this file proves they are what the code actually resolves, so a later edit to
conftest or settings that silently re-enables a real side effect fails loudly."""

from urllib.parse import urlsplit

from hrms.core.celery_app import celery_app
from hrms.core.config.settings import get_settings
from hrms.modules.attendance.face_verification import get_face_verification_provider
from hrms.modules.onboarding.email_sender import LoggingEmailSender, get_email_sender


def _db_index(url: str) -> str:
    return urlsplit(url).path.lstrip("/") or "0"


def test_effective_email_provider_is_the_logging_sender() -> None:
    settings = get_settings()
    assert settings.email_provider == "logging"
    assert isinstance(get_email_sender(settings), LoggingEmailSender)


def test_face_provider_is_disabled() -> None:
    settings = get_settings()
    assert settings.face_verification_provider == "disabled"
    assert get_face_verification_provider(settings) is None


def test_celery_broker_and_backend_use_an_isolated_redis_db() -> None:
    settings = get_settings()
    assert _db_index(settings.celery_broker) != _db_index(settings.redis_url)
    assert _db_index(settings.celery_backend) != _db_index(settings.redis_url)
    # The module-level Celery app is built at import time — it must have picked up the
    # isolated broker too, not just a freshly constructed Settings.
    assert _db_index(str(celery_app.conf.broker_url)) == _db_index(settings.celery_broker)
    assert _db_index(str(celery_app.conf.broker_url)) != "0"

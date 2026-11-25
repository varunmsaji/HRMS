"""A per-employee "blocked" result in a successful bulk response carries the same text a
single-request error would: a written message for a business refusal, a fixed one for a server
failure - never the instance text of a 5xx."""

from uuid import uuid4

from hrms.core.errors.base import ConflictError
from hrms.modules.attendance.exceptions import FaceProviderFailedError
from hrms.modules.attendance.service import _blocked


def test_a_business_refusal_keeps_its_written_message() -> None:
    result = _blocked(uuid4(), ConflictError("This day is locked.", code="DAY_LOCKED"), [])
    assert (result.outcome, result.code, result.message) == (
        "BLOCKED",
        "DAY_LOCKED",
        "This day is locked.",
    )


def test_a_server_failure_never_carries_its_instance_text() -> None:
    result = _blocked(uuid4(), FaceProviderFailedError("token=eyJabc at /srv/app/provider.py"), [])
    assert result.message == FaceProviderFailedError.public_message
    assert "eyJ" not in result.message and "/srv" not in result.message

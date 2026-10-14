"""LOG-08 / plan §H — the shared redaction processor and `safe_error`.

Table-driven unit checks of `redact_event`, plus end-to-end checks through the *real* JSON
pipeline `configure_logging` builds (structlog and, for worker/Beat, the stdlib tree), reading the
actual stdout bytes so the assertions hold for what an operator would see."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from pytest import CaptureFixture
from sqlalchemy.exc import DBAPIError

from hrms.core.errors.base import ConflictError
from hrms.core.observability.logging import configure_logging, get_logger, safe_error
from hrms.core.observability.redaction import (
    MAX_EXCEPTION_CHARS,
    MAX_FIELD_CHARS,
    REDACTED,
    redact_event,
)

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJlLXNlbnRpbmVs"


def _redact(**fields: Any) -> dict[str, Any]:
    return redact_event(None, "info", {"event": "probe", **fields})


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "refresh_token",
        "access_token",
        "token",
        "Authorization",
        "cookie",
        "set_cookie",
        "api_key",
        "apikey",
        "smtp_password",
        "client_secret",
        "otp",
        "aadhaar",
        "pan_number",
        "account_number",
        "ifsc",
        "salary",
        "text_body",
        "request_body",
        "face_template",
        "credentials",
    ],
)
def test_sensitive_keys_are_masked_whatever_their_value(key: str) -> None:
    assert _redact(**{key: "s3ntinel"})[key] == REDACTED


@pytest.mark.parametrize(
    "key",
    ["family_id", "token_kind", "key_version", "salary_structure_id", "request_id", "user_id"],
)
def test_identifiers_about_sensitive_things_are_kept(key: str) -> None:
    assert _redact(**{key: "abc-123"})[key] == "abc-123"


def test_nested_structures_are_masked_by_key_and_pattern() -> None:
    out = _redact(context={"password": "p", "items": [{"refresh_token": "t"}, f"Bearer {JWT}"]})
    assert out["context"]["password"] == REDACTED
    assert out["context"]["items"][0]["refresh_token"] == REDACTED
    assert JWT not in json.dumps(out)


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        (f"token was {JWT} ok", JWT),
        ("Authorization: Bearer abcdefghijklmnop123", "abcdefghijklmnop123"),
        (
            "GET /doc.pdf?X-Amz-Credential=AKIAEXAMPLE%2F2026&X-Amz-Signature=deadbeefcafe",
            "deadbeefcafe",
        ),
        (
            "GET /doc.pdf?X-Amz-Credential=AKIAEXAMPLE%2F2026&X-Amz-Signature=deadbeefcafe",
            "AKIAEXAMPLE",
        ),
        ("connect postgresql://hrms:hunter2-pw@db:5432/hrms failed", "hunter2-pw"),
        ('duplicate key value violates "uq" DETAIL: Key (email)=(a.b@x.io) exists', "a.b@x.io"),
        ("sent to priya.sharma@example.com", "priya.sharma@example.com"),
        ("PAN ABCDE1234F on file", "ABCDE1234F"),
        ("GET /v1/public/onboarding/tok-SENTINEL-1/documents", "tok-SENTINEL-1"),
        ("link https://app/reset-password/rst-SENTINEL-2", "rst-SENTINEL-2"),
    ],
)
def test_value_patterns_mask_only_the_secret(raw: str, secret: str) -> None:
    out = _redact(detail=raw)["detail"]
    assert secret not in out
    assert out != ""


def test_route_template_placeholder_is_not_masked() -> None:
    path = "/v1/public/account-invites/{token}/accept"
    assert _redact(http_path=path)["http_path"] == path


def test_event_text_of_foreign_records_is_redacted_but_our_event_names_are_not() -> None:
    assert _redact()["event"] == "probe"
    out = redact_event(None, "info", {"event": f"HTTP Request: POST https://x/?t {JWT}"})
    assert JWT not in out["event"]


def test_long_values_are_truncated_and_tracebacks_get_more_room() -> None:
    out = _redact(detail="x" * (MAX_FIELD_CHARS + 500), exception="y" * (MAX_EXCEPTION_CHARS + 5))
    assert len(out["detail"]) < MAX_FIELD_CHARS + 50
    assert "truncated 500 chars" in out["detail"]
    assert out["exception"].startswith("y" * MAX_EXCEPTION_CHARS)
    assert "truncated 5 chars" in out["exception"]


def test_bytes_are_never_rendered() -> None:
    assert _redact(payload=b"\x89PNG\r\n raw-image-bytes")["payload"] == "[BYTES 22]"


def test_arbitrary_objects_are_rendered_then_redacted() -> None:
    class Leaky:
        def __str__(self) -> str:
            return "Employee(email=leak@example.com)"

    assert "leak@example.com" not in str(_redact(obj=Leaky())["obj"])


def test_a_failure_inside_redaction_drops_fields_instead_of_emitting_them_raw() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    out = redact_event(None, "info", {"event": "x", "level": "info", "obj": Hostile()})
    assert out == {"level": "info", "event": "log_redaction_failed", "redaction_failed": True}


# ---- safe_error ---------------------------------------------------------------------------


class _UniqueViolationError(Exception):
    sqlstate = "23505"


def test_safe_error_classifies_without_the_message() -> None:
    assert safe_error(RuntimeError("secret-text")) == {
        "exception_type": "RuntimeError",
        "error_category": "unexpected",
    }

    app_err = ConflictError("conflict on secret-text")
    assert safe_error(app_err) == {
        "exception_type": "ConflictError",
        "error_category": "unexpected",
        "error_code": "CONFLICT",
    }

    orig = Exception("adapter")
    orig.__cause__ = _UniqueViolationError("Key (email)=(x@y.z) already exists")
    db_err = DBAPIError("INSERT ...", {"email": "x@y.z"}, orig)
    fields = safe_error(db_err)
    assert fields["exception_type"] == "DBAPIError"
    assert fields["driver_error"] == "_UniqueViolationError"
    assert fields["sqlstate"] == "23505"
    assert fields["error_category"] == "db_integrity"
    assert "x@y.z" not in json.dumps(fields)

    def _chained() -> None:
        try:
            {}["inner"]
        except KeyError as inner:
            raise ValueError("outer") from inner

    with pytest.raises(ValueError) as chained:
        _chained()
    assert safe_error(chained.value)["cause_type"] == "KeyError"


# ---- end to end through the real pipeline -------------------------------------------------


def _json_lines(raw: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


@pytest.fixture
def api_logging() -> Iterator[None]:
    configure_logging("api")
    yield
    configure_logging("api")


def test_secrets_never_reach_stdout_through_structlog(
    api_logging: None, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    log = get_logger("probe.redaction")
    log.warning(
        "probe_event",
        password="pw-SENTINEL",
        detail=f"Authorization: Bearer {JWT}",
        recipient="someone@example.com",
    )

    def _fail() -> None:
        raise ValueError(f"failed for someone@example.com with {JWT}")

    try:
        _fail()
    except ValueError:
        log.exception("probe_exception")
    raw = capfd.readouterr().out
    for secret in ("pw-SENTINEL", JWT, "someone@example.com"):
        assert secret not in raw
    events = {e["event"]: e for e in _json_lines(raw)}
    assert events["probe_event"]["password"] == REDACTED
    assert "Traceback" in events["probe_exception"]["exception"]


def test_control_characters_cannot_forge_log_lines(
    api_logging: None, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    forged = 'x\n{"event": "forged", "level": "critical"}\r\x1b[31m '
    get_logger("probe.injection").info("probe_injection", value=forged)
    lines = [line for line in capfd.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event"] == "probe_injection"
    assert parsed["value"] == forged  # preserved, but only as an escaped JSON string


def test_stdlib_records_are_redacted_on_the_worker_pipeline(
    capfd: CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging("worker", configure_stdlib=True)
        capfd.readouterr()
        logging.getLogger("httpx").warning(
            "HTTP Request: POST https://mail/send?Signature=abc123sig %s", JWT
        )
        raw = capfd.readouterr().out
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
        configure_logging("api")
    assert JWT not in raw
    assert "abc123sig" not in raw
    (entry,) = [e for e in _json_lines(raw) if e.get("logger") == "httpx"]
    assert entry["service"] == "worker"

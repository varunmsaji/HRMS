"""LOG-07 — operational security events (`security.*`), one schema for every auth-related site.

These are *operational log* events for detection and incident response (credential stuffing,
lockout storms, token theft, probing across tenants). They are deliberately separate from the
business audit trail (`core/audit`, Postgres `audit_log`), which keeps its own records, redaction
and retention; nothing here writes to or replaces it.

Rules every caller follows:

* never a credential, token, password or raw email address — an account is identified by its
  `user_id` when known, otherwise by `subject_hash`, a keyed pseudonym of the submitted login
  identifier that lets an operator see "many attempts against the same unknown address" without
  storing the address (it is pseudonymous, not anonymous: anyone holding the server secret and a
  candidate address can recompute it);
* `reason` is a short fixed vocabulary chosen by the caller, never exception text or user input;
* the event is emitted through `safe_log`, so a broken log sink can never change the response or
  undo a security decision that has already been made (lockout counters, revocations);
* nothing derived from these events is ever returned to the client, so they cannot act as an
  account-existence oracle.
"""

import hashlib
import hmac
from typing import Any, Literal

from hrms.core.config.settings import get_settings
from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.observability.metrics import SECURITY_EVENTS, safe_count

_logger = get_logger("hrms.security")

Level = Literal["info", "warning", "error"]


def subject_hash(identifier: str | None) -> str | None:
    """Keyed, truncated HMAC of a normalised login identifier (email). Stable across processes
    sharing the same `JWT_ACCESS_SECRET`; the secret is domain-separated so the derived key is
    never usable as a JWT key."""
    if not identifier:
        return None
    normalised = identifier.strip().lower().encode("utf-8")
    key = hashlib.sha256(b"hrms-log-subject|" + get_settings().jwt_access_secret.encode()).digest()
    return hmac.new(key, normalised, hashlib.sha256).hexdigest()[:16]


def security_event(event: str, *, level: Level = "info", **fields: Any) -> None:
    """Emits `security.<event>` at `level`. `fields` must be identifiers, fixed reason codes,
    counts or the client IP — see the module docstring."""
    # `event` is always a literal at the call sites (closed set); the level is one of three.
    safe_count(SECURITY_EVENTS, event, level)
    method = {"info": _logger.info, "warning": _logger.warning, "error": _logger.error}[level]
    safe_log(method, f"security.{event}", **fields)

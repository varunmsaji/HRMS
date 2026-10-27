"""Refuses to start the suite against the shared development stack.

Why this exists (QA Phase 2/3 findings ENV-ISOL-001, ENV-ISOL-002):

* `tests/conftest.py` defaults `DATABASE_URL` to the persistent `hrms_dev` database, and the
  integration suite's teardown helpers issue real DELETEs.
* The root autouse fixture `_reset_credential_rate_limits` SCAN-deletes `ratelimit:*` keys on
  `REDIS_URL` before and after EVERY test (unit tests included); the default is the shared dev
  Redis, index 0.

The check only fires for the shared-dev signature - a database named `hrms_dev` on any host, or the
shared dev Redis (`localhost:6380`) at index 0. It never fires when:

* `CI` is truthy (GitHub Actions service containers deliberately reuse those names), or
* `HRMS_TEST_ALLOW_SHARED_DEV=1` is exported (explicit, per-invocation acknowledgement), or
* the targets differ (e.g. `run_full_tests.py` uses `hrms_test` and Redis index 1, a QA stack
  uses its own ports).

It adds a refusal; it never changes what a passing run does.
"""

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

_LOCAL = {"localhost", "127.0.0.1", "::1", ""}
_SHARED_DEV_DB = "hrms_dev"
_SHARED_DEV_REDIS_PORT = 6380

OVERRIDE = "HRMS_TEST_ALLOW_SHARED_DEV"
STRICT = "HRMS_QA_STRICT"

_DB_VARS = ("DATABASE_URL", "MIGRATIONS_DATABASE_URL", "HRMS_APP_DATABASE_URL")
_REDIS_VARS = ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND")
#: Ports that identify the shared dev stack OR a well-known system service on the same machine
#: (system Postgres 5432 / Redis 6379 / MySQL 3306 belong to other projects). A disposable QA
#: stack must use none of them.
_FORBIDDEN_PORTS = {5432, 5433, 6379, 6380, 9000, 9001, 8000, 3306}
_STRICT_DB_PREFIX = "hrms_qa_"
_PROVIDER_SECRETS = (
    "MAILTRAP_API_TOKEN",
    "HOSTINGER_MAIL_API_TOKEN",
    "FACEPP_API_KEY",
    "FACEPP_API_SECRET",
    "SMTP_PASSWORD",
)


def shared_dev_targets(env: Mapping[str, str]) -> list[str]:
    """Returns human-readable reasons the effective targets look like the shared dev stack."""
    reasons: list[str] = []
    for name in _DB_VARS:
        if urlsplit(env.get(name, "")).path.lstrip("/") == _SHARED_DEV_DB:
            reasons.append(f"{name} targets the persistent dev database '{_SHARED_DEV_DB}'")
    for name in _REDIS_VARS:
        redis = urlsplit(env.get(name, ""))
        index = redis.path.lstrip("/") or "0"
        if (
            (redis.hostname or "") in _LOCAL
            and (redis.port or 6379) == _SHARED_DEV_REDIS_PORT
            and index == "0"
        ):
            reasons.append(
                f"{name} targets the shared dev Redis (port {_SHARED_DEV_REDIS_PORT}, index 0): "
                "the root conftest deletes ratelimit:* keys there around every test"
            )
    return reasons


def is_acknowledged(env: Mapping[str, str]) -> bool:
    if env.get(OVERRIDE) == "1":
        return True
    return env.get("CI", "").lower() in {"1", "true", "yes"}


def strict_problems(env: Mapping[str, str], cwd: str = ".") -> list[str]:
    """Affirmative disposability proof for the QA sandbox (`HRMS_QA_STRICT=1`).

    Unlike `shared_dev_targets` (a deny-list), this is an allow-list: every database must be named
    `hrms_qa_*`, every service must be on loopback at a non-standard port, `.env` must be absent
    or empty, providers must be the inert ones and carry no secrets. A missing variable is a
    problem (no silent fallback to the `Settings` defaults, which point at the shared stack).
    CI and the override variable are deliberately ignored in this mode."""
    out: list[str] = []
    for name in ("DATABASE_URL", "MIGRATIONS_DATABASE_URL", "REDIS_URL", "S3_ENDPOINT_URL"):
        if not env.get(name):
            out.append(f"{name} is not set (the default would point at the shared stack or AWS)")
    for name in _DB_VARS:
        if name not in env:
            continue
        u = urlsplit(env[name])
        if not u.path.lstrip("/").startswith(_STRICT_DB_PREFIX):
            out.append(
                f"{name}: database '{u.path.lstrip('/')}' does not start with {_STRICT_DB_PREFIX}"
            )
        if (u.hostname or "") != "127.0.0.1" or (u.port or 5432) in _FORBIDDEN_PORTS:
            out.append(f"{name}: host/port {u.hostname}:{u.port} is not a private loopback port")
    for name in (*_REDIS_VARS, "S3_ENDPOINT_URL"):
        if name not in env:
            continue
        u = urlsplit(env[name])
        default = 9000 if name == "S3_ENDPOINT_URL" else 6379
        if (u.hostname or "") != "127.0.0.1" or (u.port or default) in _FORBIDDEN_PORTS:
            out.append(f"{name}: host/port {u.hostname}:{u.port} is not a private loopback port")
    if env.get("EMAIL_PROVIDER", "logging") != "logging":
        out.append("EMAIL_PROVIDER must be 'logging'")
    if env.get("FACE_VERIFICATION_PROVIDER", "disabled") != "disabled":
        out.append("FACE_VERIFICATION_PROVIDER must be 'disabled'")
    out += [f"{n} must be empty" for n in _PROVIDER_SECRETS if env.get(n)]
    dotenv = os.path.join(cwd, ".env")
    if os.path.exists(dotenv) and os.path.getsize(dotenv) > 0:
        out.append(f"{dotenv} is not empty: Settings would load it as a fallback")
    return out


def check(env: Mapping[str, str]) -> None:
    """Raises `RuntimeError` with remediation text when the suite would hit the shared stack."""
    if env.get(STRICT) == "1":
        problems = strict_problems(env)
        if problems:
            raise RuntimeError(
                "QA strict isolation failed:\n  - " + "\n  - ".join(problems) + "\n(CI and "
                f"{OVERRIDE} are ignored in strict mode.)"
            )
        return
    reasons = shared_dev_targets(env)
    if not reasons or is_acknowledged(env):
        return
    raise RuntimeError(
        "Refusing to run the test suite against the shared development stack:\n  - "
        + "\n  - ".join(reasons)
        + "\nPoint DATABASE_URL, MIGRATIONS_DATABASE_URL and REDIS_URL at disposable instances "
        "(see docs/testing/FULL_TEST_SUITE.md and docs/testing/QA_EXECUTION_PLAN.md), or export "
        f"{OVERRIDE}=1 to acknowledge that you accept the risk for this invocation."
    )


def default_env() -> Mapping[str, str]:
    return os.environ

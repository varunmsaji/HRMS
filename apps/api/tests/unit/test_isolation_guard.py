"""The shared-dev-stack refusal in `tests/isolation_guard.py` (QA ENV-ISOL-001/002)."""

import pytest
from tests import isolation_guard as guard

DEV_DB = "postgresql://hrms:x@localhost:5433/hrms_dev"
DEV_REDIS = "redis://localhost:6380/0"


def test_default_shared_dev_targets_are_refused() -> None:
    with pytest.raises(RuntimeError) as exc:
        guard.check({"DATABASE_URL": DEV_DB, "REDIS_URL": DEV_REDIS})
    text = str(exc.value)
    assert "hrms_dev" in text and "6380" in text and guard.OVERRIDE in text


def test_either_shared_target_alone_is_refused() -> None:
    with pytest.raises(RuntimeError):
        guard.check({"DATABASE_URL": "postgresql://u:p@127.0.0.1:15433/qa", "REDIS_URL": DEV_REDIS})
    with pytest.raises(RuntimeError):
        guard.check({"DATABASE_URL": DEV_DB, "REDIS_URL": "redis://127.0.0.1:16380/0"})


def test_disposable_targets_are_allowed() -> None:
    guard.check(
        {
            "DATABASE_URL": "postgresql://u:p@127.0.0.1:15433/hrms_qa_x",
            "REDIS_URL": "redis://127.0.0.1:16380/0",
        }
    )


def test_runner_targets_are_allowed() -> None:
    # run_full_tests.py: separate DB name, shared Redis server but index 1.
    guard.check(
        {
            "DATABASE_URL": "postgresql://u:p@localhost:5433/hrms_test",
            "REDIS_URL": "redis://localhost:6380/1",
        }
    )


def test_explicit_acknowledgement_and_ci_are_honoured() -> None:
    base = {"DATABASE_URL": DEV_DB, "REDIS_URL": DEV_REDIS}
    guard.check({**base, guard.OVERRIDE: "1"})
    guard.check({**base, "CI": "true"})
    with pytest.raises(RuntimeError):
        guard.check({**base, guard.OVERRIDE: "0"})


def test_a_database_named_hrms_dev_is_refused_on_any_host() -> None:
    with pytest.raises(RuntimeError):
        guard.check(
            {
                "DATABASE_URL": "postgresql://u:p@db.internal:5433/hrms_dev",
                "REDIS_URL": "redis://cache.internal:6380/3",
            }
        )


# ---- strict (QA sandbox) mode -------------------------------------------------------------------

STRICT_OK = {
    "HRMS_QA_STRICT": "1",
    "DATABASE_URL": "postgresql://hrms:x@127.0.0.1:15432/hrms_qa_b1",
    "MIGRATIONS_DATABASE_URL": "postgresql://hrms:x@127.0.0.1:15432/hrms_qa_b1",
    "HRMS_APP_DATABASE_URL": "postgresql://hrms_app:x@127.0.0.1:15432/hrms_qa_b1",
    "REDIS_URL": "redis://127.0.0.1:16379/2",
    "S3_ENDPOINT_URL": "http://127.0.0.1:19000",
}


def test_strict_accepts_a_proper_sandbox(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert guard.strict_problems(STRICT_OK, str(tmp_path)) == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"DATABASE_URL": "postgresql://hrms:x@127.0.0.1:15432/hrms_test"},  # not hrms_qa_*
        {"DATABASE_URL": "postgresql://hrms:x@localhost:15432/hrms_qa_b1"},  # not literal loopback
        {"MIGRATIONS_DATABASE_URL": "postgresql://hrms:x@127.0.0.1:5433/hrms_qa_b1"},  # shared port
        {"HRMS_APP_DATABASE_URL": "postgresql://hrms_app:x@127.0.0.1:5432/hrms_qa_b1"},  # system PG
        {"REDIS_URL": "redis://127.0.0.1:6380/2"},
        {"REDIS_URL": "redis://127.0.0.1/2"},  # implicit 6379
        {"CELERY_BROKER_URL": "redis://127.0.0.1:6379/15"},
        {"S3_ENDPOINT_URL": "http://127.0.0.1:9000"},
        {"S3_ENDPOINT_URL": "http://minio.internal:19000"},
        {"EMAIL_PROVIDER": "smtp"},
        {"FACE_VERIFICATION_PROVIDER": "facepp"},
        {"MAILTRAP_API_TOKEN": "tok"},
    ],
)
def test_strict_rejects_each_redirect(mutation: dict[str, str], tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert guard.strict_problems({**STRICT_OK, **mutation}, str(tmp_path))


@pytest.mark.parametrize(
    "missing", ["DATABASE_URL", "MIGRATIONS_DATABASE_URL", "REDIS_URL", "S3_ENDPOINT_URL"]
)
def test_strict_treats_a_missing_variable_as_a_failure(missing: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    env = {k: v for k, v in STRICT_OK.items() if k != missing}
    assert any(missing in p for p in guard.strict_problems(env, str(tmp_path)))


def test_strict_rejects_a_non_empty_dotenv(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://x@localhost:5433/hrms_dev\n")
    assert any(".env" in p for p in guard.strict_problems(STRICT_OK, str(tmp_path)))
    (tmp_path / ".env").write_text("")
    assert guard.strict_problems(STRICT_OK, str(tmp_path)) == []


def test_strict_ignores_ci_and_the_override() -> None:
    bad = {**STRICT_OK, "DATABASE_URL": "postgresql://hrms:x@127.0.0.1:5433/hrms_dev"}
    with pytest.raises(RuntimeError):
        guard.check({**bad, "CI": "true", guard.OVERRIDE: "1"})


def test_non_strict_also_checks_the_migration_and_app_urls() -> None:
    env = {
        "DATABASE_URL": "postgresql://u:p@127.0.0.1:15433/qa",
        "REDIS_URL": "redis://127.0.0.1:16380/0",
    }
    with pytest.raises(RuntimeError):
        guard.check({**env, "MIGRATIONS_DATABASE_URL": DEV_DB})
    with pytest.raises(RuntimeError):
        guard.check({**env, "CELERY_BROKER_URL": DEV_REDIS})

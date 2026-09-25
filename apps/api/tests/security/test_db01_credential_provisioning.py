"""Regression coverage for Finding DB-01 (RELEASE_HARDENING_PHASE_6_DEPLOYMENT_READINESS.md §6,
fixed in RELEASE_HARDENING_PHASE_6A): production's `hrms_app` runtime-role password used to be a
fixed, repository-visible literal (`hrms_app_dev_password`) in
`infra/docker/postgres/init/002_app_role.sql`, applied unconditionally to every environment
including production, independent of anything the operator set in `DATABASE_URL`.

These are plain file/config assertions, not database tests — the goal is to fail CI immediately if
someone reintroduces a hardcoded production password or silently defaults `HRMS_APP_PASSWORD` in
`docker-compose.prod.yml`, rather than only discovering it the way Phase 6 did (a live deployment
audit against a real container).
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
HARDCODED_DEV_PASSWORD = "hrms_app_dev_password"


def _load_compose(name: str) -> dict:
    with (REPO_ROOT / name).open() as f:
        return yaml.safe_load(f)


def test_prod_compose_requires_hrms_app_password_with_no_default() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    postgres_env = compose["services"]["postgres"]["environment"]
    value = postgres_env["HRMS_APP_PASSWORD"]

    assert isinstance(value, str)
    # `${VAR:?message}` fails the `docker compose` invocation outright if HRMS_APP_PASSWORD is
    # unset — the fail-closed behavior Finding DB-01 requires. A bare `${HRMS_APP_PASSWORD}` or a
    # `${HRMS_APP_PASSWORD:-default}` would silently reintroduce the same class of defect.
    assert value.startswith("${HRMS_APP_PASSWORD:?")
    assert HARDCODED_DEV_PASSWORD not in value


def test_prod_compose_does_not_hardcode_any_postgres_password() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    postgres_env = compose["services"]["postgres"]["environment"]

    for key in ("POSTGRES_PASSWORD", "HRMS_APP_PASSWORD"):
        value = postgres_env[key]
        assert value.startswith("${"), f"{key} must come from the environment, not a literal"
        assert HARDCODED_DEV_PASSWORD not in value


def test_dev_compose_still_sets_the_fixed_dev_only_password() -> None:
    # Unlike prod, the dev compose intentionally keeps a fixed, repo-visible value — it is not a
    # secret (nothing but a local throwaway container ever uses it), and
    # tests/security/test_rls_runtime_role.py hardcodes the same value in its connection URL.
    compose = _load_compose("docker-compose.yml")
    postgres_env = compose["services"]["postgres"]["environment"]
    assert postgres_env["HRMS_APP_PASSWORD"] == HARDCODED_DEV_PASSWORD


def test_init_script_has_no_hardcoded_password_literal() -> None:
    script = (REPO_ROOT / "infra" / "docker" / "postgres" / "init" / "002_app_role.sh").read_text()

    assert HARDCODED_DEV_PASSWORD not in script
    assert "$HRMS_APP_PASSWORD" in script
    # `: "${VAR:?message}"` is the shell fail-closed idiom — exits non-zero with `message` if
    # HRMS_APP_PASSWORD is unset, rather than passing an empty/literal password to `CREATE ROLE`.
    assert ': "${HRMS_APP_PASSWORD:?' in script


def test_old_hardcoded_init_sql_file_is_gone() -> None:
    old_path = REPO_ROOT / "infra" / "docker" / "postgres" / "init" / "002_app_role.sql"
    assert not old_path.exists()


def test_ci_workflow_applies_sh_init_scripts_with_hrms_app_password() -> None:
    ci_yaml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "HRMS_APP_PASSWORD" in ci_yaml
    assert "*.sh" in ci_yaml

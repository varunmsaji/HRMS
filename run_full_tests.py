#!/usr/bin/env python3
"""One-command test suite orchestrator for Staff Spectrum HRMS.

Runs static checks, backend unit/integration/security tests, and frontend
typecheck/tests/build, against an isolated database and Redis namespace so it
never touches the developer's `hrms_dev` data. See docs/testing/FULL_TEST_SUITE.md.

Usage:
    python run_full_tests.py [--quick|--unit|--static|--integration|--security
                               |--backend|--frontend] [--keep-services] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
API_DIR = REPO_ROOT / "apps" / "api"
WEB_DIR = REPO_ROOT / "apps" / "web"
RESULTS_DIR = REPO_ROOT / "test-results"

# Dev-only, repo-visible credentials from docker-compose.yml / apps/api/.env.example.
# Never used against staging/production — see assert_safe_target() below.
PG_HOST = "localhost"
PG_PORT = "5433"
PG_ADMIN_USER = "hrms"
PG_ADMIN_PASSWORD = "hrms_dev_password"
PG_APP_PASSWORD = "hrms_app_dev_password"
DEV_DB_NAME = "hrms_dev"
TEST_DB_NAME = "hrms_test"
REDIS_HOST_PORT = "6380"
TEST_REDIS_URL = f"redis://{PG_HOST}:{REDIS_HOST_PORT}/1"  # /1, dev uses /0 — kept apart
JWT_ACCESS_SECRET = "runner-test-access-secret-min-16"
JWT_REFRESH_SECRET = "runner-test-refresh-secret-min-16"

# Same values CI (.github/workflows/ci.yml) uses for its "Integration + security" step: the
# schema-owner role, not hrms_app, because dozens of fixture teardown helpers rely on BYPASSRLS
# for raw cross-tenant DELETE/INSERT. tests/security/test_rls_runtime_role.py proves RLS itself
# by opening its own hrms_app connection, independent of this DATABASE_URL.
_TEST_DB_URL = f"postgresql://{PG_ADMIN_USER}:{PG_ADMIN_PASSWORD}@{PG_HOST}:{PG_PORT}/{TEST_DB_NAME}"

BACKEND_ENV: dict[str, str] = {
    "ENVIRONMENT": "development",  # Settings has no "test" literal; CI uses this value too.
    "DATABASE_URL": _TEST_DB_URL,
    # alembic/env.py prefers MIGRATIONS_DATABASE_URL from the real OS environment first, but
    # falls back to reading it out of apps/api/.env directly (via dotenv_values) *before* ever
    # considering settings.database_url — and this repo's real .env has MIGRATIONS_DATABASE_URL
    # pointing at hrms_dev. Without setting it here too, `alembic upgrade head` silently migrates
    # hrms_dev (a no-op since it's already at head) while hrms_test never gets its schema at all.
    # Confirmed by direct observation while building this script.
    "MIGRATIONS_DATABASE_URL": _TEST_DB_URL,
    "REDIS_URL": TEST_REDIS_URL,
    "JWT_ACCESS_SECRET": JWT_ACCESS_SECRET,
    "JWT_REFRESH_SECRET": JWT_REFRESH_SECRET,
    "TZ": "UTC",
}

STAGE_TIMEOUTS = {
    "prerequisites": 30,
    "infra": 120,
    "db-setup": 60,
    "migrations": 120,
    "static": 300,
    "unit": 300,
    "integration-security": 1800,
    "frontend-install": 300,
    "frontend-typecheck": 180,
    "frontend-test": 300,
    "frontend-build": 300,
}


@dataclass
class StageResult:
    name: str
    category: str
    status: str  # PASS, FAIL, ERROR, SKIPPED, FLAKY, ENVIRONMENT-BLOCKED
    duration_s: float
    detail: str = ""
    flaky_tests: list[str] = field(default_factory=list)


class Runner:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.stages: list[StageResult] = []
        self.started_infra = False

    def run_cmd(
        self,
        cmd: list[str],
        cwd: Path,
        env_overrides: dict[str, str] | None,
        timeout: int,
    ) -> tuple[int, str, str, float]:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                timeout=timeout,
                capture_output=not self.verbose,
                text=True,
            )
            duration = time.monotonic() - start
            return (
                proc.returncode,
                proc.stdout or "" if not self.verbose else "",
                proc.stderr or "" if not self.verbose else "",
                duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            return (
                124,
                (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                f"TIMEOUT after {timeout}s: {' '.join(cmd)}",
                duration,
            )
        except FileNotFoundError as exc:
            return (127, "", str(exc), 0.0)

    def add(self, result: StageResult) -> None:
        self.stages.append(result)
        icon = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERROR", "SKIPPED": "SKIP", "FLAKY": "FLAKY"}
        print(f"  [{icon.get(result.status, result.status):>5}] {result.name} ({result.duration_s:.1f}s)")
        if result.status not in ("PASS", "SKIPPED") and result.detail:
            print(f"         {result.detail.strip().splitlines()[-1][:200]}" if result.detail.strip() else "")


def assert_safe_target() -> None:
    """Refuse to run against anything that isn't the local disposable test DB."""
    if "test" not in TEST_DB_NAME.lower():
        raise SystemExit(f"SAFETY ABORT: test database name {TEST_DB_NAME!r} does not contain 'test'")
    if TEST_DB_NAME == DEV_DB_NAME:
        raise SystemExit("SAFETY ABORT: test database name must differ from the dev database name")
    if PG_HOST not in ("localhost", "127.0.0.1"):
        raise SystemExit(f"SAFETY ABORT: refusing non-local Postgres host {PG_HOST!r}")
    for var in ("DATABASE_URL", "MIGRATIONS_DATABASE_URL"):
        val = os.environ.get(var, "")
        if val and TEST_DB_NAME not in val and any(k in val for k in ("staging", "prod", "amazonaws", "rds")):
            raise SystemExit(f"SAFETY ABORT: ambient {var} looks like a non-local/production URL: {val!r}")


def print_banner() -> None:
    print("=" * 70)
    print("STAFF SPECTRUM — FULL TEST SUITE")
    print("=" * 70)
    print("Environment:")
    print(f"  Database : disposable Postgres database {TEST_DB_NAME!r} on {PG_HOST}:{PG_PORT}")
    print(f"             (dev database {DEV_DB_NAME!r} is never read or written)")
    print(f"  Redis    : logical DB index 1 on {PG_HOST}:{REDIS_HOST_PORT} (dev uses index 0)")
    print("  MinIO    : shared dev bucket 'hrms-documents' (known limitation, see docs)")
    print("  Settings : ENVIRONMENT=development (no 'test' literal exists in Settings)")
    print("-" * 70)


# --------------------------------------------------------------------------
# Infra
# --------------------------------------------------------------------------


def compose_cmd() -> list[str]:
    if shutil.which("docker") and subprocess.run(
        ["docker", "compose", "version"], capture_output=True
    ).returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise SystemExit("SAFETY ABORT: neither 'docker compose' nor 'docker-compose' is available")


def container_health(name: str) -> str | None:
    proc = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def stage_prerequisites(runner: Runner) -> StageResult:
    start = time.monotonic()
    missing = [b for b in ("docker", "psql", "uv", "npx", "npm") if not shutil.which(b)]
    if missing:
        return StageResult(
            "prerequisites", "infra", "ERROR", time.monotonic() - start, f"missing binaries: {missing}"
        )
    compose_cmd()  # raises if neither variant is present
    return StageResult("prerequisites", "infra", "PASS", time.monotonic() - start)


def stage_infra_up(runner: Runner) -> StageResult:
    start = time.monotonic()
    already_running = all(
        container_health(c) == "healthy" for c in ("hrms-postgres", "hrms-redis", "hrms-minio")
    )
    if not already_running:
        runner.started_infra = True
        rc, _out, err, _d = runner.run_cmd(
            [*compose_cmd(), "up", "-d"], REPO_ROOT, None, STAGE_TIMEOUTS["infra"]
        )
        if rc != 0:
            return StageResult("infra-up", "infra", "ERROR", time.monotonic() - start, err)
    deadline = time.monotonic() + STAGE_TIMEOUTS["infra"]
    services = ["hrms-postgres", "hrms-redis", "hrms-minio"]
    while time.monotonic() < deadline:
        statuses = {c: container_health(c) for c in services}
        if all(v == "healthy" for v in statuses.values()):
            return StageResult("infra-up", "infra", "PASS", time.monotonic() - start)
        time.sleep(2)
    return StageResult(
        "infra-up", "infra", "FAIL", time.monotonic() - start, f"containers not healthy in time: {statuses}"
    )


# --------------------------------------------------------------------------
# Test database setup
# --------------------------------------------------------------------------


def psql(args: list[str], dbname: str, timeout: int = 30) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PGPASSWORD"] = PG_ADMIN_PASSWORD
    cmd = ["psql", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_ADMIN_USER, "-d", dbname, "-v", "ON_ERROR_STOP=1", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)


def stage_setup_test_database(runner: Runner) -> StageResult:
    start = time.monotonic()
    try:
        exists = psql(["-tAc", f"SELECT 1 FROM pg_database WHERE datname='{TEST_DB_NAME}'"], "postgres")
        if exists.returncode != 0:
            return StageResult("db-setup", "infra", "ERROR", time.monotonic() - start, exists.stderr)
        if exists.stdout.strip() != "1":
            created = psql(["-c", f"CREATE DATABASE {TEST_DB_NAME} OWNER {PG_ADMIN_USER}"], "postgres")
            if created.returncode != 0:
                return StageResult("db-setup", "infra", "ERROR", time.monotonic() - start, created.stderr)

        ext = psql(["-f", str(REPO_ROOT / "infra/docker/postgres/init/001_extensions.sql")], TEST_DB_NAME)
        if ext.returncode != 0:
            return StageResult("db-setup", "infra", "ERROR", time.monotonic() - start, ext.stderr)

        # Re-runs infra/docker/postgres/init/002_app_role.sh against the test DB (idempotent: the
        # hrms_app role is cluster-wide and already exists from hrms_dev's init; this only grants
        # DML on hrms_test's tables, which is per-database).
        env = os.environ.copy()
        env.update(
            {
                "PGHOST": PG_HOST,
                "PGPORT": PG_PORT,
                "PGPASSWORD": PG_ADMIN_PASSWORD,
                "POSTGRES_USER": PG_ADMIN_USER,
                "POSTGRES_DB": TEST_DB_NAME,
                "HRMS_APP_PASSWORD": PG_APP_PASSWORD,
            }
        )
        role = subprocess.run(
            ["sh", str(REPO_ROOT / "infra/docker/postgres/init/002_app_role.sh")],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        if role.returncode != 0:
            return StageResult("db-setup", "infra", "ERROR", time.monotonic() - start, role.stderr)
    except subprocess.TimeoutExpired as exc:
        return StageResult("db-setup", "infra", "FAIL", time.monotonic() - start, str(exc))
    return StageResult("db-setup", "infra", "PASS", time.monotonic() - start)


def venv_python() -> str:
    # `uv run pytest`/`uv run alembic` resolve to a broken interpreter in this environment (a
    # conda Python leaks in ahead of the project's own .venv); invoke the venv's own interpreter
    # directly instead. `uv run ruff`/`mypy`/`lint-imports` are unaffected and keep using `uv run`.
    venv_py = API_DIR / ".venv" / "bin" / "python"
    if not venv_py.exists():
        raise SystemExit(f"SAFETY ABORT: expected venv interpreter not found at {venv_py}")
    return str(venv_py)


def stage_migrations(runner: Runner) -> StageResult:
    start = time.monotonic()
    rc, out, err, duration = runner.run_cmd(
        [venv_python(), "-m", "alembic", "upgrade", "head"], API_DIR, BACKEND_ENV, STAGE_TIMEOUTS["migrations"]
    )
    status = "PASS" if rc == 0 else "FAIL"
    return StageResult("alembic-upgrade-head", "infra", status, duration, out + err)


def cleanup_test_database() -> None:
    try:
        psql(
            [
                "-c",
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname='{TEST_DB_NAME}' AND pid <> pg_backend_pid()",
            ],
            "postgres",
        )
        psql(["-c", f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"], "postgres")
    except Exception as exc:  # best-effort cleanup, never crash on the way out
        print(f"  (cleanup warning: could not drop {TEST_DB_NAME}: {exc})")


# --------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------


def stage_static_checks(runner: Runner) -> list[StageResult]:
    checks = [
        ("ruff-check", ["uv", "run", "ruff", "check", "."]),
        ("ruff-format-check", ["uv", "run", "ruff", "format", "--check", "."]),
        ("mypy", ["uv", "run", "mypy", "src/hrms"]),
        ("lint-imports", ["uv", "run", "lint-imports"]),
    ]
    results = []
    for name, cmd in checks:
        rc, out, err, duration = runner.run_cmd(cmd, API_DIR, BACKEND_ENV, STAGE_TIMEOUTS["static"])
        results.append(StageResult(name, "static", "PASS" if rc == 0 else "FAIL", duration, out + err))
    return results


# --------------------------------------------------------------------------
# Pytest stages (with one-shot flaky-detection rerun)
# --------------------------------------------------------------------------


def run_pytest(
    runner: Runner, name: str, paths: list[str], timeout: int
) -> tuple[StageResult, Path | None]:
    RESULTS_DIR.mkdir(exist_ok=True)
    junit = RESULTS_DIR / f"{name}.xml"
    cmd = [venv_python(), "-m", "pytest", *paths, f"--junitxml={junit}"]
    rc, out, err, duration = runner.run_cmd(cmd, API_DIR, BACKEND_ENV, timeout)
    if rc == 0:
        return StageResult(name, "backend", "PASS", duration, junit_path_str(junit)), junit

    # One rerun of just the failed tests, to distinguish a real failure from a flaky one.
    # This never converts a fail into a reported pass — both runs are recorded, and the stage
    # is marked FLAKY (still a non-zero exit) rather than PASS.
    rerun_junit = RESULTS_DIR / f"{name}.rerun.xml"
    rc2, out2, err2, duration2 = runner.run_cmd(
        [venv_python(), "-m", "pytest", *paths, "--lf", f"--junitxml={rerun_junit}"],
        API_DIR,
        BACKEND_ENV,
        timeout,
    )
    total_duration = duration + duration2
    if rc2 == 0:
        flaky_ids = failed_test_ids(junit)
        return (
            StageResult(name, "backend", "FLAKY", total_duration, out + err, flaky_tests=flaky_ids),
            junit,
        )
    return StageResult(name, "backend", "FAIL", total_duration, out + err), junit


def junit_path_str(path: Path) -> str:
    return f"see {path.relative_to(REPO_ROOT)}"


def failed_test_ids(junit: Path) -> list[str]:
    if not junit.exists():
        return []
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError:
        return []
    ids = []
    for tc in root.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            ids.append(f"{tc.get('classname', '')}::{tc.get('name', '')}")
    return ids


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------


def stage_frontend(runner: Runner) -> list[StageResult]:
    results = []
    web_env = {"TZ": "America/New_York"}  # matches CI: TZ-rendering assertions must not pass by luck

    if not (WEB_DIR / "node_modules").exists():
        rc, out, err, duration = runner.run_cmd(["npm", "ci"], WEB_DIR, web_env, STAGE_TIMEOUTS["frontend-install"])
        results.append(StageResult("npm-ci", "frontend", "PASS" if rc == 0 else "ERROR", duration, out + err))
        if rc != 0:
            return results

    rc, out, err, duration = runner.run_cmd(
        ["npx", "tsc", "--noEmit"], WEB_DIR, web_env, STAGE_TIMEOUTS["frontend-typecheck"]
    )
    results.append(StageResult("typescript", "frontend", "PASS" if rc == 0 else "FAIL", duration, out + err))

    RESULTS_DIR.mkdir(exist_ok=True)
    vitest_junit = RESULTS_DIR / "web-vitest.xml"
    rc, out, err, duration = runner.run_cmd(
        ["npx", "vitest", "run", "--reporter=junit", f"--outputFile={vitest_junit}"],
        WEB_DIR,
        web_env,
        STAGE_TIMEOUTS["frontend-test"],
    )
    results.append(StageResult("vitest", "frontend", "PASS" if rc == 0 else "FAIL", duration, out + err))

    build_env = dict(web_env)
    build_env["NEXT_PUBLIC_API_URL"] = "http://localhost:8000"
    rc, out, err, duration = runner.run_cmd(
        ["npm", "run", "build"], WEB_DIR, build_env, STAGE_TIMEOUTS["frontend-build"]
    )
    results.append(StageResult("production-build", "frontend", "PASS" if rc == 0 else "FAIL", duration, out + err))
    return results


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def merge_junit(paths: list[Path], out_path: Path) -> None:
    combined = ET.Element("testsuites")
    for p in paths:
        if not p.exists():
            continue
        try:
            root = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        if root.tag == "testsuites":
            combined.extend(list(root))
        else:
            combined.append(root)
    ET.ElementTree(combined).write(out_path, encoding="utf-8", xml_declaration=True)


def build_results_json(stages: list[StageResult], junit_paths: list[Path]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    tests = []
    for jp in junit_paths:
        if not jp.exists():
            continue
        try:
            root = ET.parse(jp).getroot()
        except ET.ParseError:
            continue
        suites = root.iter("testsuite") if root.tag == "testsuites" else [root]
        for suite in suites:
            for tc in suite.findall("testcase"):
                failure = tc.find("failure")
                error = tc.find("error")
                skipped = tc.find("skipped")
                if failure is not None:
                    status, err_text = "FAIL", failure.get("message", "") or (failure.text or "")
                elif error is not None:
                    status, err_text = "ERROR", error.get("message", "") or (error.text or "")
                elif skipped is not None:
                    status, err_text = "SKIPPED", ""
                else:
                    status, err_text = "PASS", ""
                tests.append(
                    {
                        "name": f"{tc.get('classname', '')}::{tc.get('name', '')}",
                        "category": jp.stem,
                        "duration_s": float(tc.get("time", 0.0)),
                        "status": status,
                        "error": err_text[:2000] if err_text else None,
                        "timestamp": now,
                    }
                )
    return {
        "generated_at": now,
        "environment": {
            "database": TEST_DB_NAME,
            "redis": TEST_REDIS_URL,
            "settings_environment": "development",
        },
        "stages": [
            {
                "name": s.name,
                "category": s.category,
                "status": s.status,
                "duration_s": round(s.duration_s, 2),
                "flaky_tests": s.flaky_tests,
            }
            for s in stages
        ],
        "tests": tests,
    }


def print_summary(stages: list[StageResult]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("STAFF SPECTRUM — FULL TEST SUITE — RESULT SUMMARY")
    lines.append("=" * 70)
    by_category: dict[str, list[StageResult]] = {}
    for s in stages:
        by_category.setdefault(s.category, []).append(s)
    for category, items in by_category.items():
        lines.append("-" * 70)
        lines.append(category.upper())
        lines.append("-" * 70)
        for s in items:
            lines.append(f"{s.name:<30} {s.status:<8} {s.duration_s:6.1f}s")
            if s.flaky_tests:
                for t in s.flaky_tests:
                    lines.append(f"    flaky: {t}")
    lines.append("=" * 70)
    counts: dict[str, int] = {}
    for s in stages:
        counts[s.status] = counts.get(s.status, 0) + 1
    lines.append("TOTAL STAGES: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    failed = any(s.status not in ("PASS", "SKIPPED") for s in stages)
    lines.append("RESULT: " + ("FAIL" if failed else "PASS"))
    lines.append("=" * 70)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quick", action="store_true", help="unit tests only, no infra/DB required")
    p.add_argument("--static", action="store_true", help="static checks only (ruff/mypy/import-linter)")
    p.add_argument("--unit", action="store_true", help="backend unit tests only")
    p.add_argument("--integration", action="store_true", help="backend integration tests only")
    p.add_argument("--security", action="store_true", help="backend security tests only")
    p.add_argument("--backend", action="store_true", help="static + unit + integration + security")
    p.add_argument("--frontend", action="store_true", help="frontend typecheck + tests + build only")
    p.add_argument("--keep-services", action="store_true", help="keep the test database after the run")
    p.add_argument("--verbose", action="store_true", help="stream subprocess output instead of capturing it")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    assert_safe_target()
    print_banner()

    any_flag = any([args.quick, args.static, args.unit, args.integration, args.security, args.backend, args.frontend])
    run_static = args.static or args.backend or not any_flag
    run_unit = args.quick or args.unit or args.backend or not any_flag
    run_integration = args.integration or args.backend or (not any_flag and not args.quick)
    run_security = args.security or args.backend or (not any_flag and not args.quick)
    run_frontend = args.frontend or (not any_flag and not args.quick)

    # Redis is touched by an autouse fixture on every backend test (root conftest.py's
    # _reset_credential_rate_limits). And despite CI's "unit tests (no database)" step name, some
    # "unit" tests do open a real DB connection when the app boots (health/readiness checks,
    # test_crypto_keys) — CI only gets away with this because it migrates hrms_dev before either
    # pytest step. So any backend run, including --unit alone, needs the schema present too.
    run_backend = run_unit or run_integration or run_security
    needs_schema = run_backend

    runner = Runner(verbose=args.verbose)
    junit_files: list[Path] = []
    db_prepared = False

    try:
        print("PREREQUISITES")
        pre = stage_prerequisites(runner)
        runner.add(pre)
        if pre.status != "PASS":
            print(print_summary(runner.stages))
            return 1

        if run_backend:
            print("INFRASTRUCTURE")
            runner.add(stage_infra_up(runner))
            if needs_schema:
                db_result = stage_setup_test_database(runner)
                runner.add(db_result)
                if db_result.status == "PASS":
                    db_prepared = True
                    runner.add(stage_migrations(runner))

        if run_static:
            print("STATIC ANALYSIS")
            for r in stage_static_checks(runner):
                runner.add(r)

        if run_unit:
            print("UNIT TESTS")
            result, jp = run_pytest(runner, "unit", ["tests/unit"], STAGE_TIMEOUTS["unit"])
            runner.add(result)
            if jp:
                junit_files.append(jp)

        int_sec_paths = []
        if run_integration:
            int_sec_paths.append("tests/integration")
        if run_security:
            int_sec_paths.append("tests/security")
        if int_sec_paths:
            print("INTEGRATION + SECURITY TESTS")
            result, jp = run_pytest(
                runner, "integration-security", int_sec_paths, STAGE_TIMEOUTS["integration-security"]
            )
            runner.add(result)
            if jp:
                junit_files.append(jp)

        if run_frontend:
            print("FRONTEND")
            for r in stage_frontend(runner):
                runner.add(r)
                if r.name == "vitest":
                    junit_files.append(RESULTS_DIR / "web-vitest.xml")

    finally:
        if db_prepared and not args.keep_services:
            cleanup_test_database()
        elif db_prepared and args.keep_services:
            print(f"(--keep-services: leaving {TEST_DB_NAME} in place for inspection)")

    RESULTS_DIR.mkdir(exist_ok=True)
    merge_junit(junit_files, RESULTS_DIR / "results.xml")
    results_json = build_results_json(runner.stages, junit_files)
    (RESULTS_DIR / "results.json").write_text(json.dumps(results_json, indent=2))
    summary = print_summary(runner.stages)
    (RESULTS_DIR / "summary.txt").write_text(summary)
    print(summary)

    failed = any(s.status not in ("PASS", "SKIPPED") for s in runner.stages)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

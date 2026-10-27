# HRMS QA Strategy (Phase 2 — formal catalogue and traceability)

| Field | Value |
|---|---|
| Date | 2026-10-25 |
| Phase | QA Phase 2, catalogue and coverage-mapping stage (no application code, tests, migrations or data were changed) |
| Inputs inspected | `FUNCTIONAL_QA_REPORT_2026-10-25.md` (all 13 sections, 170 lines), `qa_live_2026-10-25/` (17 files), 264 backend test files, 64 web test files, 34 mobile test files, `.github/workflows/ci.yml`, `docs/testing/*`, `docs/business-rules/*`, `docs/audits/PAYROLL_*`, `docs/operations/PLATFORM_CONSOLE.md` |
| Companion documents | [`QA_TEST_CASES.csv`](QA_TEST_CASES.csv) · [`QA_TEST_MAP.csv`](QA_TEST_MAP.csv) · [`QA_TRACEABILITY_MATRIX.md`](QA_TRACEABILITY_MATRIX.md) · [`QA_DEFECT_REGISTER.md`](QA_DEFECT_REGISTER.md) · [`QA_EXECUTION_PLAN.md`](QA_EXECUTION_PLAN.md) · [`QA_BASELINE_RESULTS.md`](QA_BASELINE_RESULTS.md) |

Existing documents were **not duplicated**. `MASTER_PRODUCT_TEST_PLAN.md` (module map, journeys, risk areas), `FULL_TEST_SUITE.md` (the `run_full_tests.py` runner) and the two module audits remain the source for their own topics. This strategy adds the layer they lack: stable case IDs, an evidence taxonomy, a requirement→test trace, and an execution gate model. Where the older documents disagree with this one, this one governs QA execution; the disagreement is recorded in the defect register (Part D).

## 1. Principles

1. **A test count is not coverage.** Coverage is only ever stated as *"N of M catalogue cases have at least one linked check"*, with M named. Linkage says a check exists; it does not say the check asserts the business rule. See §5.
2. **Every statement carries an evidence class** (§2). Nothing inherited from the 2026-10-25 report is marked verified here.
3. **Expected results come from an authority, not from the implementation.** The authority order is: signed-off decision documents (`PAYROLL_BUSINESS_DECISIONS.md`, `00_PAYROLL_IMPLEMENTATION_PLAN.md` §8, `ATTENDANCE_*_CLIENT_SIGNOFF`) → business-rule documents → code. Where the code is the only source, or sources disagree, the case records the question in its `ambiguity` column and is **not** allowed to be marked PASS or FAIL until the product owner answers.
4. **No business rule is changed to make a test pass.** A failing check is either a defect (rule is clear and behaviour differs), a clarification (rule unclear), or a feature gap (rule documented as not built).
5. **Unimplemented ≠ failed.** Recruitment, resume/AI features, payment/usage billing and reports/exports are `NOT_APPLICABLE` (cases `REC-NI-001`, `AI-NI-001`, `BILL-NI-001`, `RPT-NI-001`), not failures.
6. **Destructive or shared-resource actions need opt-in** and are never the default (§7).

## 2. Evidence classes used in every document

| Class | Meaning | Examples in this phase |
|---|---|---|
| **VERIFIED** | I observed it in this phase by reading files or running a read-only command | register schema/row count; `df -h /`; stale `.venv` shebang; `which flutter` empty; `docker ps` health; test-function counts; the `or True` in `j3_leave.py:61` |
| **INHERITED** | Stated by the 2026-10-25 report or another document; not re-run here | 3,198 backend passed; 522 Vitest; 216 live checks (214 PASS); 110 ESLint errors; DEF-02/03/04 fixes |
| **INFERRED** | Derived by me from code structure (heuristic) | `assertion_class_inferred` in `QA_TEST_MAP.csv`; keyword-based external-dependency flags |
| **BLOCKED** | Cannot be executed until a named blocker is cleared | Flutter tests (SDK absent) |
| **UNKNOWN** | No evidence either way | Anything in a case's `actual` column that reads "NOT EXECUTED" |

## 3. Test levels and case types

`UNIT` (pure logic, no infra) · `API-E2E` (HTTP against a private stack) · `DB-INVARIANT` (SQL assertions on state after API actions, as the real runtime role) · `SECURITY` (authN/Z, tenancy, injection) · `CONCURRENCY` · `BOUNDARY` · `UNIT+ORACLE` (calculation compared with an independently computed value) · `UI-E2E` · `MOBILE-E2E` · `CONTRACT`/`STATIC` · `INFRA`/`BUILD`.

Priorities: **P0** money, tenant isolation/auth, data integrity, immutability, irreversible state transitions · **P1** core workflows and validation · **P2** configuration, observability, convenience.

## 4. Catalogue schema (`QA_TEST_CASES.csv`)

One row per case, UTF-8 CSV, 28 columns (Phase 3 added `command`). Stable key: `case_id`. IDs are `AREA-FEATURE-NNN`, never renumbered or reused; retired cases are kept with `NOT_APPLICABLE`.

| Column | Notes |
|---|---|
| `case_id`, `module`, `feature`, `requirement` | Requirement is stated as a testable sentence |
| `rule_source` | Document path/section that is the authority for the expected result |
| `test_type`, `priority`, `preconditions`, `role_tenant`, `test_data`, `steps`, `expected` | All synthetic data (`*@example.com`, `QA-<tag>-<rand>` companies) |
| `actual`, `inherited_result` | `actual` is only what *this phase* observed. `inherited_result` summarises linked live-register rows (e.g. `INHERITED_PASS (3 live checks)`) |
| `db_invariants`, `negative_assertions` | What must hold in the database, and what must **not** happen |
| `status` | `NOT_RUN` · `PASS` · `FAIL` · `BLOCKED` · `NOT_APPLICABLE` (strict enum). `PASS`/`FAIL` appear only where this phase verified the outcome (five environment cases) |
| `automation` | `AUTOMATED`, `AUTOMATED+LIVE_SCRIPT`, `PARTIAL`, `LIVE_SCRIPT_ONLY`, `CI_ONLY`, `NOT_AUTOMATED`, `N/A`. Demoted to `NOT_AUTOMATED` by the generator when no test or live check actually links |
| `evidence` | Path to the evidence, or the register row |
| `defect_ref`, `ambiguity` | Links into `QA_DEFECT_REGISTER.md` |
| `env_required`, `shared_resource_risk` | `UNIT`, `PRIVATE_STACK`, `BROWSER`, `FLUTTER`, `HOST`; plus any danger of running it against shared services |
| `live_checks`, `existing_test_files`, `existing_test_functions`, `test_globs` | Traceability back-links (the globs are the rule used to build `QA_TEST_MAP.csv`) |

**Honesty markers in the CSV.** `db_invariants` and `negative_assertions` that begin with `[module default - refine at execution]` were filled from a per-module template, not authored for that case; the case author must replace them when the case is first executed. Cases written with explicit invariants (e.g. all leave-ledger, punch-idempotency, payroll and K-1 cases) have no marker. `evidence` reads `NONE_YET …` until a run produces it.

`QA_TEST_MAP.csv` is the reverse index: **2,963 rows** = 2,649 backend test functions (AST-extracted) + 216 live checks + 64 web test files + 34 mobile test files, each with `case_ids` (`;`-separated, first = primary) or `UNMAPPED`.

## 5. What "covered" means here (denominators)

| Metric | Numerator | Denominator | Why this denominator |
|---|---|---|---|
| Catalogue linkage | cases with ≥1 live check **or** ≥1 automated test file linked | the 185 non-`NOT_APPLICABLE` cases | `NOT_APPLICABLE` cases have nothing to execute |
| Live linkage | cases with ≥1 live-register row | same 185 | |
| Assertion quality | live checks classified business/state vs technical | 216 live checks | |
| Test-map completeness | map rows with `case_ids != UNMAPPED` | 2,963 map rows | Shows no orphan tests; says nothing about correctness |

A linked test is a **candidate** for covering a case. Whether it asserts the case's *expected* outcome is established only by executing the case in the execution plan and reading the assertion. The generator's `assertion_class_inferred` (`API_STATUS_ONLY`, `API_BODY_OR_STATE`, `UNIT_LOGIC`, `NO_ASSERT_OR_RAISES_ONLY`) is a syntactic heuristic and must not be quoted as "business correctness coverage".

## 6. Environments and data

| Tier | Purpose | Composition | Status |
|---|---|---|---|
| `UNIT` | Pure logic | no network | Ready (use `python -m pytest`; console-script shebangs are stale) |
| `PRIVATE_STACK` | Everything else | disposable Postgres DB (name contains `qa`/`test`), dedicated Redis DB index and port, **private** MinIO with data on the non-root volume, `EMAIL_PROVIDER=logging`, Face provider `disabled`, private API (e.g. :18000) + private worker, `TZ=UTC` plus one run with a non-UTC host `TZ` | **Not reproducible today**: the live scripts hard-code a previous session's scratchpad paths (see `ENV-STACK-001`) |
| `BROWSER` | Web UI journeys | Built-in browser against the private stack | Not yet run |
| `FLUTTER` | Mobile | Flutter 3.29.2 (CI pin) in isolation | BLOCKED |
| `HOST` | Disk, venv, CI parity | Read-only inspection | Done for disk/venv |

Data rules: synthetic only; no shared dev DB, no production, no real email/payment. Credentials in scripts (`hrms_dev_password`, `hrms_app_dev_password`, `qa_minio…`) are repo-visible dev defaults; they must never be pointed at a non-local host.

## 7. Safety gates (apply to every batch)

1. **Identity check before any DB write:** print `current_database()`, host:port, role, and confirm the name is on an allow-list created for QA. `hrms_dev`, `hrms_test` (shared by `run_full_tests.py`), and anything not created by the batch are refused.
2. `tests/conftest.py` defaults `DATABASE_URL` to `hrms_dev`. Always export `DATABASE_URL` **and** `MIGRATIONS_DATABASE_URL` explicitly (see `FULL_TEST_SUITE.md`); verify with `echo` before pytest.
3. Deselect `tests/integration/core/test_storage.py::test_object_survives_a_minio_container_restart` unless a **private** MinIO container name is injected. It runs `docker restart hrms-minio`.
4. Never run `002_app_role.sh` against a migrated database (it re-grants UPDATE/DELETE on append-only tables).
5. Never start Celery Beat against shared Redis; never stop the shared worker/containers.
6. `HRMS_LIVE_API=1 flutter test test/live` targets `localhost:8000` by default (shared dev API) — redirect to the private API.
7. Disk guard: abort a batch if free space on `/` < 10 GiB (currently ~5 GiB) or on the stack's data volume.
8. Each batch writes its raw output beside a SHA-256 manifest under a new dated evidence directory; existing `qa_live_2026-10-25/` is read-only.

## 8. Entry / exit criteria

*Phase 2 exit (this document set):* register and report inspected; IDs and schema stable; every existing automated test and live check mapped (0 unmapped); gaps prioritised; defects/blockers/clarifications separated; execution plan sequenced; no code changed.

*Per-case exit:* PASS only if the observed outcome equals `expected`, every `db_invariants` row holds and every `negative_assertions` row holds, **and** the evidence file exists. A case with a non-empty `ambiguity` cannot go PASS until the question is answered in writing and recorded in the case.

*Release-readiness is not claimed* by this phase. See `QA_BASELINE_RESULTS.md` §6 for what is and is not known.

## 9. Maintenance

The catalogue is authored as code in [`qa_catalogue_src/`](qa_catalogue_src/) (`cases_1.py`…`cases_3.py` hold the cases; `qa_lib.py` the schema helper). To regenerate `QA_TEST_CASES.csv`, `QA_TEST_MAP.csv` and `QA_TRACEABILITY_MATRIX.md` after editing a case or adding tests:

```bash
cd docs/testing/qa_catalogue_src && PYTHONDONTWRITEBYTECODE=1 python3 gen.py && PYTHONDONTWRITEBYTECODE=1 python3 gen_md.py
```

It only reads the repository and writes those three files plus `stats.json`. Test files that match no case's `test_globs` appear as `UNMAPPED` in the map; that is the cue to add or extend a case. Executed results (`status`, `actual`, `evidence`) must be recorded by editing the case in `cases_*.py`, so they survive regeneration.

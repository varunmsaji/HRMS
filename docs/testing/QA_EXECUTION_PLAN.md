# HRMS QA Execution Plan

Date: 2026-10-25 · Companion to [`QA_TEST_STRATEGY.md`](QA_TEST_STRATEGY.md), [`QA_TEST_CASES.csv`](QA_TEST_CASES.csv), [`QA_DEFECT_REGISTER.md`](QA_DEFECT_REGISTER.md). **Nothing in this document has been executed except where stated in [`QA_BASELINE_RESULTS.md`](QA_BASELINE_RESULTS.md).** Every step that creates, restarts, installs, downloads or deletes anything is marked **[APPROVAL]** and must be approved by the owner first.

## 1. Sequenced batches

| Batch | Goal | Cases | Environment | Approvals | Exit criterion |
|---|---|---|---|---|---|
| **B0** | Inspect evidence, catalogue, read-only host facts, unit-tier re-baseline against unreachable DB/Redis | — | host, no services | none | This document set; `QA_BASELINE_RESULTS.md` §2 |
| **B1** | Private stack + harness with identity guard; clean-migration check; **K-1 reproduction**; first assertions on punch → daily result | `ENV-STACK-001`, `ENV-MIG-001`, `ATT-PUNCH-006`, `ATT-PUNCH-001…003`, `ATT-DAY-001…004` | Private stack | **A1** (isolated Postgres/Redis/MinIO containers on the non-root volume), disk headroom | Evidence directory with per-check request/response/DB rows; every B1 case has PASS/FAIL or a recorded clarification |
| **B2** | Attendance depth: regularization → recalculation, periods, locks, reconciliation invariant | `REG-*`, `PER-*`, `ATT-DAY-005…010`, `ATT-PUNCH-007/008` | Private stack | A1 | Summary reconciliation invariant checked for a mixed month |
| **B3** | Shifts, rosters, policies, overtime (the "NOT deep-tested" block) | `SHIFT-*`, `POL-*`, `OT-*` | Private stack | A1; CL-09, CL-10, CL-13 answers for expected values | Each documented-inert behaviour asserted as a no-op |
| **B4** | Leave depth + leave→attendance→period chain | `LEAVE-*`, `ATT-DAY-008`, `PER-WOL-001`, `PER-LOCKED-001` | Private stack | A1 | Ledger = balance after every scenario |
| **B5** | Payroll: independent oracle and full run to PAID | `PAYROLL-*` | Private stack (+ UNIT for oracle) | A1; **CL-04, CL-06 answers**; compliance-supplied statutory values | Oracle workbook committed with inputs/outputs; run reaches PAID with maker ≠ checker |
| **B6** | Platform console with approval ON; tenant-isolation sweep both token directions | `PLAT-*`, `TEN-*` | Private stack with `COMPANY_APPROVAL_REQUIRED=true` | A1 | Every lifecycle edge and illegal edge exercised |
| **B7** | Onboarding/employee lifecycle, documents, jobs (Beat on the private broker only) | `ONB-*`, `EMP-*`, `DOC-*`, `JOB-*` | Private stack + private worker/Beat | A1 | Exactly-once effects proven for each Beat task |
| **B8** | Web journeys + mobile | `WEB-*`, `MOB-*` | Browser + private stack; Flutter | **A2** (Flutter install), CL-23 | UI → API → DB trace per journey |
| **B9** | Closure: ESLint ratchet, CI parity, destructive-test guard, report | `ENV-*`, `WEB-LINT-001` | host | **A3** (tooling changes) | See §6 |

## 2. Cross-cutting rules for all batches

* **Run identity:** every run gets `RUN_ID=qa-YYYYMMDD-HHMM`; all resources carry it in names/labels (`hrms_qa_<RUN_ID>` DB, `qa.run=<RUN_ID>` container label, `qa-<RUN_ID>` bucket, Redis DB index recorded). Teardown only removes resources carrying that label.
* **Identity check before writes:** `SELECT current_database(), inet_server_addr(), inet_server_port(), current_user` must match the allow-list or the harness aborts.
* **Evidence per check:** `{case_id, step, request, response, db_rows_before/after, verdict, timestamp}` as JSON lines + a SHA-256 manifest. The 2026-10-25 directory stays read-only.
* **Oracle rule:** expected values for calculations are computed in a separate script from approved inputs (Python `Decimal`), committed before the system under test is run.
* **Time control:** use fixture dates in the past with explicit company timezone; never rely on "today"; run the attendance batches twice, `TZ=UTC` and `TZ=Asia/Kolkata`.
* **Stop conditions:** free space on `/` < 10 GiB, any identity mismatch, any connection to port 8000/5433 where the plan says private, any unexpected writes to `logs/`.

## 3. Deep-test plans for the prioritised gaps

Legend: **+** positive · **−** negative · **B** boundary · **P** permission · **I** state invariant · **C** concurrency · **E** environment. Authorities are named; unclear rules are *flagged to the owner* (CL-xx in the defect register), never filled in by the tester.

### 3.1 K-1 — mutable immutable-history tables (`ATT-PUNCH-006`)

* **Authority:** `Punch` model docstring (WD-11); decision status is ambiguous (CL-01).
* **Reproduce (read-only first):** (1) list every table whose model docstring/comments say "never UPDATE/DELETE/append-only" (`grep`), (2) query `has_table_privilege('hrms_app', t, 'UPDATE'|'DELETE'|'TRUNCATE')` for those tables, (3) one rolled-back `UPDATE … WHERE id=:one` on `punch` to confirm the privilege is real, not only catalog-reported. Expected today: all three tables writable by `hrms_app` (defect present); `leave_ledger`, `audit_log` etc. denied.
* **+** After an approved fix (outside this phase): intake (`/attendance/punches/me`, on-behalf, regularization approve, face punch if re-included), calculation, period close/reopen all still work.
* **−** UPDATE/DELETE/TRUNCATE as `hrms_app` → `permission denied`; as owner (migrations/test teardown) still allowed.
* **I:** punch count and content hash for a tenant unchanged by any API action other than insert.
* **E:** private DB only. Re-running `002_app_role.sh` on a throwaway DB shows privilege drift (`ENV-GRANT-001`) — never on the shared DB.
* **C:** n/a. **Open:** CL-01, CL-24 (retention purge path).

### 3.2 Shifts, rosters, policies, periods, overtime (`SHIFT-*`, `POL-*`, `PER-*`, `OT-*`)

* **Authority:** `ATTENDANCE_V1_COMPLETE.md` (§4–§14), `ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md`, `PAYROLL_BUSINESS_DECISIONS.md` (newer; wins on conflict — CL-10/11).
* **+** Fixed, flexible, split and cross-midnight shifts calculate expected status/minutes; roster publish changes schedule; policy precedence picks the most specific of the 8 levels (10 worked examples in V1 §9 become 10 cases); OT detected, capped, approved, frozen; period validate→finalize→CLOSED freezes summaries.
* **−** Overlapping shift versions/assignments/policy assignments rejected; edit of a published version refused; draft roster blocks finalize; pending regularization/OT block finalize; closed period refuses punches/recalc/roster/regularization/OT decision/leave sync.
* **B** Grace edge (exactly at grace, ±1 min), hour bands 239/240/479/480, OT threshold and daily/weekly/monthly caps ±1, duplicate-punch window ±1 s, midnight and DST-free zone boundaries, first/last day of period, joiner/leaver mid-period (`not_employed`).
* **P** Employee vs manager vs HR vs admin per endpoint (`UNLOCK` permission is stronger than lock).
* **I** Every calendar day in exactly one bucket; `Σ buckets = calendar days`; `paid + lop + unpaid_off = payable`; `attendance_day` carries the six version FKs; published versions immutable; GiST exclusion prevents overlap.
* **C** Concurrent roster update during regularization approval (V1 §5 edge 6, "not stress-tested"); parallel recalculation of the same day (`test_sweep_concurrency` exists); concurrent period close/reopen.
* **E** Private stack; clock control by fixture dates. **Documented inert settings** (rounding, auto-close, WFH/On-Duty, core hours, late-count, BY_GRADE) are asserted as *documented no-ops* and must not be filed as defects while the owner decision is pending.

### 3.3 Payroll calculations with independent oracle (`PAYROLL-CALC-*`, `PAYROLL-STAT-001`, `PAYROLL-TDS-001`)

* **Authority (approved):** BUS-001/002/003/011/016, D1–D11 in `00_PAYROLL_IMPLEMENTATION_PLAN.md` §8, PD-2/PD-4.
* **Oracle design:** a spreadsheet-free Python `Decimal` script implementing only the approved formulas: proration `salary × paid_days ÷ days_in_month`; OT `Basic ÷ (days × 8) × multiplier × hours`; encashment `Basic ÷ days × days`; daily wage `rate × paid_days`; PF 12 % of wages capped at ceiling, half-up rupee; ESI rounded up. Worked examples already in the cases: Basic 15,000.00, Oct (31 d): 26 paid days → 12,580.645161…; Feb-2026 (28 d) → 13,928.571428…; OT 3 h at 2.0× → 362.903226; 2 encashed days → 967.741935; daily wage 800 × 22 = 17,600.00; ESI wages 20,000 → employee 150, employer 650.
* **Blocked by clarification:** rounding point of prorated lines (CL-04), DA in OT base (CL-05), statutory and TDS expected values (CL-06). Until answered the oracle records both candidate roundings and the case stays `NOT_RUN`.
* **+** Month lengths 28/29/30/31; mid-month joiner and salary-change segments; holiday/weekly-off paid by pay-basis; half-day weekly off; approved OT by day class; encashment; arrears.
* **−** Un-closed period refused (PD-2); input changed after lock → `PAY_RUN_INPUTS_CHANGED`; `NEGATIVE_NET`, `STATUTORY_UNVERIFIED`, `SALARY_BASIS_MISMATCH`, `OT_MULTIPLIER_MISSING`, paid days > employed days (B02) rejected; reserved component codes (B03) refused.
* **B** Wages at PF/ESI ceiling −1/=/+1; variance exactly 15 %; employment of 1 day; leap February; zero-net.
* **P** HR maker vs finance checker (D9); EMPLOYEE sees only own finalised payslips; bank advice COMPANY_ADMIN only.
* **I** Run lines reproduce from the snapshot (pure function); finalised data immutable; one payslip per employee per run; arrears paid once.
* **C** Parallel finalise/approve; parallel adjustments with the same `Idempotency-Key`; parallel compute.
* **E** Oracle needs no infrastructure (UNIT); run lifecycle needs the private stack and a CLOSED period.

### 3.4 Platform console authorisation and tenant isolation (`PLAT-*`, `TEN-*`, `RBAC-*`)

* **Authority:** `docs/operations/PLATFORM_CONSOLE.md` (lifecycle table, token rules, audit rules).
* **+** Every edge of PENDING→TRIAL→ACTIVE↔SUSPENDED, REJECTED→TRIAL, TERMINATED with reasons and typed company name; plan/seat/trial operations; admin management.
* **−** Illegal edges refused; tenant token on every `/v1/platform` route and platform token on **every** tenant route (generate from OpenAPI, not 3 hand-picked GETs); disabling self / last admin; reused or revoked platform session; expired 30-min token.
* **B** Trial end-date day (reactivate returns TRIAL vs ACTIVE); 90-day retention date.
* **P** Matrix role × route generated from the OpenAPI for tenant roles; two-tenant read/write/transition for each resource family.
* **I** `platform_audit_log` row per action (append-only trigger for every role); company `audit_log` row `COMPANY_STATUS_CHANGED_BY_PLATFORM`; scheduled jobs skip non-TRIAL/ACTIVE.
* **C** Two platform admins acting on the same company; suspend during an in-flight tenant write.
* **E** Private stack with `COMPANY_APPROVAL_REQUIRED=true`; platform admin created by `scripts/create_platform_admin.py` against the **private** DB only.

### 3.5 Employee onboarding and lifecycle (`ONB-*`, `EMP-*`, `IMP-*`)

* **Authority:** `docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md`, `docs/modules/employee/*`.
* **+** Case → invite → public form → documents → submit → review → activate → employee + employment + optional login → first login → first punch; CSV import → same employee fields; employment change; termination sweep.
* **−** Expired/used/forged invite tokens; submit with missing sections; activation failure leaves no partial employee (`test_activation_failure_isolation`); duplicate employee code; invalid transitions; HR cannot approve own case.
* **B** Joining date today/past/future; probation end; max name lengths; CSV 0/1/max rows, BOM, CRLF.
* **P** HR vs manager vs employee; public token cannot reach authenticated routes; token not in logs (`test_token_path_redaction`).
* **I** One employee per activated case; PII columns encrypted; audit rows present for each mutation.
* **C** Double-click submit/activate; two HR users reviewing the same case; duplicate import batches.
* **E** Private stack + browser for the wizard; CL-19 (pay_basis collection) decides expected form fields.

### 3.6 Attendance punch → daily summary → regularization (`ATT-PUNCH-*`, `ATT-DAY-*`, `REG-*`)

* **Authority:** V1 §8–§12; `ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md` for business date.
* **+** Normal day; late within/beyond grace; early out; half-day by bands; multi-pair days (sum vs first/last); break deduction when a punch gap exists; holiday/weekly-off/special working day; night shift; leave overlay; regularization of missing punch → recalculated day.
* **−** Missing punch → INCOMPLETE; client-supplied time ignored; duplicate within window; future/employment-boundary punches; regularization beyond window/limit/disallowed type; self-approval.
* **B** See 3.2 plus punch exactly at midnight local, 23:59:59/00:00:00 across zones.
* **P** Self vs on-behalf; manager scope (PD-APR-1: manager *as of the attendance date*).
* **I** Raw punches never change; `attendance_day` deterministic function of punches + versions; engine version recorded; locked days untouched.
* **C** Parallel same-key punches (live `ATT-13` passes, inherited); recalculation during approval.
* **E** Private stack, two host timezones.

### 3.7 Leave application → approval/rejection → ledger/balance (`LEAVE-*`)

* **Authority:** `PAYROLL_BUSINESS_DECISIONS.md` BUS-004/005/006/013/014; `LEAVE_MODULE_AUDIT.md`; `LEAVE_POLICY_PRECEDENCE.md`.
* **+** AUTO, MANAGER, HR, HOD chains; half-day; multi-day spanning weekly off/holiday (sandwich rule on/off); accrual; year-end CL lapse / SL,EL carry-forward cap / encashment; comp-off credit and expiry; encashment.
* **−** Overlap, over-balance (negative allowed only with floor), probation/statutory-minimum rules, reason-required, closed period (PD-3), self-approval, wrong-tenant, cancel authority (BUS-004), double approve/cancel.
* **B** Balance exactly equals request; 0.5-day remainder; floor −3 for SL; year boundary; 1 day before/after joining date.
* **I** `balance == Σ ledger` after every step; ledger append-only; reserved vs available balance for PENDING (fix `LV-28`); restore exactly once on cancel.
* **C** N parallel applications vs one balance (live `LV-17/18`); approval racing cancellation; accrual running twice.
* **E** Private stack. CL-03 (weekly-off application behaviour), CL-25 (LOP split).

### 3.8 Document upload/retrieval and cross-tenant denial (`DOC-*`)

* **+** Valid PDF/PNG/JPG; presigned download returns identical bytes (SHA-256).
* **−** Executable/HTML disguised, empty, oversize (limit from `Settings`), double extension, traversal filename, other tenant's document id, expired/reused presigned URL, deleted document.
* **P** HR vs employee (own docs only) vs manager; onboarding token scope.
* **I** Rejected upload → 0 DB rows, 0 storage objects; object key prefixed by tenant; metadata hash equals stored object.
* **C** Parallel uploads of same filename; delete during download.
* **E** **Private MinIO only** (data on the non-root volume); storage-outage case (`DEP-01…03`) via an unreachable endpoint, never by stopping the shared container.

### 3.9 Background tasks, retries, idempotency, persisted results (`JOB-*`, `IMP-*`)

* **Authority:** `core/celery_app.py` Beat schedule (10 entries), `OBSERVABILITY_RUNBOOK.md`.
* **+** Each registered task run twice on the same worker process (DEF-02 regression), with concurrency 1 and 2; result persisted (import batch, accrual ledger rows, attendance days, reminders sent to the logging sender).
* **−** Task exception → structured failure log, bounded retries, no partial state; broker restart; worker kill mid-task (message re-delivered once; effect applied once).
* **I** Re-running accrual/year-end/termination/comp-off expiry/attendance sweeps changes nothing the second time; no `PENDING`/`PROCESSING` batch left stuck (`ops/import_backlog`).
* **C** Same task for same company dispatched twice concurrently (advisory locks).
* **E** Private broker DB and **private worker and Beat**. Beat is started only against the private broker with a clock-controlled schedule; never against shared Redis.

### 3.10 Web workflows and Flutter mobile (`WEB-*`, `MOB-*`)

* **+** Register → verify → login → setup wizard → employee create → leave apply → punch → regularize → payroll view (web); login → punch → leave → payslip (mobile) against the private API.
* **−** Server 4xx/5xx/offline: error banners, no duplicate submit (idempotency headers present on the four money endpoints), session expiry → login redirect.
* **B** Long names, RTL/Unicode, narrow viewport (375 px), pagination edges.
* **P** UI hides/denies what the API denies (EMPLOYEE cannot see payroll config).
* **I** UI numbers equal API numbers equal DB for balance, paid days, net pay.
* **E** Built-in browser against the private stack; Flutter 3.29.2 in isolation; `HRMS_LIVE_API=1` live test pointed to the private API only. Static contract scans (`coverage.py`) re-run and committed with inputs.

### 3.11 Shared-container restart test (`ENV-MINIO-001`)

* **Plan:** treat as `destructive`. Run only against a **private** MinIO container created by the harness, injecting its name through an env var (requires the test-infrastructure change in §6, item 4). On the shared stack it stays deselected: `--deselect tests/integration/core/test_storage.py::test_object_survives_a_minio_container_restart`.
* **+** Object written, container restarted, object readable and bytes equal. **−** Container absent → skip, not fail. **I** Volume data intact; no other container touched (`docker ps` before/after identical except the private one).

### 3.12 Clean-environment migration and reproducibility (`ENV-MIG-001`, `ENV-STACK-001`)

* **+** Empty private Postgres + `001_extensions.sql` + `002_app_role.sh` (once) → `alembic upgrade head` → single head `20261022090000`; 121 revision files; RLS enabled and forced on every `company_id` table; `hrms_app` NOSUPERUSER/NOBYPASSRLS; full suite subset green.
* **−** `alembic upgrade` twice (idempotent no-op); `alembic downgrade -1` where supported on a copy; second `002_app_role.sh` run on a copy to measure privilege drift (`ENV-GRANT-001`).
* **I** `alembic check` (model/migration drift) result recorded; list of tables without RLS compared with the allow-list (account-invite intentionally has none).
* **Pre-check (migration docstring):** `20261004104000` stops if a company has periods and zero/several legal entities — relevant when restoring any real snapshot (not done here).
* **E** Throwaway database in an isolated Postgres container on the non-root volume.

## 4. Per-batch deliverables

Each batch updates, in place: `QA_TEST_CASES.csv` (`status`, `actual`, `evidence`, `defect_ref`), `QA_BASELINE_RESULTS.md` (new section), `QA_DEFECT_REGISTER.md` (new defects/clarifications). No new documents.

## 5. Dependency map for starting each batch

`B1` needs A1 + ≥ 10 GiB free on `/` (or confirmation that image pulls are unnecessary and all writes go to `/media/varun/varun12`). `B3`/`B5` need the owner's answers CL-04…CL-10. `B6` needs the platform admin script run on the private DB. `B8` needs A2 and CL-23.

## 6. Environment and tooling remediation plan (approval-gated; none performed)

| # | Problem (class) | Proposed action | Risk | Approval | Verification | Rollback |
|---|---|---|---|---|---|---|
| 1 | Root `/` 100 % full, 5.0 GB free (VERIFIED) | (a) **Read-only inventory** first: `df -h`, `du -xh --max-depth=2` for `/var/lib/docker`, `/var/log`, `~/.cache`, snap, journal; `docker system df` (read-only). (b) Produce a ranked table of candidates with owner and age. (c) The owner decides. (d) Prefer *moving* (e.g., relocating Docker data-root or specific volumes to `/media/varun/varun12`, which has 193 GB free) over deleting. (e) Add a disk-space alert at 85 % | Moving volumes requires stopping containers; mistakes lose dev data | **A4** per action, with exact paths | `df` before/after; containers healthy; `restart` counts | Keep original until new location verified; copy then switch, never `mv` first |
| 2 | Test storage shares dev MinIO/bucket (VERIFIED, documented) | Private MinIO container (own port, own credentials, data dir on `/media/varun/varun12/qa/`), per-run bucket name | Low | A1 | `mc ls` of private vs dev bucket; dev bucket untouched | `docker rm -f` of the labelled container and removal of the labelled directory only |
| 3 | Infrastructure not safe to run repeatedly (VERIFIED: hard-coded paths) | Harness `qa/run.sh` (new, outside application code) that creates, labels, runs, and tears down with run id; refuses unlabelled targets | Low | A1 | Run twice back-to-back; second run starts from zero | Teardown is the rollback |
| 4 | Destructive tests not opt-in (VERIFIED) | In test infrastructure only: register a pytest marker `destructive`, skip unless `HRMS_TEST_ALLOW_DESTRUCTIVE=1` **and** `HRMS_TEST_MINIO_CONTAINER` is set; in `tests/conftest.py` refuse to run if `DATABASE_URL`'s database name is not on an allow-list (`*_test`, `hrms_qa_*`). No business code change | Could break developers' habit of raw `pytest` (that habit currently risks `hrms_dev`) | **A3** | Run suite with/without flags; confirm skip reasons | Revert the two test-config files |
| 5 | Stale shebangs in `.venv` (VERIFIED) | Create a *new* venv beside the old one from `uv.lock` with `uv sync --frozen` (no upgrades), verify `pytest`, `ruff`, `mypy`, `lint-imports`, then switch | Needs network or a warm uv cache; ~1 GB; disk | **A3** | `head -1 .venv/bin/pytest` points to existing interpreter; `uv pip list` equals lock | Keep the old venv until the new one passes the unit tier |
| 6 | Flutter missing (VERIFIED) | Install pinned **3.29.2** into `/media/varun/varun12/tools/flutter-3.29.2` (verify checksum; download size to be stated before downloading) or use a container image; `PUB_CACHE` on the same volume; run `flutter pub get`, `analyze`, `test` | Large download; first `pub get` hits the network | **A2** (state URL and size) | `flutter --version`; `flutter test` count equals 278 static blocks (± expansions) | Delete the dedicated tools directory |
| 7 | Web ESLint backlog: 110 errors (INHERITED) | Capture a JSON baseline; group by rule and file; fix by hand in small PRs with tests (the 97 `set-state-in-effect` errors each need design review — derive state, key on props, or move to event handlers); add a **ratchet** (count must not rise) to CI; keep the step non-blocking until zero. **No `--fix`, no mass rewrite** | Behavioural regressions from effect refactors | **A3** per PR | Vitest 522 + browser journeys unchanged | Revert the PR |
| 8 | CI vs tested environment parity (VERIFIED partial) | Single `scripts/ci_local.sh` mirroring `ci.yml` steps; pin Python 3.12 (`.python-version`); compare `uv.lock` with the venv; record Node/Flutter versions; run the exact CI commands in B9 and attach the diff of results | Low | A3 | CI-local equals CI | Remove script |

Approval keys: **A1** private stack containers/dirs on the non-root volume · **A2** Flutter download/install · **A3** test-infrastructure/tooling file changes (no application code) · **A4** any disk movement or removal.

## 7. B1 - EXECUTED 2026-10-25 under conditional approval (results: QA_BASELINE_RESULTS.md sections 15-17). Original request text kept below for history

Status: preflight passed, harness written (`docs/testing/qa_harness/`), safety fixes F1-F3 applied and verified where verifiable, **B1 not executed** because it needs infrastructure creation (approval **A1**).

Deviation from section 5: the root-disk headroom gate was **3 GiB** (currently 5.4 GiB), not 10 GiB. Reason: with data directories on `/media/varun/varun12`, Redis in tmpfs, `--log-opt max-size=5m` and images already present locally (no pull), B1 writes only a few MB to `/`. The QA volume gate is 20 GiB (193 GiB free). Tell me if you want the stricter 10 GiB gate; B1 would then stay blocked until the root disk is freed.

**The exact A1 command list and its review are now in [`QA_A1_SAFETY_REVIEW.md`](QA_A1_SAFETY_REVIEW.md) section 5 (harness v2: loopback-only namespace, strict guard, disposable DB marker); the block below is the earlier v1 list kept for history and is superseded.** Previously requested actions (all labelled `qa.run=b1-20261025a`, `qa.disposable=true`; nothing shared is touched; no image pulls):

```bash
H=docs/testing/qa_harness/stack.sh; RUN=b1-20261025a
$H up $RUN        # creates: docker network qa-net-$RUN (--internal); containers qa-$RUN-pg (postgres:16-alpine), qa-$RUN-redis (redis:7-alpine, no persistence), qa-$RUN-minio (pgsty/silo); bucket via pgsty/mc; dirs under /media/varun/varun12/work/staff-spectrum/qa_runs/$RUN/
$H guard $RUN     # proves isolation from inside the runner (writes artifacts/preflight_isolation.json); STOP if it prints NOT PROVED
$H migrate $RUN                                  # ENV-MIG-001 (alembic heads/upgrade/current on the disposable DB only)
$H py $RUN /qa/b1/k1_privileges.py after-migrate # ATT-PUNCH-006 / TEN-RLS-002 observed matrix
$H pytest $RUN tests/unit/test_isolation_guard.py -q
$H pytest $RUN tests/security/test_rls_runtime_role.py -q                                                           # TEN-RLS-001
$H pytest $RUN tests/integration/core/test_runtime_role_grants.py tests/integration/modules/payroll/test_b05_db_immutability.py -q   # TEN-RLS-002
$H pytest $RUN /qa/b1/test_b1_attendance.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q   # ATT-PUNCH-001..003, ATT-DAY-001..004
# K-1 experiments, last, because they change the disposable DB's grants:
$H usage-probe-install $RUN   # triggers that LOG UPDATE/DELETE/TRUNCATE reaching the three tables
$H pytest $RUN tests/integration/modules/attendance -q      # exercises punch/regularization/period code paths (face tests included in that directory; no external provider is configured)
$H usage-probe-report $RUN
$H rerun-role-script $RUN && $H py $RUN /qa/b1/k1_privileges.py after-rerun
$H down $RUN --confirm        # removes ONLY qa.run=$RUN containers/network and the pgdata/minio dirs (via a throwaway alpine container); artifacts are kept
```

Stop conditions: `guard` not PROVED; any container name/port already in use; free space on `/` < 3 GiB or on the QA volume < 20 GiB; any step touching a name that does not start with `qa-`.

Then, in order: ENV-STACK-001 second `up`/`down` cycle for repeatability; update `QA_TEST_CASES.csv` results via `qa_catalogue_src/results_phase3.py`.

## 8. Recommended batch after B1

B2 (REG-FLOW, PER-*, ATT-DAY-005…010) on the same stack; in parallel, once CL-04/05/06 are answered, the payroll oracle (B5) which needs no infrastructure.


## 9. After B1 - recommended next steps (B2 not started; awaiting go-ahead)

1. Decide K-1 (CL-01, CL-24); optionally authorise the usage probe (`usage-probe-install` + attendance suites) to prove whether the application ever needs UPDATE/DELETE on the three tables, and, separately, the `002_app_role.sh` rerun measurement.
2. B2 on a new RUN_ID with the same harness: `REG-FLOW-*`, `PER-*`, `ATT-DAY-005…010`, `ATT-PUNCH-007/008`; answer CL-16 items first (09:15 grace edge, unpunched working day lop 0.00 before close).
3. Commit decisions for the uncommitted harness/test-infrastructure changes are yours.


## 10. B2 executed; next

B2 executed 2026-10-25 (QA_BASELINE_RESULTS §18-23). Harness gained `stats-snapshot` (read-only), a gate on the DDL probe, and `/qa/b2` mount. **Not started without separate approval:** `002_app_role.sh` rerun, any grant change, the DDL usage probe (`--authorise-schema-change`), the full regression suite. Recommended B3 (own approval of scope): `ATT-PUNCH-007` (timezone), `SHIFT-*`, `POL-*`, `OT-*` once CL-09/10/13 are answered; payroll oracle B5 once CL-04/05/06 are answered.


## 11. B3 executed; what remains

B3 (policy precedence, effective dating, shift-version timezone, roster, overtime detection/approval) executed 2026-10-26: see QA_BASELINE_RESULTS §24-25. **Remaining, in recommended order:** B4 leave depth (ledger/balance/approval/race, needs own scope approval); B5 payroll oracle (blocked on CL-04/05/06); B6 platform console with approval ON; B7 onboarding/employee lifecycle/documents/Beat jobs; B8 web/mobile (Flutter install, browser); B9 closure (ESLint ratchet, CI parity, venv). Still needing separate approval: role-script rerun, grant changes, DDL usage probe, full regression suite. Product decisions needed: K-1 REVOKE (CL-01/24), OPEN-1/OPEN-2 (CL-16), CL-04..10, CL-13, CL-17.

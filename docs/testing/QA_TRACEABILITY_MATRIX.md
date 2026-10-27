# HRMS QA Traceability Matrix

Generated 2026-10-25 by `qa_catalogue_src/gen.py` + `gen_md.py` from `QA_TEST_CASES.csv` (192 cases) and `QA_TEST_MAP.csv` (2,963 mapped checks). Evidence classes: VERIFIED / INHERITED / INFERRED / BLOCKED / UNKNOWN as defined in [`QA_TEST_STRATEGY.md`](QA_TEST_STRATEGY.md) §2.

## A. Inspection of the live register (VERIFIED)

| Item | Finding |
|---|---|
| File | `docs/testing/qa_live_2026-10-25/register.csv` (13,829 bytes) |
| Schema | 4 columns: `id`, `check`, `status`, `detail_if_not_pass`. **No column for evidence path, script, assertion text, timestamp or run id.** |
| Rows | 216 data rows (+ header); all rows have exactly 4 fields |
| Duplicate IDs | 0 |
| Missing fields | `id`, `check`, `status` never empty. `detail_if_not_pass` is empty for 215 rows by design; the one non-empty value is `10.00` on `LV-28` (INFO) — the FAIL row `ATT-15` has an **empty** detail |
| Status values | PASS 214 · INFO 1 (`LV-28`) · FAIL 1 (`ATT-15`) |
| Prefix counts | LV 41 · AUTH 32 · PAY 26 · RBAC 16 · REG 15 · ATT 14 · EMP 13 · JOB 12 · SWP 11 · TEN 10 · DOC 9 · DEP 9 · RLS 7 · AUD 1 |
| ID gaps | `ATT-04` is absent. The script (`j4_att.py:11`) prints it as an `INFO` line only; its outcome (second IN with a new key inside the duplicate window) was never recorded |
| Evidence references | **None in the register.** IDs can be traced to scripts only by searching the script text: 214 IDs appear as literals in the 12 scripts; `SWP-02/03` are generated in a loop (`j9_sweep.py`); `DEP-00` and all others resolve. Mapping to scripts is in `QA_TEST_MAP.csv` (`file` column) |
| Raw outputs | The scripts write `j*.json` result files and read `api.log` from their own directory (`qa.py:save`, `qa.py:LOG`). **None of those files exist in the evidence directory.** Only the final CSV and the scripts were kept, so individual responses and DB rows behind each PASS cannot be audited |
| Re-runnability | `start_qa.sh` / `start_b.sh` hard-code `SP=/tmp/claude-1000/…/cec29e6e-…/scratchpad` (a previous session's directory) and source `qa_env.sh` from there; `coverage.py` needs a path argument and relative `web/` `mobile/` dirs. The scripts are therefore **not re-runnable as committed** |
| Git state | `FUNCTIONAL_QA_REPORT_2026-10-25.md` and `qa_live_2026-10-25/` are **untracked** (`git status`). The only copy of the audit evidence is the working tree; do not clean or `git stash -u`. |
| Report completeness | All 13 numbered sections plus the file list were present (170 lines); nothing was missing and nothing was invented |

## B. Coverage summary — with denominators

| Measure | Value | Denominator / note |
|---|---|---|
| Catalogue cases | 192 | counted by `C()` entries in the generator = rows in `QA_TEST_CASES.csv` |
| …of which executable (non-`NOT_APPLICABLE`) | 185 | 7 are `NOT_APPLICABLE` (face exclusion, 4 unimplemented features, 2 missing UIs; see §H) |
| Executable cases with ≥1 live check | 66 (35 %) | of 185 |
| Executable cases with ≥1 automated test file linked | 164 (88 %) | of 185 |
| Executable cases with either | 166 (89 %) | of 185 |
| Executable cases with both | 64 | |
| Executable cases with neither | 19 | all are environment/tooling cases, static or build web/mobile checks, or the two requirement gaps `SHIFT-ROSTER-002`, `OT-ELIG-001` (list below) |
| Backend test functions | 2661 in 265 files (AST count of `def test_*`) | pytest collects more *items* because 107 functions are parametrized: VERIFIED from the runner's own XML (`test-results/unit.xml` 1,354 unit items; `integration-security.xml` 1,839 items, 38 failures — the pre-fix baseline). The report's "unit 1063 PASS" equals the unit *function* count, not the 1,354 executed items |
| Backend by tier (functions) | unit 1075 · integration 1556 · security 30 | function counts, not executed items |
| Web | 64 files, 514 `it/test` blocks (static) | report: 522 passed (the 8 difference is `it.each`/dynamic expansion — not verified) |
| Mobile | 34 files, 278 `test/testWidgets` (static) | never executed (Flutter absent) |
| Unmapped checks | 0 of 2,963 map rows | every test/check links to ≥1 case; this is *linkage*, not correctness |

Executable cases with neither a live check nor an automated test: `SHIFT-ROSTER-002`, `OT-ELIG-001`, `WEB-CONTRACT-001`, `WEB-BUILD-001`, `WEB-LINT-001`, `WEB-A11Y-001`, `MOB-RUN-001`, `MOB-CONTRACT-002`, `ENV-DISK-001`, `ENV-VENV-001`, `ENV-ISOL-001`, `ENV-ISOL-002`, `ENV-MINIO-001`, `ENV-GRANT-001`, `ENV-MIG-001`, `ENV-CI-001`, `ENV-FLUTTER-001`, `ENV-STACK-001`, `ENV-LOGS-001`.

### What these numbers do **not** say

* A linked test file may exercise only one scenario of a case. Example: `PAYROLL-CALC-001` links `test_engine.py`, but whether it asserts calendar-day proration for 28/29/30/31-day months is unknown until read.
* By syntactic heuristic, 266 of the 1586 integration/security functions assert **only** HTTP status codes; 31 have no `assert` (they rely on `pytest.raises`/helpers). These classifications are INFERRED.
* Of the 216 live checks, 72 were classed (by keyword; INFERRED) as asserting business/state outcomes, 143 as technical or security responses, 1 as vacuous.

## C. Case → evidence trace

`Live` = register rows (INHERITED results). `Files`/`Fns` = automated test files linked, and the **total** `def test_` functions in those whole files (not only the ones relevant to the case), linked through the case's globs (INHERITED as part of the 3,198-pass run; not re-run). `Status` is this phase's verified status.

### Auth

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `AUTH-LOGIN-001` | P0 | Login + cookie | AUTH-06 | 2 | 16 | PASS | PASS |  |  |
| `AUTH-LOGIN-002` | P0 | Login gate: unverified email | AUTH-01 | 1 | 10 | PASS | PASS |  |  |
| `AUTH-LOGIN-003` | P0 | No user enumeration | AUTH-07, AUTH-22 | 1 | 8 | PASS | PASS |  | yes |
| `AUTH-LOGIN-004` | P0 | Account lockout | AUTH-31…32 | 1 | 10 | PASS | PASS |  | yes |
| `AUTH-LOGIN-005` | P1 | Validation envelope | AUTH-29…30 | 1 | 10 | PASS | NOT_RUN |  |  |
| `AUTH-TOKEN-001` | P0 | Forged / tampered tokens | AUTH-08…14 | 1 | 8 | PASS | PASS |  |  |
| `AUTH-REFRESH-001` | P0 | Refresh rotation + reuse detection | AUTH-15…17 | 1 | 7 | PASS | PASS |  |  |
| `AUTH-LOGOUT-001` | P0 | Logout invalidates session | AUTH-18…21 | 1 | 12 | PASS | PASS |  |  |
| `AUTH-RESET-001` | P0 | Password reset happy path + single use | AUTH-22…28 | 1 | 8 | PASS | PASS |  |  |
| `AUTH-RESET-002` | P0 | Reset revokes all sessions | — | 1 | 8 | NONE | PASS |  | yes |
| `AUTH-VERIFY-001` | P0 | Email verification token | AUTH-02…05 | 1 | 10 | PASS | PASS |  |  |
| `AUTH-RATE-001` | P0 | Auth rate limiting | AUTH-31…32 | 4 | 23 | PASS | PASS |  |  |
| `AUTH-RATE-002` | P0 | Redis outage behaviour of auth | DEP-04…07 | 1 | 2 | PASS | BLOCKED |  | yes |
| `AUTH-INVITE-001` | P0 | Account invite accept | LV-22…25 | 4 | 47 | PASS | PASS |  |  |
| `AUTH-INVITE-002` | P2 | Mobile email deep links | — | 2 | 18 | NONE | NOT_RUN |  |  |
| `AUTH-LINK-001` | P0 | Employee login linked to employee record | LV-26 | 1 | 4 | PASS | PASS |  |  |

### Tenant isolation

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `TEN-ISO-001` | P0 | Employee cross-tenant access | TEN-01…05 | 2 | 21 | PASS | PASS |  |  |
| `TEN-ISO-002` | P0 | Cross-tenant on leave, payroll, imports, docs, punches, regularization | LV-31, LV-41; PAY-18…21; JOB-06; DOC-07…08; ATT-11…12; REG-15 | 1 | 6 | PASS | PASS |  | yes |
| `TEN-HDR-001` | P0 | Company header handling | TEN-06…09 | 1 | 5 | PASS | FAIL | DEF-B6-01 | yes |
| `TEN-LIST-001` | P0 | List endpoints disjoint across tenants | TEN-10 | 1 | 13 | PASS | PASS |  | yes |
| `TEN-RLS-001` | P0 | RLS as the real runtime role | RLS-01…05 | 1 | 4 | PASS | PASS |  |  |
| `TEN-RLS-002` | P0 | Runtime role privileges | RLS-06…07; LV-21 | 3 | 18 | PASS | PASS |  | yes |
| `TEN-DEL-001` | P2 | Tenant wipe helper safety | — | 1 | 3 | NONE | NOT_RUN |  | yes |

### RBAC

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `RBAC-ESS-001` | P0 | EMPLOYEE role write denials | RBAC-01, RBAC-04…06, RBAC-12…13 | 2 | 22 | PASS | PASS |  |  |
| `RBAC-ESS-002` | P0 | EMPLOYEE role read scope | RBAC-02…03, RBAC-07…11 | 2 | 28 | PASS | FAIL | DEF-B6-02 |  |
| `RBAC-ADM-001` | P0 | HR_ADMIN capabilities and ceiling | RBAC-15…16 | 1 | 12 | PASS | PASS |  | yes |
| `RBAC-MGR-001` | P0 | Manager data scope | — | 2 | 8 | NONE | FAIL | DEF-B6-02 (extended), DEF-B10-01 | yes |
| `RBAC-MATRIX-001` | P0 | Route authorization matrix | SWP-01 | 2 | 10 | PASS | PASS |  | yes |

### Organisation

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `ORG-REG-001` | P1 | Company registration | — | 6 | 26 | NONE | NOT_RUN |  |  |
| `ORG-STRUCT-001` | P2 | Branches, departments, designations, grades, legal entities | — | 12 | 165 | NONE | NOT_RUN |  |  |
| `ORG-PROFILE-001` | P2 | Company profile + setup progress + timezone guard | — | 5 | 55 | NONE | NOT_RUN |  | yes |
| `ORG-POLCAL-001` | P2 | Policy and calendar rules (org level) | — | 4 | 68 | NONE | NOT_RUN |  |  |
| `SUB-READ-001` | P2 | Subscription read-only summary | — | 2 | 17 | NONE | NOT_RUN |  | yes |
| `PAGE-001` | P1 | Pagination contract | EMP-07…09 | 9 | 51 | PASS | NOT_RUN |  | yes |
| `CONC-IFMATCH-001` | P1 | Optimistic concurrency (ETag / If-Match) | EMP-10…13; LV-16, LV-36; PAY-11 | 1 | 2 | PASS | NOT_RUN |  | yes |
| `API-CONTRACT-001` | P1 | Core API contract & robustness | SWP-02…11 | 4 | 16 | PASS | NOT_RUN |  | yes |

### Employee

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `EMP-CRUD-001` | P1 | Create employee | EMP-01, EMP-04…06 | 4 | 44 | PASS | NOT_RUN |  |  |
| `EMP-IDEM-001` | P1 | Employee create idempotency | EMP-02…03 | 1 | 3 | PASS | NOT_RUN | OBS-IDEM-01 | yes |
| `EMP-LIFE-001` | P1 | Lifecycle and concurrency | — | 4 | 33 | NONE | NOT_RUN |  |  |
| `EMP-EMPLOY-001` | P0 | Employment / assignment / effective dating | — | 13 | 303 | NONE | NOT_RUN |  | yes |
| `EMP-PII-001` | P0 | PII field encryption | — | 4 | 37 | NONE | NOT_RUN |  |  |
| `ONB-FLOW-001` | P0 | Full onboarding: case -> invite -> public submit -> review -> activate | — | 7 | 57 | NONE | NOT_RUN |  | yes |
| `ONB-DOC-001` | P1 | Onboarding document upload bounds | — | 5 | 62 | NONE | NOT_RUN |  |  |
| `ONB-EMAIL-001` | P2 | Onboarding email sending + failure classification | — | 2 | 42 | NONE | NOT_RUN |  |  |

### Employee import

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `IMP-CSV-001` | P1 | CSV import round trip via real worker | JOB-01…05 | 2 | 19 | PASS | NOT_RUN |  |  |
| `IMP-VAL-001` | P1 | Upload validation | JOB-07…08 | 1 | 5 | PASS | NOT_RUN | DEF-03 |  |
| `IMP-IDEM-001` | P1 | Import idempotency & backlog reconciliation | JOB-10…12 | 3 | 14 | PASS | NOT_RUN |  |  |
| `IMP-OUTAGE-001` | P1 | Worker down / killed | JOB-09…11 | 0 | 0 | PASS | NOT_RUN |  |  |
| `IMP-UI-001` | P2 | Import UI | — | 0 | 0 | NONE | NOT_APPLICABLE |  | yes |

### Documents

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `DOC-UP-001` | P0 | Upload validation | DOC-01…06 | 3 | 34 | PASS | PASS |  |  |
| `DOC-XT-001` | P0 | Cross-tenant document denial | DOC-07…08 | 1 | 15 | PASS | PASS |  | yes |
| `DOC-DL-001` | P1 | Presigned download | DOC-09 | 0 | 0 | PASS | PASS |  | yes |
| `DOC-STORE-001` | P0 | Storage failure behaviour | DEP-00…03, DEP-08 | 3 | 18 | PASS | FAIL | DEF-B7-01 | yes |

### Attendance

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `ATT-PUNCH-001` | P0 | Self punch | ATT-01, ATT-05…06 | 2 | 16 | PASS | PASS |  |  |
| `ATT-PUNCH-002` | P0 | Punch idempotency | ATT-02…03, ATT-13…14 | 1 | 2 | PASS | PASS |  |  |
| `ATT-PUNCH-003` | P0 | Duplicate-punch window | — | 1 | 74 | NONE | PASS |  | yes |
| `ATT-PUNCH-004` | P0 | On-behalf punch (admin) | ATT-07…10 | 2 | 16 | PASS | NOT_RUN |  |  |
| `ATT-PUNCH-005` | P0 | Punch cross-tenant | ATT-11…12 | 1 | 14 | PASS | NOT_RUN |  |  |
| `ATT-PUNCH-006` | P0 | Punch immutability (K-1) | ATT-15 | 1 | 4 | FAIL | FAIL | K-1 (confirmed) | yes |
| `ATT-PUNCH-007` | P0 | Business-date & timezone of a punch | — | 3 | 20 | NONE | PASS |  | yes |
| `ATT-PUNCH-008` | P1 | Punch after last working day / outside employment | — | 2 | 7 | NONE | PASS |  |  |

### Attendance calc

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `ATT-DAY-001` | P0 | Punch to daily summary: normal present day | — | 3 | 95 | NONE | PASS |  | yes |
| `ATT-DAY-002` | P0 | Late arrival grace and bands | — | 2 | 77 | NONE | PASS |  | yes |
| `ATT-DAY-003` | P0 | Hour-based bands | — | 2 | 84 | NONE | PASS |  |  |
| `ATT-DAY-004` | P0 | Missing punch handling | — | 3 | 78 | NONE | PASS |  | yes |
| `ATT-DAY-005` | P0 | Day types: holiday, weekly off, special working day | — | 4 | 65 | NONE | PASS |  | yes |
| `ATT-DAY-006` | P0 | Night / cross-midnight shift | — | 2 | 12 | NONE | PASS |  | yes |
| `ATT-DAY-007` | P0 | Recalculation idempotence & engine version | — | 4 | 13 | NONE | PASS |  |  |
| `ATT-DAY-008` | P0 | Leave overlay on the day | — | 2 | 35 | NONE | PASS |  | yes |
| `ATT-DAY-009` | P0 | Employment boundary days | — | 2 | 29 | NONE | PASS |  |  |
| `ATT-DAY-010` | P2 | Orphan attendance report | — | 1 | 3 | NONE | PASS |  |  |

### Attendance regularization

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `REG-FLOW-001` | P0 | Request -> approve -> punches written once | REG-01…02, REG-06…09 | 1 | 25 | PASS | PASS |  | yes |
| `REG-FLOW-002` | P0 | Reject path | REG-10…12 | 1 | 25 | PASS | PASS |  |  |
| `REG-VAL-001` | P0 | Request validation | REG-03…04, REG-13 | 1 | 25 | PASS | PASS |  |  |
| `REG-AUTHZ-001` | P0 | Authorization | REG-05, REG-14…15 | 1 | 14 | PASS | PASS |  |  |
| `REG-POL-001` | P0 | Regularization policy limits | — | 1 | 3 | NONE | PASS |  | yes |
| `REG-LOCK-001` | P0 | Regularization on locked period | — | 2 | 29 | NONE | PASS |  |  |

### Shifts & rosters

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `SHIFT-DEF-001` | P1 | Shift definition & versioning | — | 4 | 81 | NONE | PASS |  |  |
| `SHIFT-ASSIGN-001` | P1 | Employee shift assignment | — | 1 | 40 | NONE | NOT_RUN |  | yes |
| `SHIFT-ROSTER-001` | P1 | Roster create/publish | — | 1 | 8 | NONE | PASS |  | yes |
| `SHIFT-ROSTER-002` | P2 | Bulk roster | — | 0 | 0 | NONE | NOT_RUN |  | yes |
| `SHIFT-FLEX-001` | P1 | Flexible / split shift behaviours | — | 1 | 74 | NONE | NOT_RUN |  | yes |

### Attendance policies

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `POL-RESOLVE-001` | P1 | 8-level policy precedence | — | 3 | 22 | NONE | PASS |  | yes |
| `POL-VERSION-001` | P1 | Effective-dated policy versions | — | 1 | 9 | NONE | PASS |  |  |
| `POL-INERT-001` | P1 | Inert settings hidden | — | 2 | 0 | NONE | NOT_RUN |  |  |

### Attendance periods

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `PER-LIFE-001` | P0 | Open -> validate -> finalize -> CLOSED | — | 3 | 51 | NONE | PASS |  |  |
| `PER-LE-001` | P0 | Per-legal-entity periods | — | 2 | 15 | NONE | PASS |  | yes |
| `PER-RECON-001` | P0 | Summary reconciliation invariant | — | 3 | 51 | NONE | PASS |  |  |
| `PER-LOCK-001` | P0 | Incomplete at close | — | 3 | 31 | NONE | PASS |  | yes |
| `PER-WOL-001` | P0 | Work on approved-leave day blocks close | — | 2 | 29 | NONE | PASS |  | yes |
| `PER-REOPEN-001` | P0 | Reopen semantics | — | 2 | 29 | NONE | PASS |  | yes |
| `PER-LOCKED-001` | P0 | Locked-date refusals | — | 3 | 33 | NONE | PASS |  |  |

### Overtime

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `OT-DETECT-001` | P1 | Detection, threshold, rounding, caps | — | 1 | 20 | NONE | PASS |  | yes |
| `OT-CLASS-001` | P1 | Day classification | — | 1 | 10 | NONE | NOT_RUN |  | yes |
| `OT-APPR-001` | P1 | Approval chain & frozen decisions | — | 1 | 3 | NONE | PASS |  |  |
| `OT-ELIG-001` | P1 | Eligibility 'by grade' | — | 0 | 0 | NONE | NOT_RUN |  | yes |
| `OT-LEAVE-001` | P0 | OT on full-day leave not payable | — | 2 | 35 | NONE | NOT_RUN |  |  |
| `OT-COMP-001` | P1 | Comp-off credit | — | 3 | 13 | NONE | NOT_RUN |  | yes |

### Background jobs

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `JOB-LOOP-001` | P0 | DB tasks across event loops (DEF-02) | — | 5 | 25 | NONE | PASS | DEF-02 (fix verified, uncommitted) |  |
| `JOB-BEAT-001` | P0 | Beat schedule maps to registered tasks | — | 2 | 5 | NONE | PASS |  | yes |
| `JOB-RETRY-001` | P0 | Retry, failure logging, lifecycle events | — | 4 | 10 | NONE | PASS |  | yes |
| `JOB-IDEM-001` | P0 | Task idempotency / exactly-once effects | — | 4 | 24 | NONE | PASS |  | yes |
| `JOB-HEALTH-001` | P0 | Job health & readiness | DEP-04…05 | 4 | 19 | PASS | PASS |  |  |

### Observability & core

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `OBS-LOG-001` | P1 | Structured logging & request context | — | 10 | 78 | NONE | NOT_RUN |  |  |
| `OBS-FILE-001` | P2 | File sinks, rotation, metrics | — | 7 | 72 | NONE | NOT_RUN |  |  |
| `OBS-AUDIT-001` | P0 | Audit trail & security events | AUD-01 | 3 | 13 | PASS | NOT_RUN |  | yes |
| `CFG-SET-001` | P1 | Settings guards & DB resilience | — | 8 | 55 | NONE | NOT_RUN |  |  |

### Leave

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `LEAVE-APPLY-001` | P0 | Apply (AUTO chain) debits balance | LV-01…03 | 1 | 22 | PASS | PASS |  |  |
| `LEAVE-APPLY-002` | P0 | Application idempotency | LV-04…05 | 1 | 20 | PASS | PASS |  |  |
| `LEAVE-APPLY-003` | P0 | Overlap and over-balance rejection | LV-06…09 | 2 | 7 | PASS | PASS |  |  |
| `LEAVE-APPLY-004` | P0 | Date validation & weekly-off handling | LV-10…11 | 2 | 27 | PASS | PASS |  | yes |
| `LEAVE-APPLY-005` | P1 | Leave rules: probation, statutory minimum, maternity, combination, type semantics | — | 6 | 42 | NONE | NOT_RUN |  | yes |
| `LEAVE-APPR-001` | P0 | HR-chain approval | LV-27…28, LV-32…36 | 2 | 27 | PASS_WITH_INFO | PASS |  | yes |
| `LEAVE-APPR-002` | P0 | Authorization of decisions | LV-29…31, LV-41 | 2 | 7 | PASS | PASS |  |  |
| `LEAVE-APPR-003` | P0 | Reject pending | LV-37…38 | 1 | 22 | PASS | PASS |  |  |
| `LEAVE-APPR-004` | P0 | Approval overdraw -> shortfall to LOP | — | 2 | 9 | NONE | PASS |  | yes |
| `LEAVE-CANCEL-001` | P0 | Cancel approved: restore once | LV-12…16 | 1 | 4 | PASS | PASS |  | yes |
| `LEAVE-CANCEL-002` | P0 | Cancel PENDING | LV-39…40 | 1 | 22 | PASS | PASS |  |  |
| `LEAVE-CONC-001` | P0 | Concurrent applications | LV-17…19 | 2 | 6 | PASS | PASS |  | yes |
| `LEAVE-LEDGER-001` | P0 | Ledger = balance invariant | LV-20…21 | 4 | 35 | PASS | PASS |  |  |
| `LEAVE-POL-001` | P1 | Leave policy versions & assignment | — | 3 | 34 | NONE | PASS |  | yes |
| `LEAVE-YEAR-001` | P0 | Accrual and year-end | — | 4 | 31 | NONE | PASS |  | yes |
| `LEAVE-ENC-001` | P0 | Encashment | — | 1 | 5 | NONE | PASS |  |  |
| `LEAVE-LOCK-001` | P0 | Leave vs closed attendance period | — | 1 | 4 | NONE | PASS |  |  |
| `LEAVE-COMP-001` | P0 | Comp-off lifecycle | — | 3 | 13 | NONE | NOT_RUN |  |  |

### Payroll

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `PAYROLL-FLOW-001` | P0 | Pay run state machine guards | PAY-01…08, PAY-10…11, PAY-24 | 1 | 7 | PASS | FAIL | DEF-B5A-01 |  |
| `PAYROLL-FLOW-002` | P0 | Lock inputs requires CLOSED period (PD-2) | PAY-09 | 1 | 7 | PASS | PASS |  |  |
| `PAYROLL-FLOW-003` | P0 | Full run to PAID (happy path) | — | 2 | 8 | NONE | PASS |  | yes |
| `PAYROLL-FLOW-004` | P0 | Maker-checker (D9) | — | 1 | 7 | NONE | PASS |  | yes |
| `PAYROLL-FLOW-005` | P0 | Inputs changed after lock (PD-4) | — | 2 | 16 | NONE | PASS |  |  |
| `PAYROLL-FLOW-006` | P0 | Variance gate (D10) | — | 1 | 7 | NONE | PASS |  | yes |
| `PAYROLL-FLOW-007` | P0 | Concurrency & atomicity of finalise | PAY-26 | 2 | 11 | PASS | PASS |  | yes |
| `PAYROLL-FLOW-008` | P0 | Finalised data immutability | — | 1 | 8 | NONE | PASS |  |  |
| `PAYROLL-AUTHZ-001` | P0 | Payroll authorization & tenancy | PAY-12…21 | 1 | 7 | PASS | PASS |  | yes |
| `PAYROLL-SLIP-001` | P0 | Payslip visibility | PAY-22…23 | 2 | 3 | PASS | PASS |  |  |
| `PAYROLL-ADJ-001` | P0 | Payroll adjustments | PAY-25…26 | 1 | 8 | PASS | PASS |  |  |
| `PAYROLL-ARR-001` | P0 | Arrears | — | 1 | 4 | NONE | NOT_RUN |  |  |
| `PAYROLL-CALC-001` | P0 | Proration by calendar days (BUS-016) - independent oracle | — | 2 | 44 | NONE | NOT_RUN |  | yes |
| `PAYROLL-CALC-002` | P0 | Month-length sensitivity | — | 1 | 37 | NONE | NOT_RUN |  | yes |
| `PAYROLL-CALC-003` | P0 | Joiner/leaver/segments | — | 2 | 59 | NONE | NOT_RUN |  |  |
| `PAYROLL-CALC-004` | P0 | Overtime pay (D3) | — | 2 | 47 | NONE | BLOCKED |  | yes |
| `PAYROLL-CALC-005` | P0 | Leave encashment (D4) | — | 2 | 42 | NONE | NOT_RUN |  |  |
| `PAYROLL-CALC-006` | P0 | Daily-wage employee (BUS-001/D5) | — | 2 | 44 | NONE | NOT_RUN |  |  |
| `PAYROLL-CALC-007` | P0 | Salary structure breakup (D1/D2) | — | 3 | 20 | NONE | NOT_RUN |  |  |
| `PAYROLL-STAT-001` | P0 | PF / ESI / PT / LWF engines | — | 2 | 14 | NONE | BLOCKED |  | yes |
| `PAYROLL-TDS-001` | P0 | Income tax (TDS), new regime | — | 2 | 12 | NONE | BLOCKED |  | yes |
| `PAYROLL-NET-001` | P0 | Net pay not rounded (D8); negative/zero net | — | 2 | 38 | NONE | NOT_RUN |  |  |
| `PAYROLL-BANK-001` | P0 | Bank advice CSV | — | 2 | 8 | NONE | PASS |  | yes |
| `PAYROLL-PIN-001` | P0 | Payroll vs attendance reconciliation | — | 1 | 1 | NONE | PASS |  |  |

### Platform console

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `PLAT-AUTHZ-001` | P0 | Token separation | RBAC-14 | 1 | 19 | PASS | PASS |  | yes |
| `PLAT-LIFE-001` | P0 | Company lifecycle state machine | — | 1 | 19 | NONE | PASS |  |  |
| `PLAT-ACCESS-001` | P0 | Status-based tenant access | — | 2 | 24 | NONE | PASS |  |  |
| `PLAT-AUDIT-001` | P0 | Platform audit log append-only | — | 2 | 23 | NONE | PASS |  | yes |
| `PLAT-ADMIN-001` | P0 | Platform admin management guards | — | 1 | 19 | NONE | FAIL | DEF-B6-03 | yes |
| `PLAT-SUB-001` | P0 | Plan / seat / trial operations | — | 1 | 19 | NONE | PASS |  | yes |
| `PLAT-LOG-001` | P0 | Log viewer | — | 1 | 5 | NONE | PASS |  |  |
| `PLAT-UI-001` | P0 | Platform console web pages | — | 1 | 0 | NONE | NOT_RUN |  | yes |

### Web

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `WEB-AUTH-001` | P0 | Register / verify / login UI | — | 6 | 0 | NONE | NOT_RUN |  | yes |
| `WEB-ATT-001` | P1 | Attendance screens (punch, days, periods, policies, shifts) | — | 21 | 0 | NONE | NOT_RUN |  |  |
| `WEB-LEAVE-001` | P0 | Leave application UI | — | 1 | 0 | NONE | NOT_RUN |  |  |
| `WEB-PAY-001` | P0 | Payroll UI | — | 5 | 0 | NONE | NOT_RUN |  |  |
| `WEB-ORG-001` | P2 | Organisation & setup UIs | — | 30 | 0 | NONE | NOT_RUN |  |  |
| `WEB-CONTRACT-001` | P1 | Static web->API contract | — | 0 | 0 | NONE | NOT_RUN |  | yes |
| `WEB-BUILD-001` | P1 | Production build | — | 0 | 0 | NONE | NOT_RUN |  | yes |
| `WEB-LINT-001` | P2 | ESLint backlog | — | 0 | 0 | NONE | NOT_RUN | TD-LINT-01 |  |
| `WEB-A11Y-001` | P2 | Accessibility & responsive layout | — | 0 | 0 | NONE | NOT_RUN |  | yes |
| `WEB-IMPORT-001` | P2 | Employee import UI | — | 0 | 0 | NONE | NOT_APPLICABLE |  |  |

### Mobile

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `MOB-RUN-001` | P0 | Flutter analyze + unit/widget tests | — | 0 | 0 | NONE | BLOCKED | ENV-BLK-FLUTTER |  |
| `MOB-AUTH-001` | P1 | Mobile auth & deep links | — | 3 | 0 | NONE | BLOCKED |  |  |
| `MOB-ATT-001` | P1 | Mobile attendance, regularization, rosters | — | 10 | 0 | NONE | BLOCKED |  |  |
| `MOB-LEAVE-001` | P0 | Mobile leave + Idempotency-Key | — | 3 | 0 | NONE | BLOCKED |  |  |
| `MOB-PAY-001` | P0 | Mobile payroll screens | — | 2 | 0 | NONE | BLOCKED |  |  |
| `MOB-ORG-001` | P2 | Mobile profile/onboarding/org/setup | — | 10 | 0 | NONE | BLOCKED |  |  |
| `MOB-CONTRACT-001` | P1 | Mobile contract fixtures + live contract test | — | 2 | 0 | NONE | BLOCKED | ENV-RISK-LIVEPORT (fix unvalidated) |  |
| `MOB-CONTRACT-002` | P1 | Static mobile->API contract | — | 0 | 0 | NONE | NOT_RUN |  |  |

### Environment & tooling

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `ENV-DISK-001` | P0 | Root partition capacity | — | 0 | 0 | NONE | FAIL | ENV-BLK-DISK |  |
| `ENV-VENV-001` | P1 | Stale virtual-environment shebangs | — | 0 | 0 | NONE | FAIL | ENV-BLK-SHEBANG |  |
| `ENV-ISOL-001` | P0 | Test suite default DB is the dev DB | — | 0 | 0 | NONE | PASS | ENV-RISK-DEVDB (fixed, uncommitted) |  |
| `ENV-ISOL-002` | P1 | Unit tier is not infrastructure-free | — | 0 | 0 | NONE | PASS | ENV-RISK-REDIS (fixed, uncommitted) |  |
| `ENV-ISOL-003` | P0 | Security RLS test hard-coded the shared dev database | — | 1 | 4 | NONE | PASS | ENV-RISK-HARDCODED-DEVDB (fixed, uncommitted, verified) |  |
| `ENV-MINIO-001` | P0 | Destructive MinIO restart test is on by default | — | 0 | 0 | NONE | PASS | ENV-RISK-RESTART (fixed, uncommitted) |  |
| `ENV-GRANT-001` | P0 | init script re-run undoes append-only REVOKEs | — | 0 | 0 | NONE | NOT_RUN | K-1-RELATED |  |
| `ENV-MIG-001` | P0 | Clean-environment migration reproducibility | — | 0 | 0 | NONE | PASS |  | yes |
| `ENV-CI-001` | P1 | CI vs local dependency parity | — | 0 | 0 | NONE | NOT_RUN |  |  |
| `ENV-FLUTTER-001` | P0 | Flutter toolchain | — | 0 | 0 | NONE | BLOCKED | ENV-BLK-FLUTTER |  |
| `ENV-STACK-001` | P1 | Private test stack repeatability | — | 0 | 0 | NONE | PASS | QA-EVID-01 |  |
| `ENV-LOGS-001` | P2 | Dev log/disk growth | — | 0 | 0 | NONE | NOT_RUN |  |  |

### Excluded / not implemented

| Case | Pri | Feature | Live checks | Files | Fns | Inherited | Status | Defect | Open question |
|---|---|---|---|---|---|---|---|---|---|
| `FACE-EXCL-001` | P2 | Face attendance (Face++/open-source, enrolment, liveness, punch) | — | 21 | 280 | NONE | NOT_APPLICABLE |  | yes |
| `REC-NI-001` | P2 | Recruitment, job postings, candidates | — | 0 | 0 | NONE | NOT_APPLICABLE |  |  |
| `AI-NI-001` | P2 | Resume processing / AI features | — | 0 | 0 | NONE | NOT_APPLICABLE |  |  |
| `BILL-NI-001` | P2 | Subscription payment / usage billing | — | 0 | 0 | NONE | NOT_APPLICABLE |  |  |
| `RPT-NI-001` | P2 | Reports/exports & rich notifications | — | 0 | 0 | NONE | NOT_APPLICABLE |  |  |

## D. Assessment of the live checks (assertion quality)

Found by reading the 12 scripts (VERIFIED):

| Check | Weakness |
|---|---|
| `LV-28` | VACUOUS (`or True` in j3_leave.py:61) - cannot fail |
| `ATT-15` | DESTRUCTIVE probe: unscoped UPDATE on punch inside a committing connection if it succeeds |
| `EMP-09` | DISJUNCTIVE (422 OR clamped) |
| `EMP-13` | DISJUNCTIVE (400/409/412/422/428) |
| `LV-11` | DISJUNCTIVE (rejected OR 0-day) |
| `TEN-08` | DISJUNCTIVE (200/400/403/422) |
| `AUTH-14` | DISJUNCTIVE (401 OR 403) |
| `DEP-07` | DISJUNCTIVE (200 OR 503) |
| `TEN-10` | VACUOUS-IF-EMPTY lists |
| `SWP-02` | TECHNICAL ONLY (no 5xx) |
| `SWP-03` | TECHNICAL ONLY (no 5xx) |
| `SWP-08` | TECHNICAL ONLY (no 5xx) |
| `SWP-09` | TECHNICAL ONLY (no 5xx) |
| `RLS-06` | READ-ONLY privilege smoke |
| `AUD-01` | WEAK: >=1 audit row containing 'EMPLOYEE' |

Further observations:

* **Attendance daily calculation is never asserted.** `j4_att.py:35-37` and `j5_reg.py:35` call `/attendance/days/calculate`, `/attendance/days` and the regularization recalculation and only `print('INFO …')` the response. The live pass therefore proves that punches are *stored*, not that they become the correct day status, worked minutes, late/early flags or overtime. `ATT-DAY-001…010` are the cases that close this.
* **Disjunctive expectations:** several checks accept any of 3–5 status codes (see table). They prove "not 500 and not a silent success" but not a specific contract.
* **`ATT-15` is destructive when the defect is present:** `cu.execute("update punch set direction='IN'")` has no `WHERE`; RLS scopes it to the tenant, and `with psycopg.connect(...)` commits on a clean exit. It ran on a private DB; re-running it elsewhere would rewrite punch history.
* **Mislabel:** the register calls the ATT-15 deferral "decision D11"; "D11" also names the *pay date* decision in `00_PAYROLL_IMPLEMENTATION_PLAN.md`. The immutability decision is the one in `OBSERVABILITY_ARCHITECTURE.md` §15. See defect register Part D.
* **Register is a summary, not evidence:** with no response bodies kept, a reviewer cannot tell a real PASS from a script that asserted the wrong thing.

## E. Overlapping and duplicate coverage

| Topic | Where it is covered more than once | Assessment |
|---|---|---|
| Cross-tenant denial | Live `TEN-*`, `LV-41`, `PAY-18…21`, `ATT-11/12`, `REG-15`, `DOC-07/08`, `JOB-06`; CI `test_cross_tenant_isolation`, `test_route_authorization_matrix`, `test_organisation_security`, `test_rls_runtime_role` | Heavy but valuable overlap for P0 isolation; retain. The live runs add the HTTP-level path with real headers |
| Append-only ledgers | Live `RLS-06/07`, `LV-21`; CI `test_runtime_role_grants`, `test_b05_db_immutability` | Duplicate privilege checks; CI version is the durable one, the live rows can be retired once the CI test is run in the QA stack |
| Idempotency | Live `EMP-02/03`, `LV-04/05`, `ATT-02/13/14`, `PAY-26`; CI `test_leave_idempotency`, `test_import_idempotency`, `test_optional_idempotency`, `test_b04_adjustment_idempotency`, `test_face_punch_idempotency` | Overlap; live parallel tests (ATT-13, LV-17/18) add true concurrency that CI sequential tests lack |
| Auth token forgery | Live `AUTH-08…14`; CI `test_auth_security` | Overlap; keep both (cheap) |
| Optimistic concurrency | Live `EMP-10…13`, `LV-16/36`, `PAY-11`; `unit/shared/test_if_match.py` | Overlap, consistent |
| Rate limiting | Live `AUTH-31/32`; CI `test_credential_rate_limit`, `test_proxy_aware_rate_limiting`, dual-bucket unit tests | Overlap; none verifies *account lockout* (5 attempts/15 min) — see `AUTH-LOGIN-004` |
| Leave balance arithmetic | Live `LV-01…41`; CI `test_leave_application`, `test_leave_balance_*`, `test_leave_ledger*` (≈32 files) | Largest overlap. Live adds a real approver/employee login chain; keep a trimmed core |

## F. Critical workflows with **no** end-to-end test

"End-to-end" here = exercised through HTTP from trigger to final persisted state (and UI where relevant) in one scenario. Statements are INFERRED from test names/scripts unless marked.

| # | Workflow | Live pass | CI | Gap |
|---|---|---|---|---|
| 1 | **Punch → daily attendance result** (status, worked minutes, late/early, OT) | INFO print only (VERIFIED) | `test_attendance_day`, `test_calculation` (engine/unit + integration) | No live assertion; boundary behaviour (grace edge, bands) unknown end-to-end |
| 2 | **Attendance period validate → finalize → CLOSED → pay run lock → compute → approve → finalise → PAID** | Stops at `lock-inputs` refused (PAY-09) | `test_pay_run` (project-owned) | Report §10 confirms no live full run |
| 3 | **Employee onboarding wizard (case → invite → public submit → HR review → activate → login)** | none | 11 onboarding integration files | No single scenario spans all steps with a browser or mobile client |
| 4 | **Leave approval → attendance projection → period summary → payroll paid days** | leave and punch tested separately | `test_leave_projection*` (leave→attendance) | No test (by file name) follows the chain into the pay run |
| 5 | **Shifts/rosters/policies/periods/overtime configuration → effect on calculation** | `SWP` garbage-input sweep only | 32 attendance integration files | Report §10 |
| 6 | **Platform approval lifecycle** (register → PENDING_APPROVAL → approve → TRIAL; suspend; terminate) | Ran with `COMPANY_APPROVAL_REQUIRED=false` (`start_qa.sh`) so never exercised; `RBAC-14` only 3 GETs | `test_platform_console` (24) | No live platform admin run |
| 7 | **Beat-scheduled jobs** (accrual, year-end, termination sweep, attendance sweep, reminders, comp-off expiry) | Beat deliberately not run | per-task tests call coroutines | A scheduler→queue→worker→DB run has never been seen |
| 8 | **Web UI journeys** | none (no browser session) | 514 Vitest blocks — component/lib level | Real navigation, forms, error states |
| 9 | **Mobile journeys** | none | 278 Flutter blocks — never run | Blocked (SDK) |
| 10 | **Leave year-end & encashment → payroll line** | none | `test_leave_year_end_catchup`, `test_leave_encashment` | Cross-module payment not asserted live |
| 11 | **Arrears across months** | none | `test_arrears` | Multi-run scenario |
| 12 | **Termination / offboarding → final attendance, leave and payroll** | none | `test_master_data_compensation_termination` | F&F is not implemented (5.7 pending) — requirement clarification |
| 13 | **Document download via presigned URL after permission change/expiry** | `DOC-09` bytes only | `test_employee_documents` | Expiry and re-authorisation untested |

## G. Tests that depend on external services or unsafe shared resources

Keyword scan of file contents (INFERRED; false positives expected — e.g. `engine` matches the attendance engine). Files mentioning each dependency:

| Dependency | Files | Danger |
|---|---|---|
| DB | 146 | Needs `DATABASE_URL`; **default is `hrms_dev`** (`tests/conftest.py`). Teardown helper `tenant_wipe.py` issues `DELETE FROM <every table with company_id>` for a company |
| REDIS | 24 | Shared Redis index 0 unless `REDIS_URL` set; broker DB forced to 15 (`HRMS_TEST_CELERY_DB`); rate-limit keys persist between runs |
| MINIO_S3 | 28 | Uses the shared `hrms-documents` bucket on `hrms-minio` unless overridden; failed with `XMinioStorageFull` on the full disk |
| CELERY | 28 | Task tests call coroutines directly; only `test_celery_task_event_loop` crosses loops |
| DOCKER_SUBPROCESS | 13 | Only **`integration/core/test_storage.py`** actually runs docker (VERIFIED: `docker inspect` and **`docker restart --time 10 hrms-minio`**). The other 11 files only spawn Python or use a fake `docker` in `tmp_path` (`test_host_monitor.py:48`) — safe |

Specific hazards (VERIFIED by reading): `test_object_survives_a_minio_container_restart` (skip only when docker/container is absent; no opt-in); `tests/conftest.py` default DB; `tenant_wipe.py`; `mobile/test/live/live_contract_test.dart` (targets `localhost:8000` by default; read-only GETs + login, gated by `HRMS_LIVE_API`); `qa_live` scripts embed DB URLs for ports 5433/6380 — the same ports as the shared dev stack (`start_qa.sh` relies on the DB *name* `hrms_qa_e2e` for isolation).

## H. Feature registers

The registers are kept separate. Evidence for all rows is INHERITED unless noted.

### H1. Implemented and tested (live and/or automated evidence; correctness of the *rules* still subject to the open questions in the defect register Part D)

Auth/sessions/reset/verify; tenant isolation + RLS; RBAC basics; employee CRUD with ETag/If-Match; CSV import (worker round-trip, kill/restart); leave apply/approve/reject/cancel with ledger invariants and concurrency; regularization request→approve→punches; punch intake idempotency; document upload validation; dependency-failure behaviour (storage, Redis); route authorization sweep.

### H2. Implemented but insufficiently tested (prioritised in the execution plan)

| Feature | Why insufficient | Cases |
|---|---|---|
| Attendance daily calculation, policies, shifts, rosters, periods, overtime | CI-only; no live assertion; documented inert settings and open decisions | `ATT-DAY-*`, `SHIFT-*`, `POL-*`, `PER-*`, `OT-*` |
| Payroll calculation, statutory, TDS, arrears | No independent re-derivation; seeded statutory rates unverified | `PAYROLL-CALC-*`, `PAYROLL-STAT-001`, `PAYROLL-TDS-001`, `PAYROLL-ARR-001` |
| Platform console | Live ran with approval OFF; only tenant-admin denial | `PLAT-*` |
| Onboarding & employee lifecycle | No end-to-end scenario | `ONB-FLOW-001`, `EMP-EMPLOY-001` |
| Background jobs via Beat | Beat not run | `JOB-BEAT-001`, `JOB-IDEM-001` |
| Web UI | Unit tests only; ESLint 110 errors (non-blocking in CI); `next build` not run | `WEB-*` |
| Mobile app | Never executed here | `MOB-*` (BLOCKED) |
| Subscription limits | Read-only summary; seat/feature enforcement untested | `SUB-READ-001` |
| Employee-document presigned URL lifecycle | Expiry/re-auth untested | `DOC-DL-001` |
| Immutability of punch/regularization/period action tables | Known gap K-1 | `ATT-PUNCH-006` |

### H3. Not implemented (feature gaps — **not** test failures)

Recruitment, job postings, candidates (`REC-NI-001`) · resume processing and AI features (`AI-NI-001`; specification exists in `docs/product/21_AI_and_Automation_Feature_Specification.md`) · subscription payment/usage billing (`BILL-NI-001`) · reports/exports and notifications beyond transactional email (`RPT-NI-001`) · UI for employee CSV import, leave reassign-approver, bulk roster (web and mobile; API exists) · Payroll 5.7 scope: full-and-final settlement, statutory filings, loans, reimbursements, bonus, formula builder (`PAYROLL_BUSINESS_DECISIONS.md`) · WFH/On-Duty day statuses, punch rounding, auto-close, late-count rules, core-hours enforcement (stored-but-inert; hidden per PD-1) · comp-off step rule (BUS-015) · MFA for platform admins · post-lock arrears for attendance beyond payroll arrears · automatic default-shift cascade.

### H4. Excluded intentionally

Face attendance (Face++ / open-source, enrolment, liveness, face punch): excluded by instruction (`FACE-EXCL-001`). Existing coverage is still **present** — 245 backend test functions in 16 files with `face` in the path, and 4 mobile test files — and was part of the inherited 3,198 total, so that total includes tests this effort has not assessed.

Environment-blocked and clarification registers: see [`QA_DEFECT_REGISTER.md`](QA_DEFECT_REGISTER.md) Parts C and D.

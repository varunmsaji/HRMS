# Pre-Payroll Readiness — Executive Summary

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Scope | All HRMS modules completed before Payroll |
| Method | Direct source inspection + full test-suite execution. **No code was modified.** |
| Full report | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |

---

# Executive verdict

## 🟠 NOT READY — FOUNDATION FIXES REQUIRED

**Payroll design can begin now. Payroll implementation should wait approximately 3–4 weeks.**

The HRMS foundation is well engineered. The things that are hardest to fix later — tenant isolation,
authorization, effective-dated modelling, transactional integrity, immutable audit trails, and money
representation — are all done correctly, and in several cases better than typical for a product at this
stage. None of that should be rebuilt.

What is missing is narrower and more specific: **the artifact Payroll is supposed to consume cannot
currently be produced; where it can, it is incomplete and in several places incorrect; and two whole
categories of Payroll input — salary for onboarded staff, and timezone stability — are unguarded.**

---

## Key numbers

| Metric | Count |
|---|---|
| **Total findings** | **71** |
| 🔴 Blockers | 5 |
| 🟠 Critical | 14 |
| 🟡 High | 17 |
| 🔵 Medium | 15 |
| 🟢 Low | 8 |
| Test gaps | 8 |
| Security findings | 19 |
| Data integrity findings | 17 |
| Documentation gaps | 6 |
| **Client business decisions required** | **15** |
| Product decisions required | 3 |
| **Payroll blockers** | **12** |

| Verification metric | Value |
|---|---|
| Backend source | 43 174 lines / 120 files |
| Test source | 39 434 lines / 112 files |
| **Backend tests passing locally** | **1 145 in 240 s** (executed during this audit) |
| **Frontend tests passing locally** | **342 in 45 files** (executed during this audit) |
| **Frontend type-check** | **Clean** (`tsc --noEmit`, exit 0) |
| **Tests running in CI** | **362 of 1 487** — no database is provisioned; no frontend job exists |
| Database tables | 79 |
| Tables with row-level security | 70 |
| Migrations | 61 |
| Documentation | 211 markdown files |

**Coverage.** Every module completed before Payroll was inspected. A second pass deepened four areas the
first pass had covered only from the payroll-critical path — the organisation CRUD services, bulk
employee import, onboarding internals, and the frontend — and surfaced six additional findings, two of
them payroll-relevant (PAY-013, PAY-014).

---

## Readiness gates

| Gate | Result |
|---|---|
| 1. Architecture | ⚠️ PASS with conditions |
| 2. Data integrity | ❌ FAIL |
| 3. Attendance | ❌ FAIL |
| 4. Leave | ❌ FAIL |
| 5. Security | ❌ FAIL |
| 6. Authorization | ✅ **PASS** |
| 7. Tenant isolation | ⚠️ PASS with conditions |
| 8. Testing | ❌ FAIL |
| 9. Historical integrity | ❌ FAIL |
| 10. Auditability | ⚠️ PASS with conditions |
| 11. Deployment | ❌ FAIL |
| 12. Backup & recovery | ❌ FAIL |
| 13. Monitoring | ❌ FAIL |
| 14. Payroll input readiness | ❌ FAIL |

**2 PASS · 3 PASS-with-conditions · 9 FAIL**

---

## Top 12 issues, ranked by payroll risk

| # | ID | Issue | Severity | Why it ranks here |
|---|---|---|---|---|
| 1 | **PAY-001** | No batch or scheduled attendance generation | 🔴 | Closing a month needs one HTTP call per employee per day — ~3 000 for a 100-person company. **A period cannot be finalized, so Payroll has no input at all.** |
| 2 | **PAY-002** | The frozen period summary has no paid-days figure | 🔴 | The artifact explicitly designed as Payroll's contract omits the number Payroll exists to use |
| 3 | **PAY-003** | Summary buckets double-count and under-cover | 🔴 | A worked holiday counts twice; five day-statuses count zero times. The buckets never reconcile to the month. |
| 4 | **TST-001** | CI does not run the integration, security, or frontend suites | 🔴 | No database is provisioned, and no frontend job exists — so 1 125 of 1 487 tests are not a merge gate. Nothing on this list would be caught automatically. |
| 5 | **PAY-004** | Days before joining are paid at 100 % | 🔴 | A mid-month joiner can be paid for the whole month |
| 6 | **PAY-010** | Leave balance is checked at submission and never again | 🟠 | Two applications approved after one balance check drive the balance negative. The policy switch that governs this is never read. |
| 7 | **ATT-001…005** | ~15 configurable policy rules are stored, validated, and shown in the UI — and never applied | 🟠 | Punch rounding, auto-close, half-day split, excess-break handling, night overtime. Payroll would be built on rules that appear to exist. |
| 8 | **PAY-008** | Attendance results are not exactly reproducible | 🟠 | Recomputing an unchanged day can give a different answer. A payslip cannot be defended after the fact. |
| 9 | **PAY-014** | Employees hired through digital onboarding have **no salary record at all** | 🟠 | Activation writes employee, employment, assignment, bank and statutory — but never compensation. The bulk-import path does. A docstring claims it does; it does not. |
| 10 | **PAY-013** | Changing a company or branch timezone silently alters unlocked historical attendance | 🟠 | The guard was written as a placeholder "until Attendance exists". Attendance exists; the guard is still an empty function. |
| 11 | **PAY-005 / PAY-006** | Post-exit days deduct full pay; incomplete days are neither paid nor unpaid until lock | 🟠 | Wrong final settlements; wrong pre-close previews |
| 12 | **DAT-001** | Leave accrual can double-credit under concurrency | 🟠 | Check-then-insert with no constraint, and the scheduler has no single-instance guarantee |

---

## Top 10 strengths — do not rebuild these

| # | Strength | Evidence |
|---|---|---|
| 1 | **Tenant isolation architecture** | 70 of 79 tables carry `ENABLE` + `FORCE ROW LEVEL SECURITY`; the app runs as a dedicated non-superuser role with no `BYPASSRLS`; migrations use a separate credential the app process never loads. Better than most production systems. |
| 2 | **Object-level authorization** | Every write checks the *target* record, not merely that the caller holds a permission — the control that actually prevents IDOR. Applied consistently, with commit history showing it was a deliberate hardening pass. |
| 3 | **The period-lock mechanism** | Two independent guards, fail-closed validation, atomic finalization, and a reopen that needs its own stronger permission, a mandatory reason, and a full audit trail. **Leave approval into a locked period is correctly refused and rolls the whole transaction back.** |
| 4 | **Never mutate a fact** | A wrong punch becomes a new punch. A wrong balance becomes an offsetting entry. A wrong attendance status becomes a regularization that writes punches and recomputes. Seven tables have no update path at all. |
| 5 | **Effective-dated modelling** | Overlap prevention is a database guarantee (GiST exclusion constraints), not an application check. "At most one active employment per employee" is enforced by Postgres. |
| 6 | **Policy versioning and snapshots** | Published versions are immutable; every attendance result records the six versions that produced it. Editing a policy cannot change history. |
| 7 | **Money and numeric discipline** | No floating-point arithmetic anywhere near money or duration. Integer minor units. Integer minutes. **Attendance deliberately refuses to compute money at all** — exactly the right boundary for Payroll. |
| 8 | **Deterministic policy precedence** | One 8-level precedence walk, implemented once and reused for all six policy kinds. 26 potential rule conflicts were traced; every one resolves deterministically. |
| 9 | **Pure, testable calculation core** | The attendance engine has no database access; 362 unit tests run in 1.5 seconds. Payroll should copy this pattern exactly. |
| 10 | **Decision discipline** | Numbered, dated decision logs (WD-01…WD-33, LD-01…LD-23) record what was chosen, why, and — unusually — **what was deliberately not built**. 211 documents. This is why the audit could distinguish gaps from oversights. |

---

## Required before Payroll implementation begins

Thirteen items, estimated at **3–4 focused engineering weeks**:

1. **TST-001** — add PostgreSQL and Redis services to CI; run migrations; connect as `hrms_app`, not the
   superuser. *~15 lines of YAML. Do this first — it makes everything else verifiable.*
2. **PAY-001** — a batch attendance-calculation endpoint plus a scheduled job.
3. **PAY-002** — add `paid_days` and `payable_days` to the frozen period summary.
4. **PAY-003** — make summary buckets mutually exclusive and reconcilable.
5. **PAY-004** — pre-joining days must not be paid.
6. **PAY-005** — post-exit days must not deduct.
7. **PAY-006** — decide and implement the pre-lock treatment of incomplete days.
8. **PAY-007** — make the lock-time paid/LOP resolution explicit, audited, and tested.
9. **PAY-008** — persist the derived inputs and add an engine-version stamp.
10. **PAY-010** — re-check the leave balance at approval, under a row lock.
11. **SEC-001** — fix production CORS; fail boot if it is unconfigured.
12. **PAY-014** — create a compensation record at onboarding activation (or require one before a case can
    be activated).
13. **PAY-013** — implement the timezone-change guard on both company and branch.

**In parallel, and blocking nothing:** decide *implement or remove* for each of the ~15 inert policy
fields (ATT-001…007, PAY-011), and obtain answers to the 15 client business decisions.

---

## Can safely be deferred

Everything below can proceed alongside Payroll development without risking incorrect money:

- Splitting the large service files (`attendance/service.py` is 5 480 lines)
- Table partitioning, cursor pagination beyond a hard cap, query optimisation
- Frontend accessibility, end-to-end tests, duplicate-submission guards
- Moving refresh tokens out of `localStorage`, MFA, password reset
- Column-level encryption for statutory identifiers
- Documentation tidying and dead-code removal

**Not deferrable past production launch** (though not blocking Payroll *development*): monitoring,
backups with a rehearsed restore, a deployment pipeline, and security-header hardening. Operations
scored **0 of 24** on the readiness checklist — not weak, absent.

---

## The 15 business decisions the client must make

These are **not** engineering defects. Each is a genuine business question the code cannot answer, and
each changes what Payroll must compute. Full detail in
[`PAYROLL_BLOCKER_REGISTER.md`](./PAYROLL_BLOCKER_REGISTER.md).

| # | Decision |
|---|---|
| 1 | Are holidays and weekly offs paid days for **every** employment type, or only for monthly-salaried staff? |
| 2 | How are days before joining and after exit treated inside a payroll period? |
| 3 | Are half-day weekly offs (e.g. alternate half-Saturdays) required? |
| 4 | May HR cancel an employee's approved leave? (Today only the original submitter can.) |
| 5 | Is a negative leave balance ever permitted, and under whose approval? |
| 6 | If an approval would overdraw the balance — block it, or allow and recover through payroll? |
| 7 | Is the payroll period per company, per legal entity, or per pay cycle? |
| 8 | Who may reopen a closed period after payroll has used it, and how are already-paid figures corrected? |
| 9 | Restricted and optional holidays currently default to working days — confirm. |
| 10 | A holiday falling on a weekly off currently grants no compensatory day — confirm. |
| 11 | Is overtime worked on a full-day-leave day payable? |
| 12 | When an employee works despite approved leave, they are currently paid as present **and** the leave day stays deducted until HR intervenes — confirm. |
| 13 | Should ordinary leave expire, beyond the carry-forward cap? |
| 14 | Is advance leave (borrowing against future accrual) required? |
| 15 | Comp-off day-length must be configured per overtime policy, or comp-off is never credited at all — confirm the value. |

---

## Recommended next step

**One decision meeting, then one focused remediation sprint.**

1. **This week** — take the 15 business decisions above to the client. They are independent of the
   engineering work and are on the critical path for Payroll's data model.
2. **This week** — the product team decides *implement or remove* for each of the ~15 inert policy
   fields. Shipping a configuration screen that changes nothing is worse than not shipping it.
3. **Week 1** — fix CI first (TST-001). Everything else becomes verifiable the moment it lands.
4. **Weeks 1–4** — the thirteen P0 items, in the sequence given in
   [`TECHNICAL_DEBT_REGISTER.md`](./TECHNICAL_DEBT_REGISTER.md).
5. **In parallel from now** — Payroll data model, ADRs, and sign-off of
   [`PAYROLL_FOUNDATION_CONTRACT.md`](./PAYROLL_FOUNDATION_CONTRACT.md). That contract is already
   **42 of 44 clauses verified** on its guarantee side; the foundation is sound, and design work should
   not wait.
6. **Separate track** — operations: monitoring, backups with a rehearsed restore, and a deployment
   pipeline. Required before production, not before Payroll development.

**Re-audit gate:** when the thirteen P0 items are closed, re-run Gates 2, 3, 4, 8, 9, and 14. Payroll
implementation starts when those six turn PASS.

---

## Companion documents

| Document | Contents |
|---|---|
| [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) | The complete 43-part audit |
| [`PAYROLL_INPUT_READINESS_MATRIX.md`](./PAYROLL_INPUT_READINESS_MATRIX.md) | Every input Payroll will consume, with a verdict |
| [`PAYROLL_BLOCKER_REGISTER.md`](./PAYROLL_BLOCKER_REGISTER.md) | All 53 findings + 15 business decisions, with evidence |
| [`PAYROLL_FOUNDATION_CONTRACT.md`](./PAYROLL_FOUNDATION_CONTRACT.md) | What Payroll may and may not assume |
| [`PRODUCTION_READINESS_CHECKLIST.md`](./PRODUCTION_READINESS_CHECKLIST.md) | 148-point checklist |
| [`TECHNICAL_DEBT_REGISTER.md`](./TECHNICAL_DEBT_REGISTER.md) | Prioritised debt with a 4-week sequence |
| [`SECURITY_READINESS_AUDIT.md`](./SECURITY_READINESS_AUDIT.md) | Security and authorization findings |
| [`DATA_INTEGRITY_AUDIT.md`](./DATA_INTEGRITY_AUDIT.md) | Database, transactions, concurrency, historical integrity |
| [`PRE_PAYROLL_CLIENT_READINESS_REVIEW.md`](./PRE_PAYROLL_CLIENT_READINESS_REVIEW.md) | Business-language client report |

---

*No application code, schema, migration, test, or configuration was modified during this audit.*

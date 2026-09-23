# Technical Debt Register

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |

**Severity:** 🔴 BLOCKER · 🟠 CRITICAL · 🟡 HIGH · 🔵 MEDIUM · 🟢 LOW

**Timing classification**

| Class | Meaning |
|---|---|
| **P0 — Must fix before Payroll** | Payroll cannot be built correctly on top of this |
| **P1 — Must fix before the Payroll architecture is finalized** | Changes what Payroll's design must assume |
| **P2 — Should fix before production** | Not payroll-correctness, but not shippable without it |
| **P3 — Can fix during Payroll** | Real debt, safely parallelisable |
| **P4 — Can defer** | Improvement, no business or financial risk |

---

## Summary

| Timing | Count | Estimated effort |
|---|---|---|
| P0 — Must fix before Payroll | 13 | ~3–4 engineering weeks |
| P1 — Before Payroll architecture is finalized | 10 | ~2 weeks |
| P2 — Before production | 15 | ~3–4 weeks |
| P3 — During Payroll | 20 | Parallelisable |
| P4 — Deferrable | 13 | — |
| **Total** | **71** | |

---

## P0 — Must fix before Payroll

| ID | Area | Problem | Severity | Payroll impact | Recommended timing |
|---|---|---|---|---|---|
| PAY-001 | attendance | No batch or scheduled attendance generation. `POST /v1/attendance/days/calculate` handles one employee-date; no Celery task exists. Finalization requires a row for every employment-day. | 🔴 | **A period cannot be finalized, so Payroll has no input at all.** | P0 |
| PAY-002 | attendance | `attendance_period_summary` has no `paid_days` or `payable_days` column | 🔴 | The frozen artifact designed as Payroll's contract omits the single most important figure | P0 |
| PAY-003 | attendance | Summary buckets double-count a worked holiday and assign no bucket to five statuses; half-day leave lands in `half_days`, never `leave_days` | 🔴 | Buckets do not reconcile to the period length; no combination recovers payable days | P0 |
| PAY-004 | attendance | `NOT_JOINED` → `paid_day_fraction = 1.00` | 🔴 | A pre-joining day is paid in full | P0 |
| PAY-005 | attendance | `EXITED` → `lop_fraction = 1.00` | 🟠 | A post-exit day becomes a full deduction against final settlement | P0 |
| PAY-007 | attendance | Lock-time paid/LOP rewrite is unaudited, leaves `attendance_status` disagreeing with the fractions, and depends on implicit ORM session synchronization for the frozen summary to be right. **No test covers it.** | 🟠 | The last mutation before payroll reads the data is the least verified one | P0 |
| PAY-008 | attendance | Sibling-day inputs (`prior_late_days_in_window`, `prior_excess_break_days_in_window`, `remaining_weekly/monthly_minutes`) are not persisted; no engine-version stamp | 🟠 | A payslip cannot be defended — recomputation may not reproduce the paid figure | P0 |
| PAY-010 | leave | Leave balance verified at submit and never re-checked at approval; no lock, no constraint, `allow_negative_balance` never read | 🟠 | Payroll pays leave that was never accrued | P0 |
| DAT-001 | leave | Accrual/carry-forward idempotency is a check-then-insert with no unique index — and Beat has no leader election | 🟠 | Silent, permanent double-crediting of leave balance | P0 |
| SEC-001 | core | `allow_origins=["*"] if is_development else []` — production resolves to zero allowed origins | 🟠 | The application would be non-functional on its first deployment | P0 |
| TST-001 | CI | CI provisions no PostgreSQL or Redis, so 783 integration tests never run as a merge gate. The CI role is also the BYPASSRLS superuser. No frontend job exists. | 🔴 | No regression in business logic, authorization, or tenant isolation is gated on merge | P0 |
| PAY-014 | onboarding | `activate_case` writes Employee/Employment/Assignment/Bank/Statutory but **never `employee_compensation`** — while `onboarding/schemas.py:17` documents that it does. The bulk-import path does create it. | 🟠 | **Employees hired through onboarding have no CTC.** Nothing detects it, because compensation has no consumer until Payroll. | P0 |
| PAY-013 | organisation | `_assert_timezone_change_allowed` (`service.py:601-608`) is an explicit no-op placeholder written "until Payroll/Attendance modules exist". Attendance exists. `update_branch` has no guard at all. | 🟠 | Changing a company or branch timezone silently re-derives UTC day boundaries for every unlocked historical day | P0 |

---

## P1 — Must fix before the Payroll architecture is finalized

| ID | Area | Problem | Severity | Payroll impact | Recommended timing |
|---|---|---|---|---|---|
| ATT-001 | attendance | `punch_rounding` / `rounding_minutes`: `apply_rounding()` has **zero call sites** | 🟠 | Payroll would assume rounding was applied to the minutes it reads | P1 |
| ATT-002 | attendance | `missing_punch_behaviour = AUTO_CLOSE` does nothing; `auto_close_after_minutes` / `auto_close_uses_shift_end` have zero references; `auto_closed` is hard-coded `False` | 🟠 | Days that should auto-close become ABSENT or INCOMPLETE | P1 |
| ATT-003 | attendance | `half_day_split` / `half_day_boundary_minutes` never read; half-day comes only from hour bands | 🟠 | Half-day pay determined by a rule the client did not configure | P1 |
| ATT-005 | attendance | `night_ot_mode = WINDOW` never evaluates the window; `is_night` is `shift.is_cross_midnight` only | 🟠 | Night OT misclassified → wrong multiplier → wrong money | P1 |
| PAY-011 | leave | `allow_negative_balance` never read anywhere | 🟡 | Policy switch that changes nothing | P1 |
| PAY-006 | attendance | `INCOMPLETE` → paid 0.00 / LOP 0.00 until lock; `paid + lop ≠ 1` in the open window | 🟠 | Any pre-close preview or report understates both | P1 |
| PAY-012 | organisation | Weekly-off `off_fraction` computed then discarded — half-day weekly offs become full | 🟡 | Half a day of pay per occurrence | P1 |
| TEN-002 | tests | Test suite runs as the BYPASSRLS superuser; RLS is exercised in one file only | 🟠 | Tenant isolation is designed well and verified weakly, right before Payroll adds new tenant tables | P1 |
| DAT-002 | api | No pagination on ~45 list endpoints; no `LIMIT` in any list query | 🟡 | Payroll reports will inherit the same pattern | P1 |
| ARC-003 | attendance/leave | `leave_day_projection` duplicates `leave_application_day` with no DB-level sync guarantee | 🟡 | Payroll could read either and get different answers | P1 |

---

## P2 — Should fix before production

| ID | Area | Problem | Severity | Recommended timing |
|---|---|---|---|---|
| OPS-003 | infra | No monitoring, metrics, error tracking, or alerting. Sentry is a comment; the unhandled exception is discarded without logging (`handlers.py:80`). `get_logger` has no call sites. | 🔴 | P2 |
| OPS-001 | infra | No CD pipeline, no web image, no production compose, no migration step, no rollback, root container, single uvicorn process | 🔴 | P2 |
| OPS-002 | infra | No backups, no restore testing, no RPO/RTO | 🔴 | P2 |
| SEC-002 | api | Rate limiting on 1 of ~150 endpoints; login, refresh, and the public onboarding surface unlimited | 🟠 | P2 |
| SEC-004 | core | No security headers, no `TrustedHostMiddleware`, no proxy-header handling (which makes the one rate limit global rather than per-client) | 🟠 | P2 |
| SEED-1 | seed | Demo seed has no environment guard; creates a known-credential super-admin with every permission | 🟠 | P2 |
| OPS-006 | infra | Celery Beat has no leader election; duplicate firing is possible by design | 🟠 | P2 |
| OPS-010 | leave | No Celery task has a retry policy or logs anything | 🟠 | P2 |
| OPS-004 | core | `/health` does not probe DB or Redis; no liveness/readiness split; no `HEALTHCHECK` in the Dockerfile | 🟡 | P2 |
| TST-002 | CI | No frontend job at all — 45 vitest files, `tsc`, `next lint`, `next build` never run | 🟡 | P2 |
| TST-003 | CI | No coverage measurement or threshold | 🟡 | P2 |
| TST-004 | tests | No concurrency tests; optimistic locking verified only by passing a stale version | 🟡 | P2 |
| AUD-1 | core | No audit-log read API or UI; the trail is reachable only by direct SQL | 🟡 | P2 |
| IMP-001 | employee_import | `process_batch` has no re-entry guard; Celery redelivery reruns the batch and can create duplicate employees with auto-generated codes | 🟡 | P2 |
| IMP-002 | employee_import | Batch committed as `PENDING` before enqueue; a failed `.delay()` leaves it stuck forever with no detection | 🟡 | P2 |
| PROD-1 | config | Nothing prevents booting production with the literal `change-me-…` JWT secrets | 🟡 | P2 |

---

## P3 — Can fix during Payroll

| ID | Area | Problem | Severity |
|---|---|---|---|
| ATT-004 | attendance | `excess_break_behaviour` never read — FLAG/HALF_DAY/ABSENT/DEDUCT have no effect | 🔵 |
| ATT-006 | attendance | Zero-reference fields: `early_out_uses_core_end`, `split_shift_block_mandatory`, `split_shift_allow_hours_compensation`, `wfh_requires_punch`, `wfh_uses_shift_hours`, `requires_pre_approval`, `auto_approve_within_minutes` | 🔵 |
| ATT-007 | attendance | `late_count_window` / `excess_break_count_window` stored but hard-coded to the calendar month | 🔵 |
| ATT-009 | attendance | `match_breaks` compares only the gap **start** time-of-day to break windows | 🔵 |
| ATT-010 | attendance | SPLIT shifts never compute late/early and never apply core-hours or cumulative overrides | 🔵 |
| ATT-011 | attendance | `round_minutes` NEAREST uses Python `round()` → banker's rounding | 🔵 |
| ATT-013 | attendance | Half-day leave + work → status `HALF_DAY` but `paid_day_fraction = 1.00` | 🔵 |
| DAT-003 | all | Four N+1 patterns; ~50–70 queries per employee-day | 🟡 |
| DAT-004 | leave | `_reverse_approval` uses `date.today()` — server-local, not company timezone | 🔵 |
| DAT-005 | leave | Backdating check uses `date.today()`; `max_requests_per_month` counts by UTC month of `submitted_at` | 🔵 |
| DAT-006 | leave | Same-leave-type overlapping applications not blocked at submit | 🔵 |
| DAT-010 | attendance | No FK on `leave_day_projection.leave_application_id` | 🔵 |
| SEC-005 | onboarding | Upload: no MIME allow-list, no magic-byte check, unsanitised filename in the S3 key | 🔵 |
| SEC-006 | onboarding | Upload body fully buffered before the size check | 🔵 |
| SEC-007 | db | `company` has `FORCE` RLS without `ENABLE` or a policy | 🔵 |
| SEC-011 | CI | No dependency, secret, container, or static analysis scanning | 🟡 |
| ARC-001 | attendance | `attendance/service.py` 5 480 lines / 9 service classes; `organisation/service.py` 3 895 | 🟡 |
| ARC-002 | all | Module→module import edges unconstrained; `leave ↔ attendance` cycle hidden by function-scoped imports | 🟡 |
| DOC-001 | docs | Configuration catalogues document behaviour the engine does not implement (ATT-001…005) | 🟠 |
| DOC-002 | docs | `docs/business-rules/policies/` untracked in git | 🔵 |
| DEAD-1 | all | Dead code: `apply_rounding`, `ingestion/routes.py`, `PaginationMeta`, `MoneyAmount`, `get_logger`, `gunicorn`, `rate_limit_window_ms`/`rate_limit_max` | 🔵 |
| ERR-1 | core | Catch-all exception handler discards the exception without logging it | 🟠 |
| IMP-003 | employee_import | Mid-run commits leave a crashed batch stuck at `PROCESSING` with no per-row success record | 🔵 |

---

## P4 — Can defer

| ID | Area | Problem | Severity |
|---|---|---|---|
| ATT-008 | attendance | Scheduled breaks with no punched gap are never deducted (documented limitation) | 🟢 |
| ATT-012 | attendance | `_evaluate_no_schedule` has a redundant `lop_fraction` conditional | 🟢 |
| DAT-007 | employee | `vpf_percentage` annotated `float` over a `Numeric(9,4)` column | 🟢 |
| DAT-009 | attendance | `Numeric(3,2)` fractions leave no headroom for quarter-day constructs | 🟢 |
| DAT-011 | attendance | ~~`attendance_period.legal_entity_id` reserved, always NULL (PD-LOCK-1 open)~~ — fixed 2026-09-23, periods are per legal entity (WD-34) | 🟢 |
| DAT-012 | db | No partitioning on `punch` / `attendance_day` (documented deferral, WD-26) | 🟢 |
| SEC-003 | web | Access and refresh tokens in `localStorage` (documented trade-off) | 🟠 but deferrable |
| SEC-010 | auth | No password reset, email verification, or MFA; weak password policy | 🔵 |
| KEY-1 | auth | No JWT key rotation mechanism (no `kid`, no multi-key verification) | 🟢 |
| ARC-004 | all | Cross-module recompute is synchronous; ADR-0012 outbox unimplemented | 🔵 |
| PII-1 | employee | Statutory identifiers and bank details stored unencrypted | 🔵 |
| PII-2 | core | Audit log captures full PII with no redaction or retention policy | 🔵 |
| TOK-1 | onboarding | Onboarding token travels as a URL path parameter (appears in logs and `Referer`) | 🔵 |
| DOC-003 | docs | No deployment, security, or operational documentation | 🔵 |
| DOC-004 | repo | Untracked non-project artifacts at the root (`mavericks-kit.zip`, `jersouy/`, …) | 🟢 |
| DOC-005 | docs | Superseded NestJS docs sit alongside current documentation | 🟢 |
| FE-1 | web | No duplicate-submission guard, no unsaved-changes guard, no company-timezone renderer despite ADR-0010 | 🔵 |
| FE-2 | web | No accessibility testing; no end-to-end tests | 🔵 |
| TZ-1 | tests | No DST-transition test (India has no DST; matters for a future non-IST tenant) | 🟢 |
| MIG-1 | db | Initial migration's `downgrade()` raises `NotImplementedError`; no rollback rehearsal | 🔵 |
| IMP-004 | employee_import | Whole CSV buffered at upload; the 1 000-row cap is enforced only after full parse | 🔵 |

---

## Debt that is deliberate, documented, and correct

Not everything unbuilt is debt. The following are **recorded decisions with stated reasoning**, and they
should be read as scope management rather than shortcuts:

| Item | Decision | Why it is sound |
|---|---|---|
| No table partitioning on `punch` | WD-26 | Zero punch rows exist; partitioning remains a valid additive migration once volume appears |
| No outbox / event bus | ADR-0012 pending; §25 | Synchronous in-process calls are acceptable at current scale and are honestly labelled as a stand-in |
| `AttendancePeriod.legal_entity_id` reserved | WD-30 / PD-LOCK-1 | The column ships ahead of use so a future grain change needs no data migration |
| Approval state machines mirrored, not shared | LD-05 | Three implementations, consciously chosen over a premature abstraction across three different domains |
| `LeaveDayProjection` as a stand-in read model | WD-31 | Built before Leave existed, explicitly marked replaceable. Now that Leave exists, ARC-003 asks for the decision to be revisited — not reversed. |
| Scheduled breaks not auto-deducted | `calculation.py:23-28` | The policy column that would configure it was never added; the engine refuses to invent undocumented behaviour |
| SPLIT block-level granularity | `calculation.py:17-22` | The architecture does not specify a finer contract; the engine does not invent one |
| Half-day leave as a flat 0.50 | WD-31 | Same reasoning, same precedent |
| `AttendanceDay.is_locked` shipped in W4 before any lock existed | W4 plan decision 2 | The seam shipped ahead of the mechanism, and W8 then used it exactly as intended |

This pattern — **build the mechanism the policy configures, refuse to invent behaviour the policy does
not describe, and write down what was deliberately left out** — is the single best engineering habit
visible in this codebase. It is also precisely why ATT-001…007 are findings: those fields *were*
configured, and the engine silently does not honour them, which breaks the same contract in the opposite
direction.

---

## Recommended sequencing

```
Week 1   TST-001 (CI + DB service + hrms_app role + frontend job)  ← unblocks verifying everything
         SEC-001 (CORS)                                     ← trivial, prevents a first-deploy outage
         PAY-004, PAY-005 (paid/LOP for NOT_JOINED/EXITED)  ← one-line fixes, high value
         PAY-013 (timezone guard)                           ← one day, closes a silent-history hole
         DAT-001 (accrual unique index)

Week 2   PAY-002, PAY-003 (summary columns + aggregation)   ← the Payroll contract itself
         PAY-007 (explicit lock-time resolution + audit + test)

Week 3   PAY-001 (batch calculation endpoint + Celery task) ← the largest single item
         PAY-008 (snapshot sibling inputs + engine version)

Week 4   PAY-010 (balance re-check under lock at approval)
         PAY-014 (compensation at onboarding activation)
         P1 decisions on ATT-001…005 (implement or remove)
         TEN-002 (run the suite as hrms_app)

Parallel Payroll data model + ADRs + PAYROLL_FOUNDATION_CONTRACT sign-off
         P2 operational work (monitoring, deployment, backups) on a separate track
```

---

*No application code, schema, migration, test, or configuration was modified during this audit.*

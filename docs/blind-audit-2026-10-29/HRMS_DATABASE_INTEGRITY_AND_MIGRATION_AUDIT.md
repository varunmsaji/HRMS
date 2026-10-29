# HRMS Database Integrity & Migration Audit

## 1. Migration history (confirmed by parsing, no Alembic run)
* 127 revisions, **single head** `20261030090000`, **no branch points, no dangling `down_revision`**.
* The head migration (`20261030090000_attendance_geofencing.py`) is **untracked in Git** (F-19): the repository HEAD cannot reproduce the schema the working-tree code expects.
* Migrations are hand-written raw SQL (`op.execute`), mostly idempotent (`IF NOT EXISTS`, `DROP POLICY IF EXISTS`).
* Destructive-operation scan of upgrade paths: one `DROP COLUMN` (`20260813130000_branch_fields`), two `ALTER COLUMN ... TYPE` (`20260918090000`, `20261009091000`). The `TRUNCATE` hits in other revisions are `REVOKE ... TRUNCATE` privilege statements, not data truncation. No `DROP TABLE` in upgrade paths found by the scan.

## 2. Risks
| ID | Sev | Conf. | Item |
|---|---|---|---|
| F-11 | P2 | confirmed | **Model/schema drift is undetectable**: models carry no constraints; no `alembic check`, `compare_metadata` or schema-drift test was found in `tests/` or CI (`grep` for autogenerate/compare_metadata/drift returned nothing). |
| F-20 | P2 | needs validation | `ALTER COLUMN ... TYPE` on `leave_application.approval_chain` and `leave_application_day.half` rewrites the table under `ACCESS EXCLUSIVE`; harmless while small, risky once populated. Applied already in history, so relevant only for similar future changes. |
| F-21 | P2 | unverified | Rollback story: downgrade functions exist, but the executable `tests/integration/migrations` suite was not run; data-bearing downgrades (e.g. backfills `20260920`, `…928`, `…1001`) are likely lossy. Treat production recovery as *restore from backup*, not *downgrade*. |
| F-22 | P2 | unverified | `infra/backup/pg_backup.sh`/`pg_restore.sh` exist; a restore drill was not evidenced. |
| — | P3 | confirmed | `docker-compose.prod.yml` has a one-shot `migrate` service (`alembic upgrade head`) — good; but no pre-migration backup step is wired into it. |

## 3. Referential integrity (see F-03)
Composite tenant FKs: 4 total (`20261027092000` ×1, `20261030090000` ×3). Everything else relies on application checks. `20261027092000`'s own docstring shows the team recognised the pattern; rollout was not completed for payroll/leave.

**Concrete failure scenario (schema-level, confirmed possible):** a service bug or direct SQL as `hrms_app` with `app.company_id = A` inserts a `pay_run_employee` whose `company_id = A` but `employee_id` belongs to company B. RLS `WITH CHECK` passes (row's own `company_id = A`); the single-column FK passes. Whether any *endpoint* can be driven to do this was not exhaustively verified; sampled paths filter parents by `company_id`.

## 4. Transactions & concurrency (database side)
* Session lifecycle: one transaction per request, committed in `get_session` after the handler returns, rolled back on any exception (`core/db/session.py:98-113`). Good default.
* **Mid-request commits** (≈20 sites) break the "one transaction per request" model and drop the transaction-local `app.company_id` (F-02). See Background-Jobs report for the full list.
* Advisory locks with documented acyclic order: `leave-dates → payroll-finalise → attendance-period-close → leave balance` (`core/db/locks.py`), bounded waits via `bounded_lock_wait`. Strong.
* Optimistic concurrency: `If-Match` + integer `version` on mutating routes (payroll, org). Good.
* Idempotency: `idempotency_key` table + `run_idempotent` (payroll pay-run actions, punches).

## 5. Duplicate-entry protection (confirmed)
| Domain | Mechanism |
|---|---|
| Attendance day | `UNIQUE(company_id, employee_id, attendance_date)` |
| Punch | client `idempotency_key` partial unique; **no uniqueness on (employee, time, direction)** — duplicate physical punches are an application rule (not verified in depth) |
| Leave accrual | `uq_leave_ledger_cycle_entry`, `uq_leave_ledger_comp_off_credit`; `leave_year_end_run` unique |
| Pay run | `pay_run_entity_month_uq`; `pay_run_arrear_applied_uq` |
| Salary | `employee_salary_no_overlap` EXCLUDE |
| Onboarding | email lock `lock_onboarding_case_email` + `20261027091000_onboarding_case_email_unique` |

## 6. Recommendations (not implemented)
1. Add CI step `alembic upgrade head && alembic check` against a scratch DB, plus a test that asserts every ORM-declared constraint exists.
2. Add `pre-migrate backup` to the deploy runbook; rehearse restore into a scratch instance and record RTO/RPO.
3. For future type changes on populated tables use add-column → backfill → swap, or `USING` with `lock_timeout`.
4. Commit migrations with their code; forbid deploying from a dirty tree.

# Employee Compensation (E-06) — Investigation + Implementation Plan

Status: **Planning only — no application code, migration, test, or database object was created or
modified by this document.** This is the definitive brief the next work session implements E-06
from, with no further audit. Every claim is cited to a document (path + section/line), a live code
file (path + line/symbol), or a live database object (verified via read-only `psql`). Where a
requirement is not sourced, it is labelled **UNDOCUMENTED** or **PRODUCT DECISION REQUIRED** rather
than invented.

---

## 1. Executive Summary

E-06 (Employee Compensation) is next in the locked vertical-slice sequence
(`01_EMPLOYEE_MODULE_PLAN.md` §2 "E-06", §4 dependency graph) after E-01 (Foundation), E-03
(Employment Lifecycle), E-04 (Employee Assignment), and E-05 (Shift Assignment), all **COMPLETE**
(439 backend tests passing per `16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md` §14).

The `employee_compensation` table has existed, fully formed, since the very first migration
(`20260803124757_init_schema.py`, running `apps/api/scripts/sql/001_init_schema.sql:279-293`) —
RLS-forced, GiST no-overlap-constrained, FK-linked to `employee.id`. It has **zero rows** and **zero
application code**: no ORM model, repository, service, schema, router, permission, or test exists
anywhere in `apps/api/src/hrms/modules/employee/` (verified — `models.py`'s own docstring states
`EmployeeCompensation` "still belongs to a later slice (E-06...) and is not mapped here",
`apps/api/src/hrms/modules/employee/models.py:4-6`). This means **E-06 is almost entirely an
application-layer build**: model, repository, service, schema, router, permissions, audit — mirrored
directly off the `EmployeeAssignment` pattern (E-04/E-05), which is the closest shipped sibling
(effective-dated, `employee_id`-keyed, single insert-only write operation).

A column-by-column comparison (§4) found the live table is **already sufficient for a first,
correctly-scoped E-06 slice** with **no migration required** — it already carries every column the
locked architecture record (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C, "Employee Compensation")
names as load-bearing (`annual_ctc_minor`, `currency`, `effective_from`/`effective_to`, `version`).
The additional columns the target data model documents (`salary_structure_id`, `monthly_gross`,
`revision_type`, `revision_reason`, `approved_by`, `approval_request_id`, `is_arrears_processed`, and
the child `employee_compensation_component` table) are all either dependent on modules that do not
exist yet (Payroll's salary-structure catalogue, the approval-routing engine) or are optional
enrichment, not load-bearing for a correct, effective-dated CTC history. §18 gives the exact,
minimal, ADD-COLUMN-only migration this session should still run to carry `revision_type` and
`revision_reason` (both fully specified, zero-dependency, and named by FR-EMP-012 as this slice's
own requirement) — everything else is deferred with a named reason.

**Status: READY TO IMPLEMENT**, with one genuine product decision flagged (§16) that has a safe,
precedent-following default if product does not respond before the session starts (documented
explicitly, not silently assumed).

---

## 2. Current Implementation State

| Layer | State | Evidence |
|---|---|---|
| Database table | Live since the first migration, 0 rows, RLS forced, GiST no-overlap constraint live | `apps/api/scripts/sql/001_init_schema.sql:279-293,501-506`; live `\d+ employee_compensation` (§4.1) |
| ORM model | **None** | `apps/api/src/hrms/modules/employee/models.py` — no `class EmployeeCompensation`; module docstring (lines 4-6) names it explicitly as not yet mapped |
| Repository | **None** | `apps/api/src/hrms/modules/employee/repository.py` — no `EmployeeCompensationRepository` |
| Service | **None** | `apps/api/src/hrms/modules/employee/service.py` — no `EmployeeCompensationService` |
| Schemas | **None** | `apps/api/src/hrms/modules/employee/schemas.py` — no `Compensation*` schema |
| Router | **None** | `apps/api/src/hrms/modules/employee/router.py` — no `/compensation` route |
| Permissions | **None seeded** | `apps/api/src/hrms/modules/employee/permissions.py` — module docstring line 36 lists `VIEW_COMPENSATION` explicitly among codes that "belong to later slices (E-02/E-06/...)" |
| Tests | **None** | No `test_employee_compensation*.py` anywhere under `apps/api/tests/` |
| Frontend | **None** | `find apps/web/src -iname "*employee*"` → zero results (verified this session) |
| Rows | **0** | `SELECT count(*) FROM employee_compensation;` → `0` (verified this session) |

`employee_compensation` is mentioned in Python source **only** as a prose comparison inside
`20260814090000_employment_lifecycle.py`'s own docstring (comparing its `employment_no_overlap`
GiST pattern to "the one already live for employee_assignment/employee_compensation") — never as
executable code. Grep confirms this (`grep -rn employee_compensation apps/api/src apps/api/alembic`
this session).

---

## 3. Authoritative Sources

Every document below was read in full for this plan; only what it contributed is listed.

| Document | Contribution |
|---|---|
| `docs/modules/employee/00_EMPLOYEE_AUDIT.md` | Original full-aggregate audit — §3.4 (live `employee_compensation` schema + gaps), §10 field classification, §13 permission catalogue, §16/§17 E-06 slice row and decision list |
| `docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md` | E-06 slice definition (§2), dependency graph (§4) — E-06 depends on E-01+E-03 only, not E-04/E-05 |
| `docs/modules/employee/01_EMPLOYEE_FOUNDATION_AUDIT.md` | E-01-era precedent for "verify live DB before trusting docs" discipline; confirms `employee` has no compensation-adjacent gap |
| `docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` | §1 effective-dating pattern (the template this plan reuses verbatim), §2 section J (full target `employee_compensation` field inventory + classification), §3 proposed ALTER TABLE DDL |
| `docs/modules/employee/03_EMPLOYEE_API_PLAN.md` | §2.3 — the authoritative `/v1/employees/{id}/compensation` endpoint shape (GET history/as-of, POST revision) |
| `docs/modules/employee/04_EMPLOYEE_UX_PLAN.md` | §2 — Compensation tab spec (permission-gated, absent not disabled); confirms no frontend work is required for E-06 itself (ships with E-09) |
| `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` | Part A2 (build statutory/bank now — not this slice, but confirms sequencing), Part A9 (RBAC gap-resolution precedent used for any new code), Part B4/C (locked Compensation data-model shape, `employee_id`-keyed), Part D (full rehire walkthrough including compensation), Part G item 8 (approval-routing field: store, don't enforce) |
| `docs/modules/employee/06_EMPLOYEE_FOUNDATION_IMPLEMENTATION_REPORT.md` | Confirms E-01's exact precedent for permission-catalogue subsetting and audit-action naming this slice should mirror |
| `docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md` | Methodology precedent (how to handle an undocumented enum: propose from evidence, flag for product, do not invent) — no direct E-06 content, but the working method this document reuses for `revision_type` |
| `docs/modules/employee/08_EMPLOYMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md` | Confirms `employment.status` is now `ACTIVE`/`TERMINATED` (locked), which this plan uses for the "covering employment" validation rule (mirroring E-04's own rule) |
| `docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` | **The direct template for this plan's shape** — engineering-decision classification method, migration/model/repository/service/router/permission/test section structure, all reused |
| `docs/modules/employee/10_EMPLOYEE_ASSIGNMENT_MODULE.md`, `11_EMPLOYEE_ASSIGNMENT_API.md` | Exact API reference shape and prose conventions this plan's §11 follows |
| `docs/modules/employee/12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md` | Ground truth for what was actually built (vs. planned) for Assignment — used to confirm the plan-to-report fidelity this document should also achieve |
| `docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md`, `14_..._MODULE.md`, `15_..._API.md`, `16_..._REPORT.md` | Confirms the "no migration needed / minimal migration" pattern is a real, precedented outcome in this codebase (E-05 added exactly one nullable column) — direct precedent for this plan's §18 conclusion |
| `docs/product/19_RBAC_and_Permission_Matrix.md` | §3.1 — the 14-code `EMPLOYEE.*` catalogue including `VIEW_COMPENSATION`/`UPDATE_COMPENSATION` (line 45-46); §1 access-control equation; §6 field-sensitivity tiers (RESTRICTED) |
| `docs/product/09_API_Standards.md` | §3.2 — original flat-`POST /employees` nested-`compensation{}` shape (superseded by the sub-resource shape in `03_EMPLOYEE_API_PLAN.md`, flagged §11); §1.3/1.4 envelope conventions |
| `docs/product/08_Database_Architecture.md` | §5.4 — target `employee_compensation` schema (`salary_structure_id`, `monthly_gross`, `revision_type`, `revision_reason`, `approved_by`, `approval_request_id`, `is_arrears_processed`) + `employee_compensation_component` child table; §5.1 money/ADR-0006 convention |
| `docs/database/Database_Architecture.md` | Confirmed as a short **developer-guide pointer**, not a competing source — it explicitly says "full data dictionary: `docs/product/08_Database_Architecture.md`" (line 3) and contains no `employee_compensation`-specific content; no discrepancy found, `docs/product/08` is authoritative |
| `docs/development/FastAPI_Development_Standards.md` | §1-3 — style/layout/error-handling conventions confirmed already followed by the Employee module |
| `docs/modules/grade/01_Grade_Module.md`, `02_Grade_API.md`, `00_GRADE_AUDIT.md` | Grade's `min_ctc`/`max_ctc`/`approval_limit` semantics — confirmed **informational bands only**, no enforcement mechanism documented anywhere (§8) |
| `docs/product/17_SRS_Phase1_Core_Modules.md` | FR-EMP-003/004/005 (effective-dating rules, already implemented generically), FR-EMP-012 (promotion may include "optional compensation revision"), FR-ORG-007 (Grade's CTC fields), FR-PAY-003/004/010 (salary structure/CTC builder/arrears — Payroll-owned, not this slice) |
| `docs/product/07_Backend_Architecture.md` | §9 — `AuditService` write-path convention + `sensitive_access_log` read-path convention for RESTRICTED fields (§13) |
| `docs/product/14_Security_Architecture.md` | §1 (column-level encryption for PAN/Aadhaar/bank — not CTC, confirmed CTC is not named as requiring encryption-at-rest beyond the standard column protections) + confirms `sensitive_access_log` has no `UPDATE`/`DELETE` grant at the DB-role level (defence in depth) |
| Live code: `apps/api/src/hrms/modules/employee/{models,repository,service,schemas,router,permissions,exceptions,dependencies}.py` | The exact pattern this plan mirrors — cited throughout, especially §6, §9, §11, §12 |
| Live code: `apps/api/src/hrms/modules/organisation/models.py` (`Grade` class) | Confirms `min_ctc`/`max_ctc`/`approval_limit` exist, are nullable, have no CHECK/FK tying them to `employee_compensation` (§8) |
| Live code: `apps/api/tests/integration/modules/employee/test_employee_assignment.py` | Test-structure template (§19) |
| Live database (`psql`, read-only) | §4 — full live schema dump, row counts, `alembic_version` |

---

## 4. Database Audit

### 4.1 Live schema (`\d+ employee_compensation`, verified this session)

```
 id               | uuid                     | not null | gen_random_uuid()
 company_id       | uuid                     | not null
 employee_id      | uuid                     | not null
 annual_ctc_minor | bigint                   | not null
 currency         | character(3)             | not null | 'INR'::bpchar
 effective_from   | date                     | not null
 effective_to     | date                     |
 created_at       | timestamp with time zone | not null | CURRENT_TIMESTAMP
 updated_at       | timestamp with time zone | not null
 deleted_at       | timestamp with time zone |
 version          | integer                  | not null | 1

Indexes:
    employee_compensation_pkey PRIMARY KEY btree (id)
    employee_compensation_company_id_idx btree (company_id)
    employee_compensation_employee_id_effective_from_idx btree (employee_id, effective_from)
    employee_compensation_no_overlap EXCLUDE USING gist
      (employee_id WITH =, daterange(effective_from, COALESCE(effective_to,'infinity'::date),'[]') WITH &&)
Foreign keys:
    employee_compensation_employee_id_fkey FOREIGN KEY (employee_id)
      REFERENCES employee(id) ON UPDATE CASCADE ON DELETE RESTRICT
Policies (forced RLS):
    tenant_isolation USING (company_id = current_setting('app.company_id', true)::uuid)
```

Row count: **0**. `alembic_version` = `20260814110000` (head — matches E-05, the last-applied
migration; confirmed this session, DB is up to date with every merged migration).

A stray `_prisma_migrations` table exists with exactly 1 row from 2026-08-03 — a pre-Alembic
prototype artifact, confirmed pre-existing and unrelated to E-06 (noted per the task brief, not
otherwise acted on).

### 4.2 Column-by-column comparison against the target data model

Target: `docs/product/08_Database_Architecture.md §5.4` + `02_EMPLOYEE_DATA_MODEL.md §2` section J +
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C ("Employee Compensation").

| Column | Live? | Target says | Verdict |
|---|:--:|---|---|
| `id`, `company_id`, `employee_id`, `effective_from`, `effective_to`, `created_at`, `updated_at`, `deleted_at`, `version` | Yes | Standard columns, same shape as `employee_assignment`/`employment` | **Sufficient as-is** |
| `annual_ctc_minor` | Yes | `annual_ctc` (doc naming) — live column already follows ADR-0006 (BIGINT minor units) | **Sufficient as-is** — the live column name (`annual_ctc_minor`) is more explicit than the doc's `annual_ctc` and matches the house convention (`grade.min_ctc`/`max_ctc` are also bare `BIGINT`, unsuffixed, by contrast — see §8) |
| `currency` | Yes (`CHAR(3)`, default `'INR'`) | Not named in Doc 08 §5.4's column list at all (Doc 08 assumes one company-wide currency, same as `grade.min_ctc`/`max_ctc`'s "no per-row currency" note, `organisation/models.py` Grade docstring) | Live table is **more complete** than the target doc here, not less — kept as-is, no action needed |
| `salary_structure_id` | **No** | Doc 08 §5.4: references a `salary_structure` table (Payroll's own catalogue, FR-PAY-003) | **NOT ADDED** — `salary_structure`/`salary_structure_component` tables do not exist anywhere in this codebase (grep confirms zero results); FR-PAY-003 is explicitly Payroll-owned (`docs/product/17 §5`, not in Employee's aggregate per `00_EMPLOYEE_AUDIT.md §6`). Adding a nullable FK to a table that doesn't exist isn't possible — same reasoning E-04 already applied to `cost_centre_id` (`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §6`, "no FK — no `cost_centre` table exists"). |
| `monthly_gross` | **No** | Doc 08 §5.4 | **NOT ADDED** — derivable from `annual_ctc_minor / 12` with no additional business rule stated anywhere; no document requires it be *stored* rather than computed at read time. Storing it would introduce a can-go-stale derived column with no documented invalidation rule. Deferred, not a gap. |
| `revision_type` | **No** | Doc 08 §5.4: `(JOINING/ANNUAL/PROMOTION/CORRECTION/MARKET)` — the only place in any document this exact enum appears, fully specified, no ambiguity (unlike `employment.status`, which needed its own decision document, `07_EMPLOYMENT_STATUS_DECISION.md`) | **ADD** — fully specified, zero cross-module dependency, directly required by FR-EMP-012 ("optional compensation revision" as part of promotion) and by the API plan's own field list (`03_EMPLOYEE_API_PLAN.md §2.3`: "`revision_type`, `revision_reason` required"). See §18. |
| `revision_reason` | **No** | Doc 08 §5.4, free text | **ADD** — same reasoning as `revision_type`. See §18. |
| `approved_by` | **No** | Doc 08 §5.4 | **NOT ADDED** — no approval-routing engine exists (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part G item 8: "store the field now (E-04/E-06); enforce once the approval-routing engine ships"). E-04 did **not** store `approval_request_id`-equivalent fields either — it simply didn't build the approval-adjacent columns at all rather than storing an unenforceable field (confirmed: `employee_assignment` has no `approved_by`/`approval_request_id` column live today). This plan follows the same precedent: do not add columns for a workflow that doesn't exist and has no defined trigger. |
| `approval_request_id` | **No** | Doc 08 §5.4 | **NOT ADDED** — same reasoning as `approved_by`, directly above. |
| `is_arrears_processed` | **No** | Doc 08 §5.4 | **NOT ADDED** — Payroll-owned (FR-PAY-010, "Arrears engine... detects retrospective salary revisions"); Payroll doesn't exist. No document specifies what "processed" means without a Payroll run to process it against. Storing an always-`false`, never-transitioned flag is worse than not storing it (a stale `false` looks like a documented invariant when it is actually just "nothing has ever set this"). |
| `employee_compensation_component` (child table) | **No** | Doc 08 §5.4: `(compensation_id, salary_component_id, amount, percentage, formula_override, is_monthly)` | **NOT ADDED** — depends on `salary_component`/`salary_structure` (Payroll's own catalogue, FR-PAY-001/003), which don't exist. A single `annual_ctc_minor` figure with no component breakdown is exactly what the live table already supports and is sufficient for a correct CTC history; component-level breakdown is meaningless without Payroll's salary-structure engine to interpret it. |

### 4.3 Conclusion

**No migration is structurally required** — the live table already satisfies the locked
architecture record's own field list for Compensation (Part C: "`annual_ctc_minor`, `currency`,
..., `effective_from`/`effective_to`"; `revision_type`/`revision_reason` are listed there too, so
one small additive migration is still the right call — see §18 for the exact, minimal DDL). This
mirrors E-05's own precedent exactly: a fully-specified single-purpose migration, not a large
schema rewrite (`16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md §4`: "One new column...
nullable... No new index").

---

## 5. Target Data Model

Per `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C ("Employee Compensation") — the locked position,
unchanged by this plan:

- **Purpose.** Pay, effective-dated independently of Assignment — a raise without a transfer, or a
  transfer without a raise, are both representable without coupling the two tables.
- **Belongs here (this slice's scope).** `annual_ctc_minor`, `currency`, `revision_type`,
  `revision_reason`, `effective_from`/`effective_to`.
- **Belongs here (deferred, per §4.2).** `salary_structure_id`, `monthly_gross`, `approved_by`,
  `approval_request_id`, `is_arrears_processed`, component breakdown.
- **Does NOT belong here.** PF/ESI amounts (Statutory, E-07, not yet built), bank account (Bank,
  E-08, not yet built), org placement (Assignment, E-04, already built).
- **Relationship to Employee.** 1:N, keyed on `employee_id` directly — **not** `employment_id`, the
  same load-bearing rehire-correctness detail as Assignment (Part B3/C, reconfirmed live: the only
  FK on the table today is `employee_compensation_employee_id_fkey`).
- **Effective-dated?** Yes — GiST exclusion constraint already live (§4.1).
- **Survives exit?** Last row closed at exit date; remains historically queryable (needed for
  full-and-final settlement and any later payroll audit).
- **Survives rehire?** Old rows remain; a new row opens at the rehire's new CTC. No CTC carries
  forward by default — set fresh, exactly like a new hire's first compensation row (Part D's worked
  example, quoted in full in §10 below).

---

## 6. Effective-Dating Model

E-06 reuses the exact pattern E-04 (`EmployeeAssignmentRepository`/`EmployeeAssignmentService`) and
E-03 (`EmploymentRepository`) both already implement — no new design work, a mechanical mirror.

**The exact precedent** (`apps/api/src/hrms/modules/employee/repository.py:236-253`,
`EmployeeAssignmentRepository.get_assignment_as_of`):

```python
async def get_assignment_as_of(
    self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
) -> EmployeeAssignment | None:
    """The assignment row (at most one, by `employee_assignment_no_overlap`) covering
    `as_of` — the shared cross-module contract other modules (Attendance/Leave/Payroll)
    will later call via `employee.service`
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/E)."""
    stmt = select(EmployeeAssignment).where(
        EmployeeAssignment.company_id == company_id,
        EmployeeAssignment.employee_id == employee_id,
        EmployeeAssignment.deleted_at.is_(None),
        EmployeeAssignment.effective_from <= as_of,
        or_(
            EmployeeAssignment.effective_to.is_(None),
            EmployeeAssignment.effective_to >= as_of,
        ),
    )
    return (await session.execute(stmt)).scalar_one_or_none()
```

E-06 must add the exact mirror, `EmployeeCompensationRepository.get_compensation_as_of(session, *,
company_id, employee_id, as_of) -> EmployeeCompensation | None`, with `EmployeeAssignment`
substituted for `EmployeeCompensation` and no other logic change — this is precisely what
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7 calls for ("`get_compensation_as_of(employee_id,
date)`... extendable to `get_statutory_as_of`/`get_bank_as_of`... not a generic framework").

The write pattern (insert-never-update-in-place) also mirrors
`EmployeeAssignmentRepository.close_assignment` (`repository.py:285-312`) exactly:
1. Read the current row (`effective_to IS NULL`) for the employee, if any.
2. `close_compensation`: `UPDATE ... SET effective_to = :new.effective_from - 1 day WHERE id =
   :current_row_id AND version = :expected_version RETURNING ...` — the one allowed edit, touching
   only `effective_to`.
3. `INSERT` a new row with the new `annual_ctc_minor`/`currency`/`revision_type`/`revision_reason`.

Steps 2-3 in the same transaction, mirroring
`EmployeeAssignmentService.create_assignment` (`service.py:623-790`) — see §9 for the exact method
this plan proposes.

Read shapes (current / as-of / full-history) are identical to `EmployeeAssignmentRepository`'s three
read methods (`get_current_assignment`, `get_assignment_as_of`, `list_assignments`) — E-06 needs
`get_current_compensation`, `get_compensation_as_of`, `list_compensations`, mirrored 1:1.

---

## 7. Business Rules

| Rule | Source | Required in E-06? | Reason |
|---|---|:--:|---|
| A compensation revision is always an insert of a new row; the previous row is closed the day before | FR-EMP-003 (`docs/product/17:140`, generalizes to "every assignment change" but the same ADR-0003 discipline applies identically here per `02_EMPLOYEE_DATA_MODEL.md §1.2`) | **Yes** | Load-bearing effective-dating rule, already the pattern for Assignment/Employment |
| Two overlapping "current" compensation rows for one employee are structurally impossible | `employee_compensation_no_overlap` GiST exclusion constraint, already live (§4.1) | **Yes** (already DB-enforced, service must translate `IntegrityError`) | Direct DB backstop, mirrors `AssignmentDatesOverlapError` |
| A compensation row requires a covering employment episode | No document states this for Compensation specifically — inferred by direct analogy to E-04's own rule for Assignment (`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §14.1`, itself derived from Part D's worked timeline: "Nothing to assign or pay during a gap, so nothing exists") | **ENGINEERING DECISION — Yes**, following the Assignment precedent exactly (§9, §17) | Not a DB constraint (no `employment_id` FK exists on `employee_compensation`, matching Assignment's own reasoning); enforced only in the service layer |
| Backdated changes are blocked past the last finalised payroll period unless the actor holds `PAYROLL.BACKDATE_OVERRIDE` | FR-EMP-004 (`docs/product/17:141`), `02_EMPLOYEE_DATA_MODEL.md §1.4` | **No — not implementable** | Payroll doesn't exist (same known limitation E-04/E-05 both carry forward: "any past `effective_from` is currently accepted without a lock-period check", `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §17` item 5) |
| Future-dated changes are permitted, no activation job needed | FR-EMP-005, `02_EMPLOYEE_DATA_MODEL.md §1.4` | **Yes** (falls out of the as-of-date read pattern automatically, no extra code) | Same as Assignment/Employment — the as-of-date query already returns the correct row for any date |
| Promotion may include an "optional compensation revision" in the same workflow as designation/grade change | FR-EMP-012 (`docs/product/17:149`) | **No — not a single combined transaction in this slice** | No document specifies the combined-transaction shape; E-04's `create_assignment` and this slice's `create_compensation` remain two separate write operations, exactly as Assignment and Employment already are two separate services with no cross-calling. A caller (a future UI workflow, or E-09) issues both calls; this is a UX-layer sequencing decision, not a service-layer coupling requirement — no document asks for atomicity between the two writes. Flagged as an **ENGINEERING DECISION** (§17), not silently narrowed. |
| `EMPLOYEE.VIEW_COMPENSATION` gates the entire sub-resource, absent not masked, for a caller without it | `03_EMPLOYEE_API_PLAN.md §2.3` ("Absent entirely from the response... matching the Directory screen spec's 'absent, not disabled' rule"), `docs/product/19 §6` RESTRICTED tier | **Yes** | Directly named requirement, not inferred |
| `revision_type`/`revision_reason` required on every write (not just revisions) | `03_EMPLOYEE_API_PLAN.md §2.3`: "`revision_type`, `revision_reason` required" | **Yes**, with one refinement — **ENGINEERING DECISION REQUIRED**: whether the very first compensation row (no current row to "revise") should require `revision_type=JOINING` (matching Doc 08 §5.4's own enum, which names `JOINING` as a value) rather than being exempted the way Assignment exempts `branch_id`/etc. only on the *first* row. This plan's recommendation: **always required**, using `JOINING` for the first row — unlike Assignment's org-placement fields (which have nothing to default to on first placement), `revision_type` has a documented value (`JOINING`) that is always correct for a first row, so there is no reason to make it conditionally optional the way Assignment's reference fields are. See §17. |
| Grade's `min_ctc`/`max_ctc` band constrains what CTC can be entered for an employee at that grade | **UNDOCUMENTED** — no document anywhere states this enforcement (§8, exhaustively checked) | **No** | See §8 — Grade's CTC fields are informational bands with no cross-table enforcement mechanism documented or built anywhere in this codebase |
| Approval routing on a compensation revision | Doc 08 §5.4 names `approved_by`/`approval_request_id` columns; no workflow engine exists | **No** | `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part G item 8 — explicitly deferred, store nothing until the engine exists (this plan goes one step further than "store the field": it doesn't even add the column, per §4.2, since an unenforceable stored field with no write path is worse than not storing it) |
| Rehire: new compensation row opens fresh, nothing carries forward automatically | `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C ("Employee Compensation" → "Survives rehire?"), Part D worked example | **Yes** — but see §17: unlike Assignment, this plan recommends **not** offering a "carry forward if omitted" semantic for `annual_ctc_minor`/`currency` at all (§9) | A raise/compensation figure carrying forward silently by omission is a materially different risk profile than an org-placement field carrying forward (a stale salary figure is a payroll-correctness and compliance risk; a stale department is not) |

---

## 8. Money/CTC Rules

**Representation.** `annual_ctc_minor BIGINT NOT NULL` + `currency CHAR(3) NOT NULL DEFAULT 'INR'`
— already live, already follows ADR-0006 ("money as integer minor units", cited throughout
`00_EMPLOYEE_AUDIT.md §4`, confirmed in `docs/modules/employee/00_EMPLOYEE_AUDIT.md §3.4`: "Money
already follows ADR-0006"). No change needed. This is the same representation `Grade.min_ctc`/
`max_ctc` use (`BigInteger`, `apps/api/src/hrms/modules/organisation/models.py:191-192`), and the
same the closest sibling pattern (Grade's own CTC-range validation, §8 below) already established
in this codebase.

**Rounding/precision.** No document specifies a rounding rule for `annual_ctc_minor` beyond "integer
minor units" — since the column is `BIGINT` (whole minor units, e.g. paise), there is no fractional
representation to round; any UI-side amount-to-minor-unit conversion (e.g. rupees → paise) is a
frontend/schema-validation concern, not a stored-precision concern. Not applicable to this slice
(no frontend, §14).

**Currency.** `CHAR(3)` default `'INR'`, matching ISO 4217. No document states whether a company can
ever have a compensation row in a currency other than its own configured currency (Grade's own
`min_ctc`/`max_ctc` have **no per-row currency at all** — "Company owns a single configured
currency", `organisation/models.py:178-179` docstring) — this is a genuine inconsistency between
Grade (single company-wide currency, no column) and the live `employee_compensation` table (a
per-row `currency` column, defaulting to `INR` but not constrained to match a company setting).
**UNDOCUMENTED**: no document states whether `employee_compensation.currency` must match any
company-level currency setting, or whether multi-currency compensation (e.g. an expatriate paid in
USD) is intended. This plan's recommendation (**ENGINEERING DECISION**, safe default): accept the
live column as-is (any ISO-4217-shaped 3-letter code, no cross-check against a company setting) —
building a same-currency-as-company validation would be inventing a rule no document states, the
same restraint E-04 exercised for cross-entity consistency checks (`09_EMPLOYEE_ASSIGNMENT_...
_PLAN.md §14.4`: "do not build this check... if product wants it, it should be scoped as a named
requirement"). Flagged for product awareness, not blocking.

**Grade `min_ctc`/`max_ctc` relationship — informational, not enforced.** Exhaustively checked
(`grep` across `docs/product`, `docs/modules/employee`, `docs/modules/grade` for
"grade.*ctc|ctc.*grade|band.*enforc|within.*grade" this session, zero enforcement hits found).
Findings:
- `docs/modules/grade/01_Grade_Module.md:141`: "No `RESTRICTED`-classified fields — `min_ctc`/
  `max_ctc` are compensation *bands*" — describes them as informational reference data on Grade
  itself, not as a constraint applied elsewhere.
- `docs/product/17_SRS_Phase1_Core_Modules.md:98` (FR-ORG-007): "Grade/Band: code, level, min/max
  CTC, leave entitlement override, notice period override, probation override, approval-limit
  override" — lists CTC as one of several *override* fields available on Grade for other modules to
  *consult*, but no FR-EMP-* or FR-PAY-* requirement states that Employee Compensation's
  `annual_ctc_minor` must fall within the employee's current grade's `[min_ctc, max_ctc]` range.
- Live schema: no `CHECK` constraint, no FK, no trigger tying `employee_compensation` to `grade` in
  any way (verified via `\d+ employee_compensation` and `\d+ grade`, §4.1 and below).
- Live `Grade` ORM model (`organisation/models.py:174-198`) has no cross-reference to
  `employee_compensation` and no validation method beyond `_validate_ctc_range` (`min_ctc <=
  max_ctc`, `organisation/service.py:1324-1327`) — a **self**-consistency check on Grade's own two
  columns, not a check against any employee's actual compensation.
- `Grade.approval_limit` is similarly undocumented beyond existing as a column — no document states
  what it gates (most plausibly a future compensation-approval-routing threshold, but this is this
  plan's own inference, not a sourced requirement).

**Conclusion: PRODUCT DECISION REQUIRED if enforcement is ever wanted, but not a blocker for E-06.**
This plan's recommendation (**ENGINEERING DECISION**, following the precedent E-04 set for
cross-entity checks the organisation module doesn't enforce on itself either, §14.4 of the
Assignment plan): **do not validate `annual_ctc_minor` against the employee's current grade's
`min_ctc`/`max_ctc` band in E-06.** If product wants this enforced, it should be a named,
documented requirement (with an explicit decision on whether it's a hard block or a soft warning,
and what happens when `grade_id` is null on the current assignment, or when `min_ctc`/`max_ctc` are
themselves null on the grade — both are common per the live nullable schema), not inferred silently
here.

---

## 9. Revision Types

**Authoritative enum found**: `docs/product/08_Database_Architecture.md:242` — `revision_type
(JOINING/ANNUAL/PROMOTION/CORRECTION/MARKET)`. This is the **only** place any `revision_type` value
set appears in any document read for this plan; no conflict was found (unlike `employment.status`,
which needed its own decision document because two different values were proposed in different
places — here there is exactly one proposal, from exactly one document, never contradicted).

| Value | Meaning (inferred from name, not further elaborated by any document) |
|---|---|
| `JOINING` | The employee's first compensation row, set at hire (or rehire) |
| `ANNUAL` | A regular annual increment cycle |
| `PROMOTION` | A revision tied to a promotion (FR-EMP-012's "optional compensation revision") |
| `CORRECTION` | A data-entry fix to a previously-entered figure |
| `MARKET` | An off-cycle market-adjustment revision |

No document elaborates further (e.g. which of these require `EMPLOYEE.UPDATE_COMPENSATION` vs. some
narrower permission — the RBAC catalogue does not subdivide `.UPDATE_COMPENSATION` by
`revision_type`, so this plan does not invent a subdivision). Validated at the Pydantic layer as a
`Literal` type, matching the exact precedent `employment.status` (`EMPLOYMENT_STATUS_VALUES`,
`schemas.py:151`) and `change_type` (`ASSIGNMENT_CHANGE_TYPE_VALUES`, `schemas.py:239-249`) both
already established — not a lookup table, not a PG enum type (consistent house convention per
`00_EMPLOYEE_AUDIT.md §4`: "enums as lookup tables, not PG enum types" is the documented target, but
every shipped slice so far has actually used a `CHECK`-constrained `VARCHAR` + Pydantic `Literal`
instead — `employment.status`, `employee_assignment.change_type`/`work_location_type` — so this plan
follows the **actually-shipped** precedent, not the aspirational doc rule, exactly as
`12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §17` item 7 already flagged for `change_type`).

---

## 10. Rehire Behaviour

Walking the full lifecycle, citing `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D's own worked
example (`EMP-00125`, joins 2027-06-01, resigns 2030-09-30, rejoins 2034-02-01) and applying E-06's
compensation-specific consequences:

1. **Initial hire (2027-06-01).** `employee` row created. `employment #1` created (`ACTIVE`).
   `employee_assignment #1` created. **`employee_compensation #1` created**
   (`effective_from=2027-06-01`, `effective_to=NULL`, `revision_type=JOINING`, initial
   `annual_ctc_minor`). All four rows share `employee_id`, none references `employment_id` — the
   `employee_id`-keyed pattern already locked (Part B4/C) and already the live FK shape (§4.1, §5).

2. **Compensation revision, independent of assignment (e.g. 2029-01-01).** `employee_compensation
   #1.effective_to = 2028-12-31` (closed). `employee_compensation #2` created
   (`effective_from=2029-01-01`, `revision_type=ANNUAL` or `MARKET`, new CTC). **No
   `employee_assignment` row is touched** — Part D's own text: "Independent of the assignment row
   above — no assignment row is touched by a comp-only change, and vice versa." This is the direct
   behavioural proof that Compensation and Assignment are separate child tables, not a combined
   "current state" row.

3. **Exit (2030-09-30).** `employment #1.exit_date/status → TERMINATED`. `employee_assignment
   #N.effective_to = 2030-09-30` (closed). **`employee_compensation #N.effective_to = 2030-09-30`**
   (closed — no open compensation row remains, mirroring Part D's exact text: "no open compensation
   row remains"). **Known limitation this plan inherits from E-04's own precedent**: nothing in
   `EmploymentService.terminate_employment` (E-03, already complete, not modified by this plan)
   auto-closes the compensation row, exactly as it does not auto-close the assignment row today
   (`12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §12`: "the pre-exit assignment row is not
   automatically closed when its covering employment terminates... It remains open... until the
   [next] call closes it"). E-06 will exhibit the **identical** limitation for compensation, for the
   identical reason (no slice has modified `EmploymentService`, by design — each slice's own service
   only writes to its own table). Documented here explicitly, not silently inherited.

4. **Gap (2030-10-01 → 2034-01-31).** No `employee_compensation` row exists (nothing to pay). This
   is expected, not a data gap to "fill" — same reasoning as Assignment's own gap behaviour
   (Part D: "Nothing to assign or pay during a gap, so nothing exists").

5. **Rejoins (2034-02-01).** Same `employee` row (`employee_code` unchanged). `employment #2`
   created (`is_rehire=true`, `previous_employment_id` set). `employee_assignment #4` created fresh.
   **`employee_compensation #3` created fresh** (`effective_from=2034-02-01`,
   `revision_type=JOINING` — the same value as the very first hire's row, since from this row's own
   perspective it *is* a joining event for this employment episode; `05_EMPLOYEE_ARCHITECTURE_
   DECISIONS.md` Part D: "freshly-entered CTC... No CTC carries forward by default — it is set
   fresh, exactly like a new hire's first compensation row"). Nothing about the pre-exit CTC is
   read, inferred, or defaulted — the rehire's compensation is a completely independent data-entry
   act, gated by the same `NoActiveEmploymentError`-style "must have a covering employment episode"
   rule Assignment already enforces (§9, mirroring `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md
   §14.1`).

**Consequence for E-06's design, mirroring Assignment's own §4 finding exactly**: a rehire's first
compensation row requires no special-case code — it is handled by the exact same "no current row
exists" branch as any employee's very first compensation row. The service does not need to
distinguish "first ever compensation" from "first compensation of a new episode after a gap."

---

## 11. API Plan

Sub-resource routes under `/v1/employees/{employee_id}/compensation`, per `03_EMPLOYEE_API_PLAN.md
§2.3` — verified consistent with the `/assignments` (§2.2) and shift-assignment (folded into the
same endpoint) precedent already shipped. **One documented shape conflict, resolved**: the original
`docs/product/09_API_Standards.md §3.2` sketch shows compensation nested inside a single monolithic
`POST /employees` body with a nested `{"amount": ..., "currency": ...}` object
(`docs/product/09_API_Standards.md:295-296`) — this was written before the sub-resource API plan
(`03_EMPLOYEE_API_PLAN.md`) existed and before E-04/E-05 shipped their own flat, DB-column-named
field shape (`AssignmentCreate.branch_id`, not a nested object). This plan follows the **more
specific, more recently reasoned, and already-precedented** source
(`03_EMPLOYEE_API_PLAN.md` + the shipped `AssignmentCreate` shape), exactly the resolution method
`03_EMPLOYEE_API_PLAN.md §2.4` itself already used for an analogous conflict (`PATCH` vs. insert-only
for Statutory/Bank): flat fields (`annual_ctc_minor: int`, `currency: str`) matching the live DB
columns directly, **not** a nested `{amount, currency}` object.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/compensation` | `EMPLOYEE.VIEW_COMPENSATION` | Full effective-dated history, ordered by `effective_from`, or `?as_of=YYYY-MM-DD` for the single covering row. **Absent entirely (empty response body / 403, not masked fields) for a caller without this permission** — `03_EMPLOYEE_API_PLAN.md §2.3`. |
| GET | `/v1/employees/{employee_id}/compensation/{compensation_id}` | `EMPLOYEE.VIEW_COMPENSATION` | Single row by id — engineering addition, mirrors `Assignment`'s and `Employment`'s own single-item GET (not explicitly named in the API plan but consistent with its shape, same reasoning `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §10` used) |
| POST | `/v1/employees/{employee_id}/compensation` | `EMPLOYEE.UPDATE_COMPENSATION` | Closes the current row (if any), inserts a new one. Body: `effective_from`, `annual_ctc_minor`, `currency`, `revision_type`, `revision_reason` (all required, §7/§9 — **no partial/carry-forward semantics**, unlike Assignment, §17) |

### Request body (`CompensationCreate`, `extra="forbid"`)

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `effective_from` | date | yes | Must be strictly after the current row's `effective_from`, if one exists (mirrors `InvalidEffectiveFromError`) |
| `annual_ctc_minor` | int (`>= 0`) | **yes, always** | No carry-forward — every write states the full new CTC explicitly (§17) |
| `currency` | string, 3 chars | **yes, always** | No carry-forward; no cross-check against a company-level currency (§8) |
| `revision_type` | `JOINING`\|`ANNUAL`\|`PROMOTION`\|`CORRECTION`\|`MARKET` | yes | §9 |
| `revision_reason` | string | yes | Free text, matches `03_EMPLOYEE_API_PLAN.md §2.3`: "`revision_type`, `revision_reason` required" |

### Error codes (mirroring Assignment's exact shape, `11_EMPLOYEE_ASSIGNMENT_API.md`)

| HTTP | Code | Cause |
|---|---|---|
| `404` | `NOT_FOUND` | Employee does not exist or belongs to another tenant |
| `409` | `NO_ACTIVE_EMPLOYMENT` | `effective_from` falls on a date with no covering employment episode (§7, engineering decision) |
| `422` | `INVALID_EFFECTIVE_FROM` | `effective_from` is not strictly after the current row's `effective_from` |
| `422` | `COMPENSATION_VERSION_REQUIRED` | A current row exists but `If-Match` was omitted (new exception, mirrors `AssignmentVersionRequiredError`) |
| `409` | `STALE_RESOURCE` | `If-Match` does not match the current row's `version` |
| `409` | `COMPENSATION_DATES_OVERLAP` | The `employee_compensation_no_overlap` GiST exclusion constraint rejected the insert (race-condition backstop, mirrors `AssignmentDatesOverlapError`) |
| `403` | `PERMISSION_DENIED` | Caller lacks `EMPLOYEE.UPDATE_COMPENSATION` (or `.VIEW_COMPENSATION` for GET) |
| `422` | (FastAPI validation) | `extra="forbid"` — unknown/extra fields rejected |

`If-Match` semantics identical to Assignment: required only when the employee already has a current
compensation row to close (the version checked belongs to the row being closed); omitted entirely
for the employee's very first compensation row.

**What this API does not do** (mirrors `11_EMPLOYEE_ASSIGNMENT_API.md`'s own "What this API does
not do" section): no bulk/batch compensation endpoint; no endpoint to close a compensation row
without opening a new one; no `salary_structure_id`/component breakdown field (§4.2); no
approval-routing field or gate (§7); no `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope narrowing —
gated only on the coarse `EMPLOYEE.VIEW_COMPENSATION` grant (E-10's scope, not E-06's, exact
precedent `EMPLOYEE.VIEW`/`.VIEW_ALL` already set).

---

## 12. Permission/RBAC Plan

Cross-checked against the 14-code catalogue (`docs/product/19_RBAC_and_Permission_Matrix.md §3.1`,
lines 45-46) and the gap `permissions.py`'s own module docstring already flags (line 36: "The
remaining codes not yet added (`UPDATE_SENSITIVE`, `VIEW_COMPENSATION`, `.VIEW_DOCUMENTS`,
`.CONFIRM`, etc.) belong to later slices (E-02/E-06/...)").

| Code | Already named in catalogue? | Action this slice |
|---|:--:|---|
| `EMPLOYEE.VIEW_COMPENSATION` | Yes (`19_RBAC...md:45`) | **Add** — gates both GET routes |
| `EMPLOYEE.UPDATE_COMPENSATION` | Yes (`19_RBAC...md:46`) | **Add** — gates the POST route |

**No new code beyond the catalogue is required** — unlike E-03's `EMPLOYEE.TERMINATE` (which had no
catalogue entry at all and required the resolution pattern `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
A9 established: "termination is irreversible... the same reasoning applies", `permissions.py:13-24`)
and E-06's own earlier-flagged `.VIEW_STATUTORY`/`.VIEW_BANKING` gap (A9, not this slice's concern),
**both codes E-06 needs already exist in the documented 14-code catalogue verbatim** — no naming
decision, no gap-resolution reasoning required. This is the simplest permission addition of any
slice so far.

Both codes should be added to `EMPLOYEE_PERMISSIONS` in `permissions.py` following the exact list
shape already established (`(CODE, "EMPLOYEE", "description")` tuples, `permissions.py:50-57`).
Granted to `COMPANY_ADMIN` automatically at both bootstrap-seed time and live-registration time —
**no code change needed** in `seed/bootstrap.py` or `organisation/service.py`, since both already
iterate `EMPLOYEE_PERMISSIONS` dynamically (confirmed working for every prior slice's new codes,
`12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §9`: "picked up automatically").

`test_registration_flow.py`'s permission-set assertion will need the same one-line update every
prior slice's report notes making (`06_..._REPORT.md §3`, `08_..._REPORT.md §3`,
`12_..._REPORT.md §3`) — the only test file outside `modules/employee/` this slice should touch.

---

## 13. Audit/Security Plan

**Write-path (`AuditService`).** Exact reuse of `AuditService.record(session, *, company_id,
actor_user_id, action, entity_type, entity_id, before, after, ip, user_agent)`
(`apps/api/src/hrms/core/audit/service.py:9-36`) — no change to `AuditService` itself. New action
name, following the exact convention `00_EMPLOYEE_AUDIT.md §13.4` already recommended and every
slice has followed: **`COMPENSATION_REVISED`** — a single event (not fragmented per `revision_type`,
matching `ASSIGNMENT_CHANGED`'s own "single event, detail carried in the `after` snapshot" pattern,
`00_EMPLOYEE_AUDIT.md §13.4`: "`employee_compensation`: `COMPENSATION_REVISED`" is the document's
own literal, pre-named recommendation — not invented by this plan). `before` = the closed row's
snapshot (or `None` for an employee's first compensation row, matching `ASSIGNMENT_CHANGED`'s own
`before=None` convention for a first assignment); `after` = the new row's full snapshot including
`revision_type`/`revision_reason`.

**Read-path (`sensitive_access_log`).** `docs/product/07_Backend_Architecture.md §9`: "Read-path
(sensitive access): `Depends(require_permission(...))` for a `RESTRICTED`-classified field (Document
19 §6) additionally enqueues a lightweight `sensitive_access_log` write." CTC is explicitly
`RESTRICTED`-classified (`docs/product/19_RBAC_and_Permission_Matrix.md:205`: "CTC, salary
components... Explicit permission only, **always logged**"). `docs/product/08_Database_Architecture.
md:505` names the table's exact column shape (`company_id, actor_user_id, entity_type, entity_id,
fields TEXT[], purpose, occurred_at`), and `docs/product/14_Security_Architecture.md:59-60`
confirms the DB-role hardening (no `UPDATE`/`DELETE` grant) that would apply to it once built.
**This table does not exist anywhere in this codebase today** (confirmed: `grep -rn
sensitive_access_log apps/api/src apps/api/alembic` → zero results this session) — and
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A9 already locked its build timing: "**Build now,
scoped to E-10 (not E-01)**" — this decision was made when E-01 was being planned and explicitly
named **E-10**, not E-06, as the slice that builds it. Nothing in any subsequent document
(`01_EMPLOYEE_MODULE_PLAN.md` E-06's own row, `03_EMPLOYEE_API_PLAN.md §2.3`) reopens or moves this
timing. **This plan does not build `sensitive_access_log` in E-06** — it is out of scope, per the
already-locked decision, and should not be pulled forward the same way `00_EMPLOYEE_AUDIT.md §18`
warns against pulling BR-14 forward into an unrelated slice ("resist... it is a separate... decision"
— the identical discipline applies here to `sensitive_access_log`/E-10). Flagged explicitly in §21
(Explicitly Deferred Scope), not silently dropped.

**RESTRICTED-field response shaping.** Per the already-established E-01 precedent for
`pan_number_enc`/`aadhaar_number_enc`/`uan_number` (`06_EMPLOYEE_FOUNDATION_IMPLEMENTATION_REPORT.md
§7`: "not masked, not nulled, simply never serialized") — but Compensation's case differs: the
*entire sub-resource* is absent for a caller without `EMPLOYEE.VIEW_COMPENSATION` (§7, §11), not an
individual field masked within an otherwise-visible response. This is a stronger form of the same
principle, already the explicit design (`03_EMPLOYEE_API_PLAN.md §2.3`).

---

## 14. Frontend Scope

**None.** Confirmed by three independent sources:
1. `01_EMPLOYEE_MODULE_PLAN.md` §2 "E-06" — "Frontend: Compensation tab
   (`04_EMPLOYEE_UX_PLAN.md §2`, permission-gated absent)" is listed, but every prior slice's actual
   closeout report (E-01 through E-05) deferred **all** frontend work to E-09, on the explicit
   grounds that no `Tabs`/`Timeline`/`PermissionGate`/`DataTable` primitives exist yet
   (`00_EMPLOYEE_AUDIT.md §14.5`) and building throwaway one-off UI ahead of that shared
   infrastructure is the exact risk `00_EMPLOYEE_AUDIT.md §18` flags.
2. `find apps/web/src -iname "*employee*"` → **zero results**, verified this session — no Employee
   frontend scaffolding of any kind exists to extend.
3. `04_EMPLOYEE_UX_PLAN.md §2` itself frames the Compensation tab as part of the shared 360°-profile
   tab structure (built in E-09), not a standalone screen E-06 would build in isolation.

**This plan's recommendation, following E-01 through E-05's unbroken precedent exactly**: E-06 is
backend-only. No `apps/web/` file should be touched by this slice's implementation.

---

## 15. Dependencies

| Dependency | Hard or optional? | Reason |
|---|:--:|---|
| E-01 (Employee Foundation) | **Hard** | `employee_id` FK target must exist — already shipped |
| E-03 (Employment Lifecycle) | **Hard** | The "covering employment episode" rule (§7, §17) needs `EmploymentRepository.get_employment_as_of` — already shipped, already the exact method Assignment reuses |
| E-04 (Employee Assignment) | **Not required** | `01_EMPLOYEE_MODULE_PLAN.md` §4's own dependency graph shows E-06 branching directly off E-03, parallel to E-04/E-05, not depending on either. Confirmed no compensation logic reads `employee_assignment` anywhere in this plan. |
| E-05 (Shift Assignment) | **Not required** | Same reasoning — no shift-adjacent logic in Compensation |
| Grade (organisation module) | **Optional, not integrated** | `grade_id` lives on `employee_assignment`, not `employee_compensation`; Grade's `min_ctc`/`max_ctc` are not read or enforced by this slice (§8) |
| Designation, Legal Entity, Branch, Department | **None** | No column on `employee_compensation` references any of these |
| Shift Rules | **None** | No relationship |
| Payroll (future) | **Consumer, not a dependency** | Payroll will call `get_compensation_as_of` once it exists (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part F: "What compensation was effective during period X? ... Yes — table live, effective-dating pattern already enforced"); E-06 does not depend on Payroll existing |
| Statutory (E-07, future) | **None, parallel** | No relationship — Statutory is a separate effective-dated table, not yet built |
| Banking (E-08, future) | **None, parallel** | Same |
| `salary_structure`/`salary_component` (Payroll's catalogue, future) | **Deferred, §4.2** | `salary_structure_id` is not added this slice specifically because this table doesn't exist |
| Approval-routing engine (future) | **Deferred, §7, §13** | `approved_by`/`approval_request_id` not added this slice |
| `sensitive_access_log` (E-10, future) | **Deferred, §13** | Already-locked timing, not this slice's scope |

---

## 16. Product Decisions Required

Genuine product-sign-off items only — items with a safe engineering default are in §17 instead.

### PD-1: Should `annual_ctc_minor` be validated against the employee's current grade's `min_ctc`/`max_ctc` band?

- **Question.** When creating a compensation row, should the service reject (or warn on) a CTC
  outside the employee's current-assignment grade's `[min_ctc, max_ctc]` range?
- **Options.**
  1. No enforcement (this plan's default, §8) — Grade's CTC fields remain purely informational.
  2. Hard block (`422`) when both bounds are set and the CTC falls outside them.
  3. Soft warning surfaced to the caller (not a rejection) — requires a response-shape decision this
     plan does not design.
- **Evidence.** No document states any of the three; `grade.min_ctc`/`max_ctc` are described only as
  "compensation bands" (`docs/modules/grade/01_Grade_Module.md:141`) with no consuming rule found
  anywhere (§8 exhaustive check).
- **Recommendation.** Option 1 (no enforcement), because: (a) it is the only option requiring zero
  new design work and is directly precedented by E-04's own declined cross-entity check
  (`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §14.4`); (b) `grade_id`/`min_ctc`/`max_ctc` are
  all nullable, so any enforcement rule must first answer several unstated sub-questions (does a
  null grade skip the check? does a null bound skip the check? is it enforced only at creation or
  also retroactively if Grade's band changes later?) that no document resolves; (c) it does not
  block Payroll or any other downstream consumer, since Grade's bands remain queryable independently
  regardless of whether Compensation cross-checks them.
- **Consequences if deferred (option 1 shipped now, revisited later).** Zero — adding the check
  later is a pure service-layer addition with no schema change and no migration, since both tables
  and both columns already exist. Low cost to defer, unlike a schema decision.
- **This plan proceeds with option 1.** If product answers before implementation starts, revise
  §7/§9 accordingly; if not, ship option 1 and record the decision in E-06's own closeout report
  exactly as every prior slice has done for its own open items.

**This is the only item in this document classified as PRODUCT DECISION REQUIRED with no equally-
safe alternative baked in as the plan's own default.** Every other open question in this plan (§17)
has a recommended resolution this plan adopts outright, following a directly-precedented pattern
from an already-shipped sibling slice — the same standard `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_
PLAN.md §"Summary answers"` item 8 used to conclude "no blocking product decision" for E-04. Because
PD-1 has a safe, zero-schema-cost default that this plan adopts, **it does not block
implementation** (see the status line at the end of this document).

---

## 17. Engineering Decisions

Choices safely made from existing codebase patterns — each cites the pattern it follows, per the
same classification discipline `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §14` established.

### 17.1 A compensation row requires a covering employment episode

**Rule**: `create_compensation` requires `EmploymentRepository.get_employment_as_of(employee_id,
as_of=effective_from)` to return a row; otherwise `409 NO_ACTIVE_EMPLOYMENT`.

**Pattern followed**: `EmployeeAssignmentService.create_assignment`'s identical rule
(`service.py:636-640`), itself derived from Part D's worked timeline showing no compensation row can
exist during a gap. Not a DB constraint (no `employment_id` column on `employee_compensation`, by
design, §5) — enforced only in the service layer, same limitation Assignment already documents
(`exceptions.py:138-144`, `NoActiveEmploymentError` docstring).

### 17.2 No carry-forward semantics for `annual_ctc_minor`/`currency`/`revision_type`/`revision_reason`

**Rule**: unlike `AssignmentCreate` (where an omitted field carries forward from the current row,
`service.py:671-697`), `CompensationCreate` requires all four business fields on every write — there
is no "omit to keep the same CTC" shorthand.

**Why this deliberately departs from the Assignment precedent**: Assignment's carry-forward exists
because a transfer that only changes `department_id` shouldn't force the caller to re-state
`branch_id`/`designation_id`/etc. Compensation has no equivalent "only some fields changed" use case
that FR-EMP-012 or the API plan names — every documented `revision_type` (§9) implies the CTC figure
itself is the subject of the write. A caller wanting to record a `CORRECTION`-type revision that
changes only `revision_reason` while leaving `annual_ctc_minor` numerically identical can still do so
by re-stating the same number — this is not a meaningfully worse UX than carry-forward, and avoids
the materially higher risk of a caller *accidentally* omitting `annual_ctc_minor` and silently
carrying forward a stale salary figure into a new effective-dated row (a payroll-correctness risk
Assignment's own fields don't carry). Documented as a deliberate divergence, not an oversight.

### 17.3 `revision_type=JOINING` required (not exempted) on the first compensation row

**Rule**: `CompensationCreate.revision_type` is always required, including on an employee's very
first compensation row (where the caller supplies `JOINING`) — unlike Assignment's
`branch_id`/`department_id`/`designation_id`, which are *conditionally* required only when no
current row exists (`AssignmentFieldsRequiredError`, `service.py:649-656`).

**Why this differs from Assignment's conditional-required pattern**: Assignment's fields are
conditionally required because there is no sensible default value for "which department" on a first
placement — the field must come from somewhere, and carry-forward supplies it after the first row.
`revision_type` has exactly one documented value (`JOINING`, §9) that is unambiguously correct for
every employee's first compensation row — there is no need for conditional-required logic when the
correct value is always the same, known constant. Simpler than Assignment's equivalent handling, not
a divergence in spirit — same "the caller states the true value" principle, applied to a field where
the true first-row value is always knowable in advance.

### 17.4 No combined promotion+compensation-revision transaction

Per §7: FR-EMP-012 names "optional compensation revision" as part of a single promotion *workflow*,
but no document specifies a shared-transaction API shape. This plan keeps `create_assignment` (E-04)
and `create_compensation` (E-06) as two independent service calls with no cross-service coupling —
matching the existing pattern that no slice's service imports another slice's service within the
same module (`EmployeeAssignmentService` does not call `EmploymentService.create_employment`, e.g.;
each service only reads via the other's repository/as-of methods, never writes through it). A future
UI workflow (E-09) or a thin orchestration endpoint can sequence both calls; this plan does not build
that orchestration now, matching E-04's own declined scope for FR-EMP-011's employment-closing half
(`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §1`: "inter-entity transfer's employment-closing
mechanics... is an `Employment`-level operation outside this slice's scope").

### 17.5 Money validation

`annual_ctc_minor: int = Field(ge=0)` — a negative CTC is meaningless; `>= 0` is the only bound any
adjacent pattern in this codebase applies to a money field (Grade's own `min_ctc`/`max_ctc` have no
stated lower-bound validation beyond being `BigInteger` — nullable, no `CHECK`, per §4.1/§8 — so `>=
0` here is this plan's own minimal, uncontroversial addition, not inferred from an existing Grade
rule). `currency: str = Field(min_length=3, max_length=3)` — matches the live `CHAR(3)` column;
no ISO-4217-membership validation is built (no document requires it, and no adjacent pattern in this
codebase validates currency codes against a fixed list anywhere).

### 17.6 Exception naming

New exceptions follow the exact naming/shape convention `exceptions.py` already establishes for
Assignment: `CompensationDatesOverlapError(ConflictError)` (mirrors `AssignmentDatesOverlapError`),
`CompensationVersionRequiredError(ValidationError)` (mirrors `AssignmentVersionRequiredError`),
`InvalidEffectiveFromError` is **reused as-is** (already generic — the existing class's docstring
doesn't name Assignment specifically, and its `field`/`message` shape applies identically to
Compensation with no modification needed). No new `NoActiveEmploymentError` — **reused as-is** from
Assignment (already generic, no Assignment-specific wording in its message).

---

## 18. Migration Plan

**One small, additive-only migration** — `apps/api/alembic/versions/<timestamp>_employee_
compensation.py`, following the exact `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` template every
prior slice's migration used (`20260814100000_employee_assignment.py`,
`20260814110000_employee_shift_assignment.py`), and the exact RLS-idempotent-reassertion convention:

```sql
ALTER TABLE employee_compensation
  ADD COLUMN IF NOT EXISTS revision_type VARCHAR(20) NOT NULL DEFAULT 'JOINING',
  ADD COLUMN IF NOT EXISTS revision_reason TEXT;

-- No CHECK constraint on revision_type's value set — matches the established precedent
-- (employment.status / employee_assignment.change_type are both validated at the Pydantic
-- layer only, not DB CHECK-constrained, per 12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §17
-- item 7's own note that this is the actually-shipped pattern, not the aspirational lookup-table
-- rule). A DEFAULT is safe here specifically because the table has zero rows (§4.1) — no backfill
-- ambiguity; the DEFAULT exists only so the column can be declared NOT NULL cleanly in one
-- statement without a separate backfill-then-constrain step, matching how employment.status
-- itself got a DEFAULT ('ACTIVE') in its own migration for the identical reason.

-- RLS re-asserted idempotently, matching every prior migration's own habit (already live and
-- correct on this table since the first migration — this is house convention, not a fix):
ALTER TABLE employee_compensation ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_compensation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON employee_compensation;
CREATE POLICY tenant_isolation ON employee_compensation
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

**No new index** — the live `employee_compensation_employee_id_effective_from_idx` and the GiST
exclusion constraint already cover every query shape this slice's repository needs (`get_current_
compensation`, `get_compensation_as_of`, `list_compensations` — all filter on `employee_id` [+
`effective_from`/`effective_to`], exactly the indexed columns). This matches E-05's own precedent
exactly (`16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md §4`: "No new index — no source calls
for one").

**No new FK** — `employee_compensation` has exactly one relationship column (`employee_id`), already
FK-constrained since the first migration (§4.1). Nothing this slice adds is a reference column.

**No downgrade risk** — zero rows exist (§4.1); the migration is purely additive and its downgrade
(`DROP COLUMN IF EXISTS revision_reason, revision_type`) is safe and lossless.

---

## 19. Test Plan

Mirrors `test_employee_assignment_service.py` (unit) / `test_employee_assignment.py` (integration)'s
own structure exactly — the closest sibling, same effective-dating shape, same single-write-operation
service design.

### Unit (`tests/unit/modules/employee/test_employee_compensation_service.py`)

- First compensation row: success with `revision_type=JOINING`.
- No covering employment episode → `NoActiveEmploymentError`.
- Unknown employee → `NotFoundError`.
- Current row exists, new `effective_from` strictly after → success, current row closed.
- Current row exists, `effective_from` not strictly after → `InvalidEffectiveFromError`.
- Current row exists, `If-Match` omitted → `CompensationVersionRequiredError`.
- Current row exists, stale `version` on close → `StaleResourceError`.
- The GiST-overlap-to-domain-error translation (`IntegrityError` → `CompensationDatesOverlapError`).
- Read-path: `list_compensations` (full history), `get_compensation`, `get_compensation_as_of`
  (including that it does not require an employee-existence check, mirroring
  `get_assignment_as_of`'s own documented behaviour, `service.py:820-832`).
- Negative `annual_ctc_minor` rejected at the schema layer (`422`, Pydantic `ge=0`).

### Integration (`tests/integration/modules/employee/test_employee_compensation.py`, against the real
Postgres dev database)

- First compensation row success, with audit-row verification (`COMPENSATION_REVISED`, `before=None`).
- No-covering-employment rejection (`409 NO_ACTIVE_EMPLOYMENT`).
- Mass-assignment rejection (`422`, `extra="forbid"` — attempt to set `id`/`company_id`/
  `employee_id`/`version`/`effective_to`).
- Missing/stale `If-Match` on a revision (both error paths).
- **The raw-SQL GiST-constraint-bypass test** — attempt an overlapping raw insert bypassing the
  service's own close-first logic, proving the DB constraint is the actual backstop, matching
  `test_raw_overlapping_insert_rejected_at_database_level`'s exact precedent
  (`12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §10`).
- As-of-date boundary walk (exact `effective_from`, exact `effective_to`, one day outside each —
  matching `test_list_assignments_as_of_date_boundaries`'s own boundary-condition discipline).
- A revision scenario: two sequential compensation rows for one employee, `effective_to` correctly
  closed on the first, `annual_ctc_minor` different on each, both independently queryable.
- **Full rehire scenario, end-to-end** — reusing the same fixture shape as
  `test_rehire_first_assignment_after_gap`: employee joins, compensation set, employment terminates,
  gap, rehire, new compensation set — assert `employee_id` unchanged throughout, no compensation row
  exists during the gap (`get_compensation_as_of` during the gap returns `None`), full history
  returns exactly the pre-exit and post-rehire rows with a visible gap.
- Cross-tenant isolation: `GET`/`POST` against another tenant's employee → `404`.
- Permission-matrix tests: no `.VIEW_COMPENSATION` → `403` on GET (and confirm the response is not a
  masked/degraded body but an outright denial, per §7/§11's "absent, not disabled" rule); no
  `.UPDATE_COMPENSATION` → `403` on POST; `.VIEW_COMPENSATION`-only caller cannot POST.
- Every test tears down its own rows in a `finally` block, FK-safe order (`employee_compensation ->
  employment -> employee/number_series -> ... -> legal_entity/company/roles/user`), mirroring
  `_cleanup`'s existing helper exactly (`test_employee_assignment.py`'s own established pattern).

**Regression**: `test_registration_flow.py`'s permission-set assertion updated for the two new codes
(§12) — the only pre-existing test file this slice should need to touch.

---

## 20. Validation Plan

Exact commands every prior slice's closeout report has run and reported, from `apps/api/`:

```
uv run ruff check .              # lint
uv run ruff format --check .     # formatting
uv run mypy src/hrms              # type-check
uv run lint-imports                # import-boundary contract (modules → shared → core)
uv run pytest                     # full backend suite — expect 439 (pre-existing) + N new, 0 failed
```

These are exactly the commands `.github/workflows/ci.yml` runs (verified this session, lines 30-46)
— running them locally before considering the slice done matches CI exactly, no drift.

**Manual DB verification** (matching every prior slice's own discipline, e.g.
`16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md §4`): after `alembic upgrade head`, run
`\d+ employee_compensation` against the dev database and confirm the two new columns
(`revision_type`, `revision_reason`), their types/defaults, and that every pre-existing column,
index, FK, and the GiST exclusion constraint are unchanged. Confirm `alembic_version` advances to
the new revision. Confirm row count is still `0` after the full test suite run (no orphaned test
data), matching `08_EMPLOYMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md §14`'s own "dev database
cleanliness" check.

No frontend validation command applies (§14 — no frontend work in this slice).

---

## 21. Explicitly Deferred Scope

- **BR-14 shift/notice-period override chain** — unrelated to Compensation; already deferred at the
  cross-module level (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part G item 1), not reopened here.
- **Payroll** (salary structures, components, CTC-to-gross-to-net breakup, arrears engine, payroll
  runs) — a separate, later module (`docs/product/VERSION_1_ROADMAP.md`); `salary_structure_id`,
  `monthly_gross`, `is_arrears_processed`, and the `employee_compensation_component` child table are
  all deferred to whenever Payroll's own catalogue tables exist (§4.2).
- **Statutory (E-07)** and **Banking (E-08)** — separate, not-yet-built effective-dated tables; no
  code in this slice touches either.
- **Approval-routing engine** on compensation revisions (`approved_by`/`approval_request_id`) — no
  engine exists; not stored, not enforced (§7, §13, §17.4's related decision on not combining
  promotion+compensation into one transaction).
- **`sensitive_access_log`** (RESTRICTED-field read logging) — already-locked timing is **E-10**, not
  E-06 (§13); explicitly not built here despite CTC being RESTRICTED-classified.
- **Grade `min_ctc`/`max_ctc` band enforcement against `annual_ctc_minor`** — PD-1 (§16); this plan
  ships with no enforcement, revisit only on explicit product direction.
- **Combined promotion+compensation-revision workflow/transaction** (FR-EMP-012's "single workflow")
  — §17.4; two independent API calls, no orchestration endpoint built.
- **Frontend (Compensation tab, salary-revision workflow screen)** — E-09, per unbroken precedent
  from E-01 through E-05 (§14).
- **`SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope resolver** on the GET routes — E-10's scope,
  identical precedent to every prior slice's own reads (`Employment`, `Assignment` both gate only on
  the coarse `VIEW`/`VIEW_ALL` distinction today).
- **Backdating-past-locked-payroll-period enforcement** (FR-EMP-004, `PAYROLL.BACKDATE_OVERRIDE`) —
  not implementable until Payroll exists; any past `effective_from` is currently accepted without a
  lock-period check, identical known limitation to Assignment/Employment.
- **Multi-currency cross-check against a company-level currency setting** — §8; the live `currency`
  column accepts any 3-letter code with no cross-validation.

---

## 22. Risks

1. **Effective-dating write path is now a fourth repetition of the same pattern** (Employment,
   Assignment, and now Compensation) — low risk, since the pattern is fully mechanical at this point
   (E-04's own risk framing — "first effective-dated write path... budget extra review time" — no
   longer applies; this is the third/fourth instance, not the first).
2. **A stale `annual_ctc_minor` silently carried forward is a materially worse failure mode than a
   stale department** — mitigated by §17.2's deliberate no-carry-forward decision, but this is a
   decision this plan makes rather than one sourced from a document; a future reviewer disagreeing
   with §17.2 should revisit it before implementation, not after.
3. **RESTRICTED-tier data with no `sensitive_access_log`** — CTC reads are not logged beyond the
   ordinary write-path `AuditService` calls, because `sensitive_access_log` is deliberately deferred
   to E-10 (§13, §21). This is a real, named compliance gap for the period between E-06 shipping and
   E-10 shipping — flagged, not silently accepted, exactly as `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
   Part A9 itself already anticipated when it locked E-10 (not E-01, and by extension not E-06) as
   the build slice.
4. **PD-1 (Grade band enforcement) shipping as "no enforcement"** could be read by a future reviewer
   as a silent gap rather than a deliberate, documented decision — mitigated by §8/§16's explicit
   citation trail; still worth a one-line mention in E-06's own closeout report, matching how every
   prior slice's report explicitly re-confirms its own known limitations rather than assuming the
   plan document alone is sufficient record.
5. **The assignment-row-not-auto-closed-on-termination limitation now has a compensation-row
   sibling** (§10 step 3) — two independent, un-remediated gaps of the same shape. Neither is this
   slice's to fix (fixing either means modifying `EmploymentService.terminate_employment`, out of
   scope for a single-table slice per every prior slice's own restraint), but the *combination* is
   worth flagging for a future dedicated "close child rows on termination" follow-up task spanning
   both tables at once, rather than two separate patches.

---

## 23. Recommended Implementation Sequence

Phased, listing exact files likely to change per phase — **no file is created or modified by this
planning document itself.**

1. **Migration**: `apps/api/alembic/versions/<timestamp>_employee_compensation.py` (§18). Apply,
   verify against the dev DB (`\d+ employee_compensation`).
2. **ORM model**: `apps/api/src/hrms/modules/employee/models.py` — add `EmployeeCompensation`
   class, alongside `Employee`/`Employment`/`EmployeeAssignment`/`NumberSeries`; update the module
   docstring (lines 1-7) to remove the now-stale "not mapped here" sentence about
   `EmployeeCompensation`.
3. **Repository**: `apps/api/src/hrms/modules/employee/repository.py` — add
   `EmployeeCompensationRepository` (mirrors `EmployeeAssignmentRepository` exactly, §6): `insert_
   compensation`, `get_current_compensation`, `get_compensation_as_of`, `list_compensations`,
   `get_compensation`, `close_compensation`.
4. **Exceptions**: `apps/api/src/hrms/modules/employee/exceptions.py` — add
   `CompensationDatesOverlapError`, `CompensationVersionRequiredError` (§17.6); reuse
   `InvalidEffectiveFromError`/`NoActiveEmploymentError`/`StaleResourceError` as-is.
5. **Schemas**: `apps/api/src/hrms/modules/employee/schemas.py` — add `REVISION_TYPE_VALUES`
   tuple + `RevisionType` Literal (§9), `CompensationCreate`/`CompensationRead`, `compensation_to_
   read`/`compensation_to_audit_dict`.
6. **Service**: `apps/api/src/hrms/modules/employee/service.py` — add
   `EmployeeCompensationService.create_compensation` (§6, §17) + read methods
   (`list_compensations`, `get_compensation`, `get_compensation_as_of`).
7. **Permissions**: `apps/api/src/hrms/modules/employee/permissions.py` — add
   `EMPLOYEE_VIEW_COMPENSATION`, `EMPLOYEE_UPDATE_COMPENSATION` to `EMPLOYEE_PERMISSIONS` (§12).
8. **Dependencies**: `apps/api/src/hrms/modules/employee/dependencies.py` — add `get_employee_
   compensation_service`.
9. **Router**: `apps/api/src/hrms/modules/employee/router.py` — add 3 routes (§11), following the
   exact static-`Depends(require_permission(...))` pattern (unlike Assignment's dynamic
   permission-selection-by-body — Compensation's two permissions map 1:1 to GET/POST, no dynamic
   selection needed).
10. **Tests**: `apps/api/tests/unit/modules/employee/test_employee_compensation_service.py`,
    `apps/api/tests/integration/modules/employee/test_employee_compensation.py` (§19), written
    alongside the service, not after.
11. **Regression update**: `apps/api/tests/integration/modules/organisation/test_registration_
    flow.py` — add the two new permission codes to the existing assertion (§12).
12. **Validation**: run §20's five commands; verify against the dev DB.
13. **Documentation**: a new `docs/modules/employee/18_EMPLOYEE_COMPENSATION_IMPLEMENTATION_
    REPORT.md` at close (this plan is `17_...`, following the established numbering — Assignment
    used 09/10/11/12, Shift Assignment used 13/14/15/16), not edits to this plan document itself,
    matching every prior slice's own report-writing convention.

---

## 24. Definition of Done

Mirrors the bar every prior slice's closeout report has actually met (E-01 through E-05, all
verified 100% passing before their own next slice began):

- [ ] Migration applied and verified against the dev database, column-by-column, matching this
      plan's §18 exactly (or a documented, reasoned deviation).
- [ ] `EmployeeCompensation` ORM model, repository, service, schemas, permissions, dependencies,
      router all implemented, mirroring `EmployeeAssignment`'s shape per §6/§9/§11/§17.
- [ ] Three endpoints live: `GET .../compensation`, `GET .../compensation/{id}`, `POST
      .../compensation`, exact shapes per §11.
- [ ] `EMPLOYEE.VIEW_COMPENSATION`/`EMPLOYEE.UPDATE_COMPENSATION` seeded, granted to
      `COMPANY_ADMIN` at both bootstrap and live-registration time, verified by the updated
      `test_registration_flow.py` assertion.
- [ ] `COMPENSATION_REVISED` audit event fires on every write, verified by test.
- [ ] GiST exclusion constraint's race-condition backstop verified by a raw-insert test (§19).
- [ ] As-of-date read pattern verified against boundary conditions (§19).
- [ ] Full rehire scenario verified end-to-end (§10, §19).
- [ ] Cross-tenant isolation verified (§19).
- [ ] Permission-matrix tests verified (§19).
- [ ] All five validation commands (§20) pass clean against the whole backend, not just this
      slice's own files.
- [ ] Dev database confirmed clean (`employee_compensation` row count `0`) after the full test run.
- [ ] No `apps/web/` file touched (§14).
- [ ] No file outside `modules/employee/`, the one new migration, the two new test files, and the
      one `test_registration_flow.py` assertion update, touched.
- [ ] Closeout report written (`18_EMPLOYEE_COMPENSATION_IMPLEMENTATION_REPORT.md`), explicitly
      re-confirming PD-1's resolution (§16) and every §21 deferred-scope item, per the discipline
      every prior slice's own report has followed.

---

## Status

**READY TO IMPLEMENT.**

One product-decision item was identified (§16, PD-1 — Grade CTC-band enforcement) but it carries a
safe, zero-schema-cost, fully-precedented default (no enforcement) that this plan adopts outright,
exactly the same way `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` concluded "no blocking product
decision" for E-04 despite naming several engineering choices along the way. No other item in this
document lacks a sourced answer or a directly-precedented safe default. The database requires one
small, fully-specified, zero-risk additive migration (§18); every other structural question this
slice depends on (effective-dating pattern, rehire correctness, permission catalogue, audit
convention) was already decided by `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` before this document was
written and is not reopened here.

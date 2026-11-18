# Shift Lifecycle Production-Safety Audit — 17 November 2026

**Status: read-only audit. Nothing was fixed, staged or committed. Awaiting owner review.**

Scope: creation, editing, publishing, assignment, roster, swap, reassignment, deactivation and
deletion of shifts; every downstream reader (attendance engine, leave, payroll); authorization,
database integrity, concurrency, background work, audit, notifications, web and mobile clients.

Companion reports (not repeated here, referenced by ID): `SHIFT_MANAGEMENT_AUDIT_2026-11-15.md`
(SH-xx, engine rules), `SHIFT_REMEDIATION_PLAN_2026-11-15.md`, `SHIFT_CREATION_VALIDATION_AUDIT_2026-11-17.md`
(SC-xx, creation rules). This report's IDs are **SL-xx**.

---

## 0. Phase 0 — repository and environment state (documented before anything else)

| Item | Finding |
|---|---|
| Repo path | `/media/varun/varun27/work/staff-spectrum/HRMS` (the session opened on `varun20`, which now holds only `infra`; drive mount number changed again) |
| Branch / HEAD | `test` / `dd71571` |
| Working tree | **153 uncommitted paths** (68 modified, 85 untracked): attendance, leave, organisation, web and mobile work from other sessions, plus the uncommitted SC-01..04 shift-name work and migration `20261117090000`. All preserved; none touched. |
| Audit's own writes | This report; probe scripts in the session scratchpad only; one throwaway database (below). No application code, migration, config or test file was edited. |
| Databases | `hrms_dev` untouched. `hrms_test` untouched (it is two migrations behind head and holds leftovers). I created **`hrms_audit_shift_probe`** on the same Postgres server (port 5433), migrated it to the working-tree head (`20261117090000`) and ran everything there. Redis index 1; Celery broker index 15. |
| Role used by probes | Schema owner `hrms` (bypasses row-level security). So the cross-tenant probes prove the *application-layer* tenant scoping; RLS itself is covered by existing runtime-role tests that I did not run. |

**Baseline.** Existing shift suites run against the disposable DB: `organisation/test_shift.py`,
`test_shift_version.py`, `test_shift_name_integrity.py`, `test_shift_break_rules.py`,
`attendance/test_shift_roster.py`, `leave/test_leave_roster_days.py`, `tests/unit/modules/organisation`,
`tests/unit/modules/attendance/test_split_shift.py` → **411 passed, 0 failed, 43.7 s**. This proves the
happy paths and the rules those files pin. It does not prove anything about the races and gaps below;
that is why I probed them separately.

**Evidence labels used throughout:** **[EXEC]** = reproduced by running the real API against the
disposable DB. **[READ]** = verified by reading the cited source only. **[UNVERIFIED]** = not
established either way.

---

## 1. Executive summary

**Verdict: production safe with conditions for a single-administrator, fixed-roster pilot; not yet
safe for several administrators editing concurrently or for self-service swaps at scale.**

What is solid (verified):
- **Tenant isolation holds.** 12 cross-company attempts (read, edit, delete, publish, assign, roster
  with another company's shift, forged `X-Company-Id`) all returned 404 or an empty list. [EXEC]
- **Version publishing is concurrency-safe.** 4 parallel create-version calls → 1×201, 3×409. 3 parallel
  publishes of one draft → 1×200, 2×409. 4 parallel roster creates for one employee-date → 1×201, 3×409.
  Overlapping published versions and overlapping assignments are blocked by database exclusion
  constraints; one open draft per shift by a partial unique index. [EXEC + schema]
- **Published versions stay immutable and history is stable**: every calculated day stores its shift
  version; closed periods refuse roster, publish and assignment writes. [READ; prior audit]
- **Writes that change attendance queue a recalculation in the same transaction** (publish, assignment,
  roster publish/edit/delete, swap approve). [READ]
- **Notification failure cannot undo a business write** (savepoint-isolated). [READ]
- **Bulk roster create is all-or-nothing.** A bulk with a conflicting 3rd date left only the pre-existing row. [EXEC]

What is not safe yet — 15 findings: **0 Critical, 1 High, 7 Medium, 5 Low, 2 informational.**

| ID | Sev | One line |
|---|---|---|
| SL-01 | High | Saving only breaks/duty blocks on a draft ignores `If-Match`, so two admins silently overwrite each other, and publish can freeze breaks nobody validated |
| SL-02 | Medium | A roster row can be created for someone with no employment, or dated before their joining date |
| SL-03 | Medium | `PATCH` can turn a shift row into a week-off row that still carries a shift |
| SL-04 | Medium | Concurrent or double-tapped swap requests all succeed: four pending swaps for one pair and day |
| SL-05 | Medium | Deactivating a shift ignores future roster rows; a draft on an inactive shift can still be published |
| SL-06 | Medium | Web and mobile "copy day" / "publish all" are client loops: partial result, and a half-created row blocks every retry |
| SL-07 | Medium | Rostering and swapping ignore leave, weekly off, rest and employment end; a swap can be approved for today after punches exist |
| SL-08 | Medium | A wrongly published version cannot be corrected and has no impact preview (carried from SC-05 / P-08) |
| SL-09 | Low | Deactivate-vs-assign race (read-verified, not executed) |
| SL-10 | Low | A recalculation request that fails 5 times is closed silently |
| SL-11 | Low | Employees are not told when their roster or shift assignment changes |
| SL-12 | Low | Web roster dialog loads shifts from an endpoint that needs a different permission; the 403 is swallowed |
| SL-13 | Low | Database lacks defence-in-depth: no tenant FK on assignment, `ON DELETE SET NULL` on history, no immutability triggers |
| SL-14 | Low | Swap response discloses a colleague's name/shift by UUID; a GET writes to the database |
| SL-15 / SL-16 | Info | Generic error code on a lost create-version race; recurring / department / bulk-multi-employee assignment are not built |

**Not covered by any existing test:** concurrency of roster, swap, deactivation and breaks-only
edits; the SL-02 and SL-03 states; partial-failure of the client copy loops.

---

## 2. Complete shift lifecycle architecture

```
CONFIGURATION (organisation/service.py)
  shift (identity, name, code, is_active)  ──1:N──  shift_version (DRAFT → PUBLISHED, effective-dated)
                                                      ├─ shift_break (replaced wholesale on every draft save)
                                                      └─ shift_duty_block (SPLIT only)
ASSIGNMENT (three, and only three, ways a person gets a shift)
  1. employee_assignment.shift_id   default shift, effective-dated, GiST no-overlap          employee/service.py:2008
  2. shift_roster                   per-employee-per-date override, DRAFT→PUBLISHED          attendance/service.py:2534
  3. shift_swap_request             two employees exchange published roster rows on a date   attendance/schedule_service.py
RESOLUTION   work_schedule.py: published roster row, else assignment shift, else none; version by date
CONSUMERS    attendance engine → attendance_day (stores shift_version_id) → period close → payroll
RECALC       attendance/recalc.py queue, written in the writer's transaction, kicked after commit
```

Payroll holds **no shift reference at all** (grep of `modules/payroll`: none). It reads the closed
attendance period, so shift edits reach pay only through attendance days, and only while those days
are unlocked.

## 3. API and UI entry-point inventory

| Workflow | Endpoint | Permission | Web | Mobile |
|---|---|---|---|---|
| Create shift + schedule + publish | `POST /v1/shifts/setup` | `ORG.SHIFT.MANAGE` | shifts page | shifts screens |
| Create shift / draft | `POST /v1/shifts`, `POST …/versions` | same | yes | yes |
| Edit draft / discard | `PATCH`, `DELETE …/versions/{id}` | same, `If-Match` | yes | yes |
| Publish | `POST …/versions/{id}/publish` | same, two tokens | yes | yes |
| Rename / deactivate / reactivate | `PATCH`, `DELETE /v1/shifts/{id}` | same, `If-Match` | yes | yes |
| Guarded delete | `GET …/deletion-check`, `POST …/delete` | same | yes | yes |
| Default shift | `POST /v1/employees/{id}/assignments` (`SHIFT_CHANGE`) | employee-assignment permissions, data-scoped | yes | yes |
| Roster create / bulk / edit / publish / delete | `/v1/rosters*` | `ATTENDANCE.ROSTER_MANAGE`, data-scoped per target employee | one row at a time; **`/rosters/bulk` is not called by web or mobile** | one row at a time |
| Swaps (HR / employee) | `/v1/rosters/swap-requests*` | HR: `ROSTER_MANAGE`; employee: `ATTENDANCE.VIEW` | yes | yes |

**Unsupported (not defects):** assignment by department, designation, team or location; recurring or
rotation patterns (WD-27: the client expands to dated rows); import of shifts or rosters;
background auto-assignment; shift-swap by approval chain beyond one manager.

---

## 4. Creation workflow audit
See `SHIFT_CREATION_VALIDATION_AUDIT_2026-11-17.md` (SC-01..04 implemented, uncommitted). Re-verified here: `POST /shifts/setup`
is one transaction; a create leaves an *empty draft* that cannot publish (`shift_version_published_required_check`
plus service validation); name uniqueness uses an advisory lock plus partial unique index
`shift_company_live_name_key`. **Verdict: production safe with conditions** — SC-05 (effective-date typo
recovery) and SC-06 (no maximum length) remain owner-deferred.

## 5. Edit workflow audit
- Published versions: no edit path exists (`ShiftVersionNotDraftError`); change = new version. History intact. **Safe.**
- Draft scalar edits: `If-Match` enforced, stale write → 409 with current copy. **Safe.**
- Draft **breaks / duty blocks only** edits: **not guarded — SL-01.**
- Failed edit leaves original intact: breaks replace and scalar update run in one request transaction. **Safe.** [READ]

## 6. Publish workflow audit
Safe: closed-period refusal, new `effective_from` must be after the open version's, two concurrency
tokens, exclusion-constraint backstop, recalc queued for the shift from `effective_from`, audit with
before/after. [EXEC for concurrency]
Gaps: no impact preview and no way to correct a wrong publish (**SL-08**); publish does not re-read
breaks under a lock (**SL-01**); publish of a draft on an inactive shift is not refused (**SL-15**).

## 7. Assignment workflow audit
Requirement-by-requirement (the 16 you listed):

| # | Requirement | Default shift (`create_assignment`) | Roster (`/rosters`) | Swap |
|---|---|---|---|---|
| 1 | Employee exists | ✔ visible-or-404 | ✔ visible-or-404 | ✔ |
| 2 | Same company | ✔ [EXEC] | ✔ [EXEC] | ✔ |
| 3–4 | Active, employed, not terminated | ✔ employment must cover `effective_from` (`:2029`) | **✘ SL-02 [EXEC]** | partial (`_LIVE_STATUSES` for self-service only) |
| 5 | Shift exists and published | ✔ version must exist on the date (`:2158`) | ✔ (`_ensure_shift_usable_on`, create/update only) | n/a (uses existing rows) |
| 6 | Shift same company | ✔ [EXEC] | ✔ + composite FK | ✔ |
| 7 | Effective date valid | ✔ + closed period | ✔ closed period | ✔ not before today |
| 8 | No conflict with another assignment | ✔ GiST | ✔ unique index [EXEC] | ✘ duplicates **SL-04 [EXEC]** |
| 9 | Respects approved leave | ✘ no rule | ✘ no rule | ✘ no rule (SL-07) |
| 10 | Weekly-off policy | ✘ no rule | override semantics only | ✘ |
| 11 | Holiday policy | ✘ | override semantics only | ✘ |
| 12 | Rest-period | ✘ no documented rule | ✘ | ✘ |
| 13 | Max working hours | ✘ no documented rule | ✘ | ✘ |
| 14 | No overlapping work periods | n/a (one shift per date; P-14 two shifts a day unsupported) | n/a | n/a |
| 15 | Historical assignments protected | ✔ closed-period + closes-previous model | ✔ | ✔ date ≥ today |
| 16 | Future assignments on version change | ✔ resolved by date, so unaffected | ✔ | ✔ |

Rows 9–13 are **missing product decisions, not confirmed defects** (see §23).

## 8. Reassignment and cancellation audit
- Reassign default shift: new row closes the previous (`close_assignment` with version check). Concurrent
  writers resolved by If-Match plus GiST. Recalc queued from `effective_from`. **Safe.**
- Roster change / delete: version-checked, audited, recalc queued only when the row is or was PUBLISHED. **Safe.**
- Termination: future PUBLISHED roster rows and PENDING swaps are **not** touched (grep of `employee/service.py`:
  no roster or swap reference). The engine labels such days `EXITED`, so pay is safe, but rosters, coverage
  counts and swap approvals still carry the person (SL-07). [READ]
- Leave approval after rostering: not checked (P-12, SL-07).

## 9. Deactivation and deletion audit
| Case | Behaviour | Verdict |
|---|---|---|
| Deactivate with active employees on default assignment | refused (`MasterDataInUseError`) | safe |
| Deactivate with **published or draft roster rows** | **allowed [EXEC]** | SL-05 |
| Deactivate with pending swaps | allowed [READ] | SL-05 |
| Create a roster on an inactive shift | refused `INACTIVE_SHIFT` [EXEC] | safe |
| **Publish an existing draft** on an inactive shift | **allowed [EXEC]** | SL-05 |
| Reactivate | allowed, no checks | acceptable |
| Soft delete | requires inactive, no assignment/roster/attendance/regularization history, typed name, reason, row locked `FOR UPDATE`, audited with snapshot | **safe** |
| Hard delete | none in application. Database would null history (SL-13) | safe in-app |
| Historical attendance of a deactivated shift | engine ignores `is_active`; versions resolve by date | stable |

## 10. Validation matrix

| Rule | Frontend | API schema | Service | DB | Worker/engine | Concurrency-proof | Verdict |
|---|---|---|---|---|---|---|---|
| Name unique, non-blank | ✔ | ✔ trims | ✔ advisory lock | ✔ unique + CHECK | – | ✔ (existing test) | OK |
| Type-specific times / flex / split | ✔ | ✔ | ✔ at publish | ✔ required-fields CHECK | – | n/a | OK |
| Break structure and containment | ✔ | ✔ | ✔ | partial (kind/min-max CHECKs) | engine | **✘ SL-01** | gap |
| Effective version ordering, no overlap | – | – | ✔ | ✔ GiST | – | ✔ [EXEC] | OK |
| Closed-period protection | – | – | ✔ publish, roster, assignment | – | engine skips locked | n/a | OK |
| Roster: one row per employee-date | – | – | ✔ | ✔ unique | – | ✔ [EXEC] | OK |
| Roster: week-off excludes shift | ✔ | **create only** | ✘ | ✘ (only flag-exclusivity CHECK) | engine behaviour not probed | – | **SL-03** |
| Roster: employee employed on date | ✘ | ✘ | ✘ | ✘ | engine yields NOT_JOINED/EXITED | – | **SL-02** |
| Roster: shift usable on date | ✔ | – | create/update ✔, **publish ✘** | composite FK (tenant only) | – | – | SL-05 |
| Assignment: version exists on date | – | – | ✔ | – | engine config-error | – | OK |
| Swap: one pending per employee-day | – | – | check before lock | ✘ no index | – | **✘ [EXEC]** | **SL-04** |
| Leave / rest / max hours / weekly-off on assignment | – | – | ✘ | ✘ | – | – | policy (§23) |

## 11. Database integrity analysis (schema inspected on the disposable DB)

Present: RLS **enabled and forced** on `shift`, `shift_version`, `shift_break`, `shift_duty_block`,
`shift_roster`, `shift_swap_request`, `employee_assignment`, `attendance_recalc_request`, `audit_log`.
`shift_version_no_overlap` (GiST, published only); `shift_version_one_open_draft_idx`;
`employee_assignment_no_overlap` (GiST); `shift_roster_unique_idx` (partial, live rows);
`shift_company_live_name_key`; tenant composite FK on `shift_roster`; status and structure CHECKs.

Absent: any unique index on pending swaps (SL-04); any CHECK tying a week-off roster row to a null
`shift_id` (SL-03); composite tenant FK on `employee_assignment.shift_id` and on the swap table's shifts
and employees (SL-13); **no triggers at all** on shift tables, so immutability of published versions and
their child `shift_break` / `shift_duty_block` rows is application-only (SL-13); `ON DELETE SET NULL` on
assignment, roster and `attendance_day` shift columns, so an operator hard-delete would silently erase
history links (SL-13).

## 12. Concurrency analysis — your ten scenarios

| # | Scenario | Result |
|---|---|---|
| 1 | Two users create the same shift name | Prevented (advisory lock + unique index; existing test) |
| 2 | Two managers give one employee overlapping assignments | Prevented by GiST; the loser gets 409 |
| 2b | Two roster rows for one employee-date | 1×201, 3×409 [EXEC] |
| 3 | Two managers edit the same shift | Scalar edits: 409. **Breaks/duty-block-only edits: last write wins, no error [EXEC] — SL-01** |
| 4 | Two managers publish competing versions | Only one draft can exist; 4 parallel creates → 1 winner [EXEC]; 3 parallel publishes of one draft → 1 winner [EXEC] |
| 5 | Bulk assignment partially succeeds | Server bulk is atomic [EXEC]. **Client copy / publish-all loops are not — SL-06** |
| 6 | Assignment saved while the employee becomes inactive | [UNVERIFIED]; not executed. Employment check and write are in one transaction but at READ COMMITTED, so a very narrow window exists |
| 7 | Shift deactivated while an assignment is created | **Window exists [READ] — SL-09** |
| 8 | Worker processes an obsolete assignment | Recalc re-reads current state each run and is idempotent [READ]; safe |
| 9 | Recalc runs before related changes commit | Request row is inserted in the writer's transaction; the kick is deferred until commit [READ]; safe |
| 10 | A transaction fails after partial writes | Single request transaction; verified for bulk [EXEC] and version publish (rollback on overlap) |
| – | Duplicate swap requests | **4 parallel → 4×201, 4 PENDING [EXEC] — SL-04** |

Idempotency: roster create and version create are naturally idempotent via unique keys (clean 409).
Swap create is not. Assignment create relies on `If-Match`, so a blind retry after a lost response gets
409 rather than a duplicate. There is no `Idempotency-Key` on any shift write; the 409s are the only
protection against the "timeout after successful persistence" case, and the user must reload to learn the write landed.

## 13. Security and authorization analysis
- Every shift, roster and swap endpoint carries `require_permission(...)`; roster mutations additionally
  check the **target employee** against the caller's data scope (`ensure_employee_visible`), returning the
  same 404 for "not yours" and "does not exist". [READ]
- Cross-company: **12 attempts, all 404 or empty** [EXEC] (list in §0 and Appendix B).
- Mass assignment: shift, version, roster and swap schemas use `extra="forbid"`. [READ]
- IDOR: object ids are always combined with `company_id` in repository lookups. [READ]
- Weak spots: SL-12 (permission mismatch), SL-14 (colleague disclosure by UUID, same tenant only).
- **[UNVERIFIED]** which default roles hold `ORG.SHIFT.MANAGE` vs `ATTENDANCE.ROSTER_MANAGE`; the default
  role catalogue was not inspected beyond the permission definitions.

## 14. Attendance integration analysis
Single resolution function (`work_schedule.py`, Invariant A) is used by day calculation, punch window,
policy scope and leave. Overnight attribution to the start date, locked-day refusal, and version-by-date
history are covered by existing tests (411 pass). The queue repairs only **existing, unlocked** days
(`recalc.py` module docstring); a missing day is created by the next punch or sweep. Gaps: SL-03
(engine behaviour for a week-off row carrying a shift is **not probed**), SL-07 (same-day swap after punches),
SL-10 (abandoned requests). Period close recalculates every unlocked day (prior audit; `test_period_close_recalculates.py`),
which bounds any stale result to the period.

## 15. Leave integration analysis
Leave reads published roster overrides to decide which days consume leave (`published_day_overrides`,
`leave/service.py:2686`). **Nothing checks the reverse**: rostering, assigning or swapping onto an approved leave day is
accepted (P-12, SL-07). Leave cancellation does not touch rosters (correct: rosters were never changed by leave).

## 16. Payroll integration analysis
Payroll consumes the attendance period summary, not shifts. A finalized period locks its days, and
shift publish, roster and assignment writes into it are refused, so **no path was found by which editing
or assigning a shift changes finalized payroll**. Backdated edits into an *open* period change that
period's days at the next recalculation, which is the intended behaviour but has no preview (SL-08).
Night allowance and overtime read the day's stored snapshot, not the latest version [READ, prior audit].

## 17. Frontend and mobile analysis
Good: dialogs disable while saving, field errors map from 422, 409 stale errors surface via `describeApiError`,
board moves reload on failure. Gaps: SL-06, SL-12. Shift-list failure is silently turned into an empty
list in three places (`roster-entry-dialog.tsx:92`, `rosters/page.tsx:149`, `grid/page.tsx:151`). The board's
"Unassigned" column deletes the roster row, so the employee reverts to their default-assignment shift;
whether the label misleads an employee who has a default shift is **[UNVERIFIED]** (UI not clicked through).
Web and mobile were read, not exercised in a browser or emulator.

## 18. Background worker and notification analysis
Notifications (swaps only) run inside a savepoint and return 0 on failure: a failed notification cannot
fail the write. [READ] Recalc: 5-minute Beat backstop for lost kicks, 50 requests per run, 5 attempts then
abandon with `last_error` (SL-10). No dead-letter surface beyond the table and an error log line. Audit
coverage: SHIFT_CREATED / UPDATED / DEACTIVATED / REACTIVATED / DELETED, SHIFT_VERSION_CREATED / UPDATED /
DISCARDED / PUBLISHED, SHIFT_ROSTER_CREATED / UPDATED / PUBLISHED / DELETED, ASSIGNMENT_CHANGED, swap
requested / consented / approved / declined / withdrawn. Each has actor, company, ip and user agent;
before/after present except swaps (reference and status only, no shifts or date in the "after" for
decisions). **Not audited:** bulk-roster as a unit, and "recalculation triggered" is visible only in the
request table. No notification reaches an employee when a roster or default shift changes (SL-11).

## 19. Test coverage matrix

| Layer | What exists | What it proves | Missing |
|---|---|---|---|
| Unit | `unit/modules/organisation` shift service/validation/break/name; `attendance/test_split_shift`, `test_shift_window`, `test_work_schedule`, `test_resolved_work_schedule` | pure rules | – |
| API integration | `test_shift`, `test_shift_version`, `test_shift_roster`, `test_weekly_schedule` (includes swaps), `test_recalc_queue` | happy paths, 409 on stale, scope | SL-02, SL-03 states; deactivate-with-roster; publish-draft-on-inactive |
| DB integration | `test_shift_name_integrity`, migration tests (`shift_tenant_fk`, `shift_name_unique`), RLS runtime-role tests | constraints, tenant FK | not run by me; swap uniqueness absent |
| Concurrency | `test_shift_name_integrity` (name), attendance sweep/punch concurrency | name race | **none** for roster, swap, publish, breaks-only edit, deactivate-vs-assign |
| Security | `tests/security`, `test_organisation_security`, RLS runtime-role | RLS, scope | cross-tenant shift/roster matrix is mine (Appendix B) |
| Frontend | web page tests for shifts, rosters, grid | rendering, calls | partial failure of copy/publish-all |
| Attendance regression | engine and overtime suites | day maths | engine on week-off+shift row |
| Leave regression | `test_leave_roster_days` | roster→leave consumption | leave→roster conflict |
| Payroll regression | none shift-specific (payroll has no shift link) | – | – |
| Migration | name-unique, tenant-FK | schema | `test_shift_name_unique_migration` is not in the CI migration job (CI lists files by name; `.github/` is protected) |

## 20–22. Detailed findings, severity and remediation

Format: ID · Severity · Classification · Evidence.

### SL-01 — Breaks/duty-block-only saves bypass optimistic concurrency · **High** · Confirmed defect · [EXEC]
- **Where:** `organisation/service.py:3269` (`update_shift_version`); the version check runs only inside
  `if values:` (`:3349`); `patch.breaks` / `patch.duty_blocks` are applied afterwards (`:3380`, `:3395`) with no
  token check and no version bump. `replace_breaks` is delete-all-then-insert (`organisation/repository.py:1018`).
- **Actual:** PATCH `{"breaks":[…]}` with `If-Match: 999` returned **200**; two such saves in a row both succeeded
  and only the last survived; the version number stayed at 2. [EXEC P3]
- **Expected:** a stale or wrong `If-Match` is 409 for any change to the draft, and every change bumps the version.
- **Reproduction:** admin A and B open the same draft; A saves a lunch break, B saves a different one; A's work vanishes with no error.
- **Second effect [READ, not executed]:** `publish_shift_version` reads breaks at `:3522` and validates them, then
  updates the draft under its own token (`:3595`). A concurrent nested-only edit does not change that token, so the version can
  publish with breaks the publisher never saw. A published version is immutable and cannot be corrected (SL-08).
- **Impact:** wrong break deduction on every day of every employee on that shift, from the effective date, in a shift that cannot be edited afterwards.
- **Fix:** bump `version` whenever breaks or duty blocks change and check it first; lock the draft row `FOR UPDATE` in publish before reading children and validate what was read.
- **Tests:** two-writer breaks-only conflict → 409; breaks-only save bumps version; publish concurrent with a breaks edit publishes either the old or the new set, never an unvalidated one.
- **Depends on:** none.

### SL-02 — Roster accepts people who are not employed · **Medium** · Missing safeguard · [EXEC]
- **Where:** `attendance/service.py:2635` (`_insert`) checks closed period and shift usability only.
- **Actual:** a roster row was created for an employee with **no employment record**, and for a date **before the joining date** (joined 2026-03-01, rostered 2026-02-01). Both 201. [EXEC P2]
- **Expected:** same rule as default assignment (`employee/service.py:2029`): employment must cover the date. (Your requirement 3–4.)
- **Impact:** pay is not wrong (engine labels such days `NOT_JOINED` / `EXITED`), but coverage numbers, weekly planner, leave-consumption overrides and swap candidates include people who are not working. Rostering a terminated employee's future days is also accepted.
- **Fix:** require a covering employment on `roster_date` in create, update and publish; decide whether a row already past the last working day is refused or only flagged (policy D-L1).
- **Tests:** no employment → 4xx; before joining → 4xx; after last working day → per D-L1; publish re-checks.

### SL-03 — PATCH creates a week-off row that still has a shift · **Medium** · Confirmed defect · [EXEC]
- **Where:** create enforces "week-off row must not carry a shift_id" (`attendance/schemas.py:1302`); `ShiftRosterUpdate` (`:1343`) validates only that the two flags are not both true; the database CHECK is the same flag-exclusivity only.
- **Actual:** create with week-off + shift → 422; but PATCH `{"is_week_off_override":true}` on a row holding a shift → **200**, leaving week-off + shift. [EXEC P1]
- **Impact:** the engine's behaviour for that state **was not probed**: `shift_id_for` returns the row's shift while `roster_week_off_override` is also true. The web and mobile clients always send `shift_id: null` with the flag, so only direct API use or a future client reaches it.
- **Fix:** validate the merged row (current + patch) and add a CHECK `NOT (is_week_off_override AND shift_id IS NOT NULL)` after cleaning existing rows (impact SQL first).
- **Tests:** PATCH to week-off without clearing the shift → 422; migration on data containing the state.

### SL-04 — Duplicate pending swap requests · **Medium** · Confirmed defect · [EXEC]
- **Where:** `attendance/schedule_service.py:697` duplicate check runs **before** the lock taken at `:714`; no unique index exists.
- **Actual:** 4 parallel identical requests → 4×201 and 4 PENDING rows. [EXEC P6]
- **Mitigation present:** approving one rewrites both rosters, so approving another fails with "roster changed" (`:801`). No double rewrite.
- **Impact:** a double-tap from the mobile app puts duplicates in a manager's queue and sends duplicate notifications; the second approval attempt looks like a system error.
- **Fix:** take the lock first, then check; add a partial unique index on `(company_id, swap_date, requester_employee_id)` and on counterpart where `status='PENDING'`.
- **Tests:** N parallel creates → one 201; index violation maps to 409.

### SL-05 — Deactivation ignores rosters; drafts can be published onto an inactive shift · **Medium** · Confirmed defect (publish) / Policy decision (deactivate) · [EXEC]
- **Where:** deactivation guard counts only active employees on default assignments (`organisation/service.py:2382–2386`, `employee/repository.py:526`); `publish_roster_entry` (`attendance/service.py:2762`) does not call `_ensure_shift_usable_on`.
- **Actual:** deactivating a shift used by a PUBLISHED future roster row and a DRAFT row → **200**; publishing that draft afterwards → **200**; creating a *new* row on it → 422. [EXEC P4]
- **Impact:** an administrator believes a shift is retired while next month's roster still runs on it and the engine keeps honouring it (engine ignores `is_active`).
- **Fix (needs decision D-L2):** either block deactivation while future roster rows or pending swaps exist (reuse the deletion-check counts, restricted to dates ≥ today), or allow it and show the count; and re-run usability at publish.
- **Tests:** deactivate with future roster → per decision; publish on inactive → 422.

### SL-06 — Client "copy day" and "publish all" are non-atomic loops · **Medium** · Missing safeguard · [READ]
- **Where:** `web/.../rosters/board/page.tsx:212–250` (two calls per employee, serial, stops at first error); `rosters/calendar/page.tsx:192–217`; `mobile/.../roster_repository.dart:69–80`.
- **Actual behaviour:** a failure mid-loop leaves earlier employees copied and the failing employee with a **DRAFT** (create succeeded, publish failed). The next attempt builds its "already rostered" set from `GET /rosters` (`:218–224`), which includes drafts, so the half-created employee is **skipped as already rostered and never published**. They then work on their default shift while the supervisor believes the roster is set. The failure toast ("stopped part-way") does not say how many were done.
- **Impact:** wrong shift for some employees on a day, undetected until attendance disagrees. Unexecuted; derived from the code path.
- **Fix:** exclude drafts from the skip set or publish them; report counts on failure; better, add a server endpoint that takes many employees and publishes in one transaction (the existing `/rosters/bulk` is single-employee, create-only, and used by no client).
- **Tests:** web test with a forced second-call failure; assert recovery on retry.

### SL-07 — Rostering and swapping ignore leave, weekly off, rest, employment end; same-day swaps · **Medium** · Policy decision (+ one missing safeguard) · [READ]
- **Where:** `ShiftRosterService._insert`, `create_assignment`, `schedule_service._create` / `decide`.
- **Actual:** none of these consult approved leave, rest between shifts or maximum hours; a swap is allowed for **today** (`:687` refuses only past dates) and approval rewrites today's roster after punches may exist, queuing a recalculation of the already-worked day against the other shift. `decide` does not re-check that both people are still employed.
- **Expected:** unknown — no documented company rule (P-12, P-14 in the 15 Nov audit). **I have not invented limits.**
- **Fix:** after decisions D-L3 / D-L4, add the chosen warnings or blocks at roster create/publish and swap create/approve. Re-check employment at swap approval regardless.

### SL-08 — No correction path and no impact preview for a published version · **Medium** · Design limitation / Policy decision · [READ]
Carried from SC-05 and P-08, unchanged: a wrong `effective_from` or content can only be superseded by a later version; backdating into an open period silently changes that period's days at the next recalculation. Owner deferred until a recoverable correction workflow is designed (SC-05). Included so the closure criteria below are complete.

### SL-09 — Deactivate-vs-assign race · **Low** · Missing safeguard · [READ, not executed]
`_assert_shift_ownership` (`employee/service.py:1899`) reads the shift without a lock; `update_shift` (`organisation/service.py:2357`) updates without locking and the guard count runs before the update. A concurrent assignment's foreign-key lock (`KEY SHARE`) does not conflict with the shift's `UPDATE` of a non-key column, so an employee can end up actively assigned to a just-deactivated shift. Consequence is mild because the engine ignores `is_active`. `delete_shift` already does it right (`lock_shift`, `repository.py:752`). Fix: same `FOR UPDATE`/`FOR SHARE` pairing. Test: parallel deactivate and assign.

### SL-10 — Abandoned recalculation requests are silent · **Low** · Missing safeguard · [READ]
After 5 failed runs a request is closed with `last_error` and one error log line (`recalc.py:43`, `:357–:412`). No surface tells HR that days are stale. Period close recalculates all unlocked days, so the exposure is bounded by the period, but a payroll cut-off is exactly when this matters. Fix: a count on the attendance dashboard / health check, and block or warn at period finalize if any request for the period was abandoned.

### SL-11 — Employees are not told about roster or default-shift changes · **Low** · Optional enhancement · [READ]
Only swaps notify (`notification/types.py:73–74`). Publishing a roster, changing a row, or a `SHIFT_CHANGE` assignment sends nothing. Employees find out by opening the schedule. Product decision D-L5.

### SL-12 — Shift dropdown depends on a different permission · **Low** · Confirmed code path · [READ]
`GET /v1/shifts` requires `ORG.SHIFT.MANAGE` (`organisation/router.py:707`), but `roster-entry-dialog.tsx:90` and the roster pages call it for users who hold `ATTENDANCE.ROSTER_MANAGE`. A 403 is turned into an empty list (`.catch(() => setShifts([]))`). A roster manager without shift-manage sees an empty dropdown and no explanation. **[UNVERIFIED]** whether any default role has that split. Fix: a roster-scoped read endpoint or a visible error.

### SL-13 — Database defence in depth · **Low** · Design limitation · [EXEC schema]
(a) `employee_assignment.shift_id` and the swap table's shift and employee columns have plain foreign keys, no tenant composite (only roster and regularization got it in `20261031090000`); (b) `ON DELETE SET NULL` on assignment, roster and `attendance_day` shift references; (c) no trigger prevents updates to a PUBLISHED `shift_version` or to its `shift_break` / `shift_duty_block` rows, and `ON DELETE CASCADE` on those children. Application never hard-deletes and RLS blocks cross-tenant, so this is exposure to operator SQL and future code, not to users today.

### SL-14 — Swap disclosure by UUID; GET writes · **Low** · Missing safeguard · [READ]
`create_my_swap` (`schedule_service.py:578`) lets an employee holding only `ATTENDANCE.VIEW` target any live colleague in the company by UUID; the response includes that person's name, code, department and shift name for the date (`_party`, `:398`). `list_swaps` performs an `UPDATE` to expire stale swaps (`:492`, `:540`) on a read request, and swaps stay PENDING until someone lists. Same-tenant only; UUIDs are unguessable.

### SL-15 — Informational · [EXEC / READ]
Losing a create-version race returns the generic `DUPLICATE_RESOURCE` for some losers and the specific `SHIFT_VERSION_DRAFT_ALREADY_EXISTS` for others (the insert at `organisation/service.py:3134` has no handler for the draft unique index). Harmless. Drafts and publishes on an inactive shift are also not refused.

### SL-16 — Unsupported by design (not defects)
Assignment by department / designation / team / location; rotation and recurring rosters; shift or roster import; auto-assignment; swap requests beyond one date and one counterpart. `POST /rosters/bulk` exists but no client uses it.

---

## 23. Policy decisions requiring your approval

| ID | Question | Default if you decide nothing | Blocks |
|---|---|---|---|
| D-L1 | Must an employee be employed on the roster date? Past the last working day: refuse or only warn? | Accept (today) | SL-02 |
| D-L2 | May a shift be deactivated while future roster rows or pending swaps use it? | Allowed silently (today) | SL-05 |
| D-L3 | May a swap be raised or approved for today, after punches? | Allowed (today) | SL-07 |
| D-L4 | Should rostering/assigning onto approved leave, or breaking rest/max-hours, warn, block, or stay silent? (extends P-12) | Silent (today) | SL-07 |
| D-L5 | Should employees be notified when their roster or default shift changes? | No | SL-11 |
| D-L6 | Recoverable correction workflow and impact preview for published versions (SC-05, P-08) | Deferred by owner | SL-08 |
| D-L7 | On termination: cancel future roster rows and pending swaps? | No (today) | SL-07 |

## 24. Production-readiness assessment

| Dimension | Assessment | Basis |
|---|---|---|
| Functional correctness | **Pass** with SL-03 caveat | 411 tests; engine rules fixed on 15 Nov |
| Validation completeness | **Fail** | SL-02, SL-03, SL-05 |
| Assignment integrity | **Fail** (roster); Pass (default shift) | SL-02, SL-04 |
| Database integrity | **Pass with conditions** | strong constraints; SL-03/04/13 gaps |
| Concurrency safety | **Fail** | SL-01, SL-04 executed; SL-09 read |
| Authorization | **Pass** | 12 cross-tenant probes, `extra="forbid"`; role catalogue unverified |
| Attendance integration | **Pass with conditions** | queue sound; SL-03 engine effect unprobed, SL-10 |
| Leave integration | **Fail (policy gap)** | SL-07; one-directional |
| Payroll integration | **Pass** | no shift link; locked periods protect finalized pay |
| Frontend reliability | **Fail** | SL-06, SL-12; UI not exercised in a browser |
| Background processing | **Pass with conditions** | idempotent, deferred kick; SL-10 |
| Auditability | **Pass** | all lifecycle events audited with actor and before/after (swap detail thin) |
| Failure recovery | **Pass with conditions** | transactional; no idempotency keys; client loops (SL-06) |
| Migration safety | **Unknown for CI** | migrations apply cleanly to head (done here); new name-unique migration test not in CI job |

**By workflow:** shift creation — production safe with conditions (SC-05/06). Draft edit — **not production safe** (SL-01).
Publish — production safe with conditions (SL-01, SL-08). Default-shift assignment — production safe.
Roster — **not production safe** until SL-02/03. Swap — **not production safe** for self-service at scale (SL-04, SL-07).
Deactivation — production safe with conditions (SL-05). Soft delete — production safe.
Reassignment on termination / leave — insufficiently verified (SL-07).

**Insufficiently verified:** engine behaviour on a week-off+shift row; assign-while-employee-terminated race;
RLS under the runtime role for these probes; any behaviour at thousands of employees (no load test run);
browser and device behaviour of the web and mobile clients.

## 25. Prioritized implementation plan (not started)
1. **SL-01** (High, small, no dependency): version bump + token on nested edits; lock in publish.
2. **SL-04** and **SL-03** (small; each needs a migration, so owner merges): swap uniqueness, roster merged-row validation + CHECK after an impact query.
3. **SL-05 publish re-check** and **SL-02** after decisions D-L1/D-L2.
4. **SL-06** server-side multi-employee publish endpoint; client message fix.
5. **SL-09, SL-10, SL-12** hardening.
6. Policy-gated: SL-07, SL-08, SL-11.
7. Close the test gaps listed in §19 as each fix lands.

## 26. Acceptance criteria for closure
- SL-01: a stale or missing `If-Match` on any draft change is 409; every change bumps `version`; a parallel publish-vs-breaks-edit never publishes unseen breaks.
- SL-02/03: states unreachable by API and, for SL-03, by CHECK; migration runs on a copy containing both states.
- SL-04: N parallel swap creates yield one 201.
- SL-05/06/09/10/12: each has an automated test that failed before the change.
- Existing 411-test shift suite, `test_attendance_concurrency`, `test_recalc_queue` and the RLS runtime-role tests stay green.
- A multi-administrator session (two browsers) completes: edit, publish, assign, roster, swap with no silent overwrite.

---

## Appendix A — Probe log (disposable DB `hrms_audit_shift_probe`)
Script: scratchpad `probe_shift_lifecycle.py` (session-local, not in the repo). Results as executed:

| Probe | Result |
|---|---|
| P1a create week-off + shift | 422 |
| **P1b PATCH week-off on row with shift** | **200** |
| **P2a roster before joining date** | **201** |
| **P2b roster for employee with no employment** | **201** |
| **P3b breaks-only PATCH, `If-Match: 999`** | **200**, version unchanged |
| P3c/d second breaks-only save | 200; only the last break set remained |
| P4a publish future roster | 200 |
| **P4b deactivate shift used by PUBLISHED + DRAFT roster** | **200** |
| **P4c publish draft onto inactive shift** | **200** |
| P4d create roster on inactive shift | 422 `INACTIVE_SHIFT` |
| P5 bulk with conflicting 3rd date | 409; only the pre-existing row remained |
| **P6 4 parallel swap creates** | **4×201, 4 PENDING** |
| P8a 4 parallel create-version | 201, 409, 409, 409 |
| P8b 4 parallel roster create | 201, 409, 409, 409 |
| P8c 3 parallel publish of one draft | 200, 409, 409; one open version, previous correctly closed |

## Appendix B — Cross-company matrix (company B acting on company A's data)
GET shift, PATCH shift, DELETE shift, GET version, GET roster, PATCH roster, PUBLISH roster, DELETE roster,
roster for A's employee, assignment of A's shift to A's employee, B's roster using A's shift id, B's token with
A's `X-Company-Id` → **all 404**; list rosters filtered to A's employee → **200 with an empty list**.

## Appendix C — Cleanup
The disposable database `hrms_audit_shift_probe` is dropped when this report is delivered. `hrms_dev` and `hrms_test` were not modified.

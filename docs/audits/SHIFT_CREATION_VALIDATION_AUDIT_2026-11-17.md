# Shift Creation Validation Audit — 17 November 2026

Scope: what is checked when a shift is created (shift master, draft version, publish).
Phase 1 (sections 1-10) was a read-only audit. Phase 2 (section 11) records the implementation of
SC-01 to SC-04 under the owner decisions of 17 Nov 2026. **Status: implemented in the working tree,
tested, NOT committed - awaiting review.**
Baseline: branch `test`, HEAD `dd71571`, working tree dirty (139 paths, none touched by this audit).
Companion documents: `SHIFT_MANAGEMENT_AUDIT_2026-11-15.md`, `SHIFT_REMEDIATION_PLAN_2026-11-15.md`
(SH-xx ids there are the earlier findings; this report uses SC-xx).

Method: every finding below was checked by reading the cited code. Nothing was executed, so
runtime behaviour (what the engine does with a given stored value) is marked **read-only
verified** or **not probed** accordingly.

---

## 1. Executive summary

Shift creation validates the main things well: permission, name uniqueness (including rename),
type-specific fields, times, timezone allow-list, flexible/split structure, break structure,
breaks shorter than the shift, closed attendance periods, version overlap (database
constraint), concurrency tokens and audit. `POST /shifts/setup` runs create, fill and publish
in one transaction (the session commits once, in `core/db/session.py`).

Of the 10 items I reported in chat, after verification:

| Outcome | Items |
|---|---|
| Confirmed defect | 1 (name race), plus 2 new ones found while verifying (SC-02, SC-03) |
| Confirmed missing safeguard | 6 (dormant break checks), 7 (flexible-duration window), 5 (SPLIT breaks), plus SC-03b |
| Needs a policy decision before any change | 3 (effective date), 4 (shift length) |
| By design / optional enhancement, not a bug | 8, 9, 10 |
| **Withdrawn (my chat claim was wrong)** | 2 (rename duplicate check) |

Nothing found corrupts attendance or pay today. Real exposure is: two same-named shifts under
concurrency (SC-01), untrimmed or blank-looking names via the API (SC-02), and a typo in a
future `effective_from` that cannot be corrected without deleting the shift (SC-05, decision).

Uncommitted changes: `organisation/service.py` has 92 added lines, all of them
`request_calendar_recalc` calls in holiday calendar, weekly-off pattern, work calendar and
calendar exception methods (lines ~3770–4700). The shift creation code (lines 2160–3600) is
identical to HEAD. Other dirty files are attendance, leave, web and mobile work unrelated to
shift creation.

---

## 2. Existing validation inventory

All paths under `apps/api/src/hrms/modules/organisation/` unless noted. Line numbers are at HEAD
`dd71571` plus the working tree (shift code unchanged by the working tree).

### 2.1 Endpoints

| Endpoint | Handler | Notes |
|---|---|---|
| `POST /v1/shifts/setup` | `router.py:717`, `shift_setup.py:18` | create + fill + publish, one transaction |
| `POST /v1/shifts` | `router.py:737` → `service.create_shift` (`service.py:2160`) | name only; adds empty draft |
| `PATCH /v1/shifts/{id}` | `router.py:766` → `service.update_shift` (`service.py:2328`) | rename, deactivate |
| `POST /v1/shifts/{id}/versions` | `router.py:869` → `create_shift_version` (`service.py:3060`) | new draft |
| `PATCH /v1/shifts/{id}/versions/{vid}` | `router.py:918` → `update_shift_version` (`service.py:3223`) | draft only |
| `POST /v1/shifts/{id}/versions/{vid}/publish` | `router.py:969` → `publish_shift_version` (`service.py:3452`) | full validation |

All require `ORG.SHIFT.MANAGE` (`permissions.py:47`) and are company-scoped.

### 2.2 Checks by layer

| # | Check | Layer | Location |
|---|---|---|---|
| V1 | Permission and company scope | route | `router.py` dependencies |
| V2 | Name 1–100 characters; unknown fields rejected | schema | `schemas.py:1028` `ShiftCreate`, `:1038` `ShiftUpdate`, `:1478` `ShiftSetup` |
| V3 | Name unique per company, ignoring case and surrounding spaces, soft-deleted rows excluded | service | `_assert_shift_name_free` `service.py:2234`; called on create `:2175` and rename `:2363` |
| V4 | Code auto-assigned, serialised per company by advisory lock | service | `shared/auto_code.py` (`pg_advisory_xact_lock`) |
| V5 | `shift_type` in FIXED / FLEXIBLE / SPLIT | schema + DB CHECK | `schemas.py:1366`; `shift_version_shift_type_check` |
| V6 | Time format `HH:MM` | schema | `_TIME_PATTERN` |
| V7 | Timezone is IANA and on the company allow-list | schema + publish re-check | `schemas.py:693` `validate_schedule_timezone`; `service.py:2908` |
| V8 | `required_minutes` 1–1440 | schema | `schemas.py:1366`/`:1428` |
| V9 | Dormant fields (weekly-off pattern, scheduled/min/max minutes) refused | schema | `_reject_dormant_shift_version_fields` |
| V10 | Fields of another shift type refused | publish | `_validate_shift_version_type_fields` `service.py:2884` |
| V11 | `shift_type` and `effective_from` present | publish + DB CHECK | `service.py:2908`; `shift_version_published_required_check` |
| V12 | FIXED: both times, start ≠ end; overnight derived by server | publish | `service.py:2908`, `_derive_cross_midnight` `:2600` |
| V13 | FLEXIBLE: window and required minutes present, window end after start, core hours as a pair and in order | publish | `service.py:2908` |
| V14 | SPLIT: ≥2 blocks, sequence 1..n, each start ≠ end, no overlap, whole sequence fits in 24h | publish | `_validate_duty_blocks_for_publish` `service.py:2789` |
| V15 | Break: unique name, kind-specific fields, min ≤ max, scheduled within min/max (flexible), fixed windows do not overlap | save + publish | `_validate_shift_breaks` `service.py:2621` |
| V16 | Fixed breaks inside the shift (FIXED, FLEXIBLE only) | publish | `_validate_breaks_boundaries_for_publish` `service.py:2837` |
| V17 | Breaks together shorter than the shift | publish | `_validate_breaks_shorter_than_shift` `service.py:3004` |
| V18 | Break `mode` refused while `shift_break_modes_enabled` is false (default) | schema | `schemas.py:1247`, `core/config/settings.py:371` |
| V19 | Weekly-off pattern reference exists | create/update version | `service.py:3060`, `:3223` |
| V20 | Backdated publish refused inside a CLOSED attendance period | publish | `service.py:3494` → `AttendanceService.assert_date_open` |
| V21 | New version starts after the current published one; second concurrency token | publish | `service.py:3503–3510` |
| V22 | No overlapping published versions | DB | `shift_version_no_overlap` (GiST exclusion, migration `20260818140000`) |
| V23 | One open draft per shift | DB | `shift_version_one_open_draft_idx` |
| V24 | Optimistic concurrency (`If-Match`) | route + repo | all PATCH/publish |
| V25 | Recalculation queued for days already calculated against this shift | publish | `service.py:3585` → `attendance/recalc.py:48` |
| V26 | Audit record for shift, draft, publish | service | `SHIFT_CREATED`, `SHIFT_VERSION_CREATED`, `SHIFT_VERSION_PUBLISHED` |
| V27 | DB: end ≥ start for date range; break min ≤ max; duty block time range; unique block sequence | DB | migration `20260818140000` |

### 2.3 Client-side (web)

`apps/web/src/lib/shift/validate-shift.ts` trims the name and requires it.
`validate-shift-version.ts` mirrors type, time, core-hours, block-count and break checks.
Mobile uses the same API. The API is the authority; client checks are convenience only.

---

## 3. Findings

Classes: **D** confirmed defect, **S** missing safeguard, **C** capability gap (feature not
built), **P** needs a policy decision, **E** optional enhancement, **W** withdrawn.

| ID | Chat item | Class | Severity | Likelihood | Business impact |
|---|---|---|---|---|---|
| SC-01 | 1 | D | Medium | Low | Two shifts with one name |
| SC-02 | new | D | Low | Medium | Untrimmed or blank-looking names |
| SC-03 | new | S | Low | Low | Break window outside the shift |
| SC-04 | 6 | S | Low | Low (dormant) | Weak checks once break modes ship |
| SC-05 | 3 | P | Medium | Low | Uncorrectable future date |
| SC-06 | 4 | P | — | — | Whether 23h59m is acceptable |
| SC-07 | 5 | C | Low | Low | SPLIT breaks unchecked |
| SC-08 | 7 | C | Low | Medium (night shifts) | No flexible break across midnight |
| SC-09 | 8 | E | — | — | Night/OT flag consistency |
| SC-10 | 9 | E (by design) | — | — | Draft permissiveness |
| SC-11 | 10 | E | — | — | Duplicate timings, caps, impact preview |
| SC-12 | 2 | W | — | — | Rename is checked |

### SC-01 — Duplicate shift name under concurrent creates (D, Medium)

**Evidence.** `_assert_shift_name_free` (`service.py:2234`) is a plain `SELECT`. Its own
docstring says there is no unique index and a race can pass both. Confirmed: `models.py:236`
`Shift` has no `__table_args__` constraint on name; the only shift index created is
`shift_company_id_idx` (`alembic/versions/20260813170000_shift_rules.py:60`). In `create_shift`
the name check (`:2175`) runs before `next_auto_shift_code` (`:2178`), which is the first point
that takes a lock (advisory lock, `shared/auto_code.py`). So the lock does not protect the check.
The remediation plan (`SHIFT_REMEDIATION_PLAN_2026-11-15.md` section on SH-21) records the same caveat.
Rename is also unprotected (`:2363`).

**Root cause.** Uniqueness enforced in application code only.

**Business impact.** Two shifts both named "Morning" appear in roster, assignment and swap
pickers; users cannot tell them apart. Needs a double submit, a retry, or two admins at once.

**Remediation.**
1. Partial unique index on `shift (company_id, lower(btrim(name))) WHERE deleted_at IS NULL`.
2. Map the resulting `IntegrityError` to the existing `ShiftNameAlreadyExistsError` on create and rename.
3. Keep the service check for the friendly early error.

**Dependencies.** Migration must first find existing duplicates (see section 7). Decision D-1.

### SC-02 — API stores names untrimmed and accepts whitespace-only (D, Low)

**Evidence.** `ShiftCreate.name`, `ShiftUpdate.name`, `ShiftSetup.name` are
`Field(min_length=1, max_length=100)` with `ConfigDict(extra="forbid")` only (`schemas.py:1028`,
`:1038`, `:1478`); no strip validator (`grep strip` in `schemas.py` shows none for these).
`create_shift` stores `body.name` as received (`create_shift`, `service.py:2160`+). The uniqueness check strips,
so `"  morning "` is detected as a duplicate (covered by `test_shift.py:458` onward) but a
first shift can still be saved as `"   "` or `" Morning "`. The web form trims
(`validate-shift.ts:24`), so only API or mobile callers reach this. The same applies to break
names (`ShiftBreakCreate.name`, `schemas.py:1205`), whose uniqueness check also strips
(`service.py:2630`).

**Root cause.** Normalisation done in the web client only.

**Business impact.** Blank-looking shift in pickers; stored names differ from what the
uniqueness check compares.

**Remediation.** Strip and re-check `min_length` on shift name and break name at the schema.
Existing stored names are left unchanged (see D-2).

### SC-03 — Break windows are only contained in the shift for fixed breaks (S, Low)

**Evidence.** `_validate_breaks_boundaries_for_publish` (`service.py:2837`) skips SPLIT
(`:2859`) and skips every break that is not `FIXED_WINDOW` (`:2877`). A `FLEXIBLE_DURATION`
break whose `window_start`–`window_end` lies wholly outside a FIXED shift passes. **Not probed:**
what the engine then does with such a break (read-only verification only).

**Business impact.** A break that can never be taken inside the shift; unclear deduction behaviour.

**Remediation.** Apply the same containment test to flexible-duration windows for FIXED and
FLEXIBLE shifts. Decision D-5 (whether partial overlap is allowed).

### SC-04 — Duration checks skipped for legacy-mode breaks (S, Low, dormant)

**Evidence.** `_validate_break_durations` returns immediately when `brk.mode is None`
(`service.py:2688`). Because `shift_break_modes_enabled` defaults to false (`settings.py:371`)
and the schema refuses a mode while it is false (`schemas.py:1247`), every break created today
has `mode=None`, so these checks never run: `max_minutes ≥ 1`, scheduled ≤ max, scheduled ≥ min
across all kinds, and AUTO_DEDUCT rules. What still runs for legacy breaks: kind-specific
fields, min ≤ max, scheduled within min..max for flexible breaks (`service.py:2621`+), and the DB
`shift_break_min_max_check`. Reachable today: a flexible-duration break with `max_minutes=0`
(schema allows `ge=0`).

**Business impact.** None for AUTO_DEDUCT while modes are off; becomes live the moment modes
are enabled for existing stored breaks. Existing remediation note SH-12/SH-15 already says to
fix before exposing modes.

**Remediation.** Run the shared duration rules for every break regardless of mode, or make
enabling the flag depend on this fix. Decision D-6.

### SC-05 — `effective_from` has no sanity guard (P, Medium)

**Evidence.** `ShiftVersionCreate/Update.effective_from: date | None` (`schemas.py:1380`, `:1438`)
with no validator. Publish checks only: present, not in a closed period (`service.py:3494`),
and later than the current published version (`:3503`). DB check only `effective_to >= effective_from`.

What the code does with the value (read-only verified):
- Past date: `request_recalc` is clamped to today and limited to days already calculated against
  this shift (`attendance/recalc.py:62–70`). A first version in the past is harmless; a past
  second version recalculates only that shift's affected days and is blocked in closed periods.
- Future date: no recalculation; the shift simply has no schedule until then. A published
  version cannot be edited and the next version must start after it (`service.py:3503`), so a
  future typo cannot be corrected by a new version before that date. The only route found is
  deleting the shift, which is blocked once it was ever assigned or used (`delete_shift`).

**Why this is a decision, not a bug.** The request forbids inventing a limit. The report
therefore lists the options and no number.

**Decision D-3 options.** (a) No change. (b) Confirmation prompt on dates far from today, threshold
chosen by you. (c) Company setting for the allowed range. (d) Allow correcting an unassigned
future published version.

### SC-06 — No maximum shift length (P)

**Evidence.** FIXED: end ≠ start, so the longest is 23h59m by construction (`service.py:2908`
FIXED branch). FLEXIBLE: `required_minutes ≤ 1440` (`schemas.py:1388`). SPLIT: whole sequence
≤ 24h (`service.py:2789`, `InvalidShiftVersionDutyBlockSpanError`). So nothing can exceed 24
hours; the open question is whether anything over some shorter length should be refused or
warned. That depends on policy (statutory daily hours, overnight security shifts, etc.).

**Decision D-4.** Is a ceiling wanted at all? If yes, hard error or warning, and the number.
No change proposed without it.

### SC-07 — SPLIT breaks cannot be checked against duty blocks (C, Low)

**Evidence.** `ShiftBreak` (`models.py:322`) has no `duty_block_id`; the docstring at
`service.py:2837` states containment is skipped for SPLIT for this reason. SPLIT still gets the
"breaks shorter than total block time" check (`:3004`).

**Remediation.** Needs a schema change (nullable `duty_block_id`, migration) plus API, clients and
engine awareness. Only worth doing if SPLIT shifts with breaks are used. Decision D-7.

### SC-08 — Flexible-duration break window cannot cross midnight (C, Low)

**Evidence.** Rejected at `service.py:2658` (`window_end <= window_start`). The engine has the
same assumption: `attendance/break_rules.py:233–235` skips a rule whose end is not after its
start, and `crosses_midnight` is only stored for `FIXED_WINDOW` (`service.py` `_build_break_rows`).
Validation and engine are consistent, so this is a limitation, not a mismatch bug.

**Remediation.** Engine change first, then relax validation. Decision D-8 (is it needed for
night shifts?).

### SC-09 — Night / OT flags not cross-checked with times or policy (E)

**Evidence.** `is_night_shift` is deliberately explicit (`schemas.py:1366` docstring citing
architecture §9.5). The engine reads it only when the policy's `night_ot_mode` is `SHIFT_FLAG` or
`BOTH` (`calculation.py:1795–1830`); `WINDOW` mode ignores it. `is_ot_eligible` is combined with
the policy at calculation (`calculation.py:3270`, `:3541`). Core hours are documented as
independent of the start window (`_validate_and_derive_for_publish` comment, FLEXIBLE branch). None of this is wrong; at most a
warning would help.

### SC-10 — Draft permissiveness (E, by design)

**Evidence.** `ShiftVersionCreate` docstring: "a draft may be incomplete mid-edit; only publish
enforces the full set". `setup_shift` publishes by default, so the setup flow validates
immediately. Not a defect.

### SC-11 — Duplicate timings, count caps, publish impact preview (E)

**Evidence.** No code for any of these. Two shifts with identical timings, any number of
breaks/blocks/shifts, and publish without preview are all allowed. These are enhancements; no
policy requires them in the repository.

### SC-12 — Rename duplicate check (W, withdrawn)

My chat summary listed this as unconfirmed. It is covered: `update_shift` calls
`_assert_shift_name_free(..., except_id=shift_id)` (`service.py:2362–2363`) and
`test_shift.py` exercises a rename to `"MORNING"` returning 409. Only the concurrency issue
(SC-01) remains.

### Other observations (no finding)

- Code generation is race-safe (advisory lock), contrary to my initial worry.
- `setup_shift` is atomic: one session commit (`core/db/session.py:76`); a publish
  `IntegrityError` rolls back the whole setup (`service.py` publish path).
- A deactivated shift still reserves its name (the name check ignores only `deleted_at`).
  Treated as a decision D-1, not a defect.

---

## 4. Policy decisions requiring your approval

| ID | Decision | Affects |
|---|---|---|
| D-1 | Should a deactivated (not deleted) shift keep reserving its name? Today it does. | SC-01 index design |
| D-2 | Existing shifts whose stored name has surrounding spaces: leave, or normalise in the migration? | SC-01, SC-02 |
| D-3 | Do you want any guard on `effective_from`? Options in SC-05. No limit will be implemented without your number. | SC-05 |
| D-4 | Is a maximum shift length wanted? Hard error, warning, or nothing? Number if yes. | SC-06 |
| D-5 | Must a flexible-duration break window lie fully inside the shift, or may it overlap partly? | SC-03 |
| D-6 | Fix legacy-break duration checks now, or only before break modes are enabled? | SC-04 |
| D-7 | Are SPLIT shifts with breaks in use? Is a duty-block link on breaks worth building? | SC-07 |
| D-8 | Are night-shift flexible breaks needed (engine change)? | SC-08 |

SC-09 to SC-11 need a decision only if you want them promoted from enhancement to scope.

---

## 5. Database migration requirements

| Finding | Migration | Pre-check |
|---|---|---|
| SC-01 | `CREATE UNIQUE INDEX CONCURRENTLY` on `shift (company_id, lower(btrim(name))) WHERE deleted_at IS NULL` | Query for existing duplicates first; resolve or abort. Memory notes only test data so far, still verify per environment. |
| SC-02 | none | — |
| SC-03, SC-04 | none | — |
| SC-05, SC-06 | none (unless D-3 chooses a company setting) | — |
| SC-07 | nullable `shift_break.duty_block_id` + FK | only if D-7 says yes |
| SC-08 | none for validation; engine change separate | only if D-8 says yes |

Downgrade for SC-01: drop the index. Rollback is safe.

---

## 6. Implementation sequence

1. **SC-02** schema name normalisation (no dependency, smallest).
2. **SC-01** pre-check query, migration, `IntegrityError` mapping (needs D-1, D-2).
3. **SC-04** shared break duration rules for every mode (needs D-6); must land before any
   enablement of `shift_break_modes_enabled`.
4. **SC-03** containment for flexible-duration windows (needs D-5; do together with SC-04 since both
   live in the break validators).
5. **SC-05 / SC-06** only after D-3 / D-4 are answered.
6. **SC-07 / SC-08** only if D-7 / D-8 say yes; engine and clients follow validation.
7. Update `SHIFT_REMEDIATION_PLAN` section on SH-21 to point to this report.

Steps 1–4 touch only `organisation/schemas.py`, `organisation/service.py`, one new migration and
tests, so they conflict with the working tree's `service.py` edits only by proximity (the working
tree edits are in the calendar methods, lines ~3770+). Changes must be made without stashing,
resetting or checking out: edit in place, in separate commits touching only these files.

---

## 7. Detailed test matrix

Existing coverage: `tests/integration/modules/organisation/test_shift.py` (18 tests, SH-21 block at
`:458`), `test_shift_version.py` (30 tests, SH-06 and SH-11 included),
`tests/unit/modules/organisation/test_shift_service.py`.

### SC-01 — name race

| # | Test | Type | Expected |
|---|---|---|---|
| 1 | Two concurrent `POST /shifts` with same name (two sessions, barrier) | integration | exactly one 201, one 409 `SHIFT_NAME_ALREADY_EXISTS` |
| 2 | Same with case/space variants | integration | one 409 |
| 3 | Concurrent rename of two shifts to one name | integration | one 409 |
| 4 | Concurrent `POST /shifts/setup` same name | integration | one 409, no orphan draft or version left |
| 5 | Same name in two companies | integration | both succeed |
| 6 | Name of a soft-deleted shift reused | integration | succeeds |
| 7 | Deactivated shift's name reused | integration | per D-1 |
| 8 | Migration with seeded duplicates | migration | aborts with a clear message; nothing partial |
| 9 | Migration on clean data, downgrade, upgrade | migration | index appears and disappears |
| 10 | Regression: existing uniqueness test at `test_shift.py:458` | integration | still passes |

### SC-02 — name normalisation

| # | Test | Expected |
|---|---|---|
| 1 | `"   "` on create, setup, rename | 422 |
| 2 | `"  Morning "` | stored `"Morning"` |
| 3 | Break name `"  Lunch "` stored trimmed; duplicate `"lunch"` rejected | 422 |
| 4 | 100-char name with trailing spaces | accepted after trim |
| 5 | Unicode/non-ASCII name | accepted unchanged |
| 6 | Regression: web `validate-shift` tests | unchanged |

### SC-03 — flexible-duration containment (after D-5)

| # | Test | Expected |
|---|---|---|
| 1 | Window wholly outside FIXED shift | publish 422 |
| 2 | Window inside | publish OK |
| 3 | Partial overlap | per D-5 |
| 4 | Overnight FIXED shift with window in the after-midnight half | OK |
| 5 | FLEXIBLE shift | bound as for fixed breaks (SH-11 test must still pass) |
| 6 | SPLIT shift | unchanged (skipped) |

### SC-04 — duration rules for legacy breaks (after D-6)

| # | Test | Expected |
|---|---|---|
| 1 | Flexible break `max_minutes=0` | 422 |
| 2 | scheduled > max, scheduled < min | 422 |
| 3 | FIXED_WINDOW with scheduled longer than its window | per D-6 |
| 4 | Existing valid stored breaks load and republish | no regression |
| 5 | Flag on: AUTO_DEDUCT rules still enforced | unchanged |

### SC-05 / SC-06 (only after decisions)

| # | Test | Expected |
|---|---|---|
| 1 | Characterisation: far-past and far-future first version publishes today | passes (documents current behaviour until D-3) |
| 2 | Characterisation: 23h59m FIXED publishes; 24h FLEXIBLE publishes | passes until D-4 |
| 3 | Future typo version: later version before it is refused | `InvalidShiftVersionEffectiveFromError` (documents the trap) |
| 4 | Decision-specific tests | written once the decision is made |

### Regression pack for every change

Shift create/setup/rename/deactivate/delete; version create, patch, publish, overlap constraint,
closed-period refusal, recalculation queued; SPLIT, FLEXIBLE, overnight FIXED publish; break
overlap and containment (SH-11); timezone allow-list (SH-06); web and mobile contract fixtures
for shift schemas; openapi/contract snapshot if names or error codes change.

---

## 8. Regression risks

| Risk | Where | Mitigation |
|---|---|---|
| Unique index breaks existing duplicate data on deploy | SC-01 migration | pre-check, `CONCURRENTLY`, abort cleanly |
| Trimming changes names clients already display or match on | SC-02 | trim at write only; leave stored rows; web already trims |
| Stricter break checks reject drafts that publish today | SC-03, SC-04 | run validators over existing stored versions as a report first; republish only blocked, existing published rows untouched |
| Concurrency fix leaves orphan rows in `setup` | SC-01 | tests 1 and 4 assert rollback |
| Editing `service.py` with the dirty tree | all | edit in place, never stash/reset/checkout; stage only named files |
| Error-code or schema change reaches clients | SC-01, SC-02 | existing code `SHIFT_NAME_ALREADY_EXISTS` reused; contract fixtures checked |

---

## 9. Acceptance criteria

1. Every confirmed finding (SC-01, SC-02, and SC-03/SC-04 once decided) has a failing test before
   the fix and a passing one after.
2. No change to SC-05, SC-06, SC-07, SC-08 without the matching decision recorded here.
3. Full organisation and attendance integration suites pass; no new skips.
4. New migration upgrades and downgrades on a database seeded with duplicates and with clean data.
5. Concurrency tests pass repeatedly (run at least 20 times) with no orphan shift or draft rows.
6. `git diff` of the fix commits touches only the files named in section 6; the pre-existing
   uncommitted changes remain uncommitted and unmodified.
7. This report updated with results and the remediation plan cross-referenced.

---

## 10. Corrections to my earlier chat summary

- Item 2 (rename duplicate check): wrong, it is checked (SC-12).
- Item 8: described as a gap; it is an explicit design choice (SC-09).
- Item 9: by design (SC-10).
- Items 3 and 4: I called them "small to fix"; they are policy decisions and I recommended
  limits without a basis. Withdrawn.
- Added: SC-02 (name trimming), SC-03 (flexible-duration containment).
- "Uncommitted changes in `service.py` not separated": now separated, none affect shift creation.


---

## 11. Implementation status (17 November 2026)

Nothing below is committed or staged. SC-05 to SC-08 were not touched.

### 11.1 Owner decisions applied

| ID | Decision | Effect |
|---|---|---|
| D-1 | Deactivated shifts keep their names | Index and check ignore `is_active`; only `deleted_at` releases a name |
| D-2 | No automatic normalisation; compare with `lower(btrim(name))`; detect collisions and blank names before migrating and abort with a report | Migration reports and stops; no row is ever changed |
| D-3 | No arbitrary effective-date limit; defer SC-05, document the need for a recoverable correction workflow | Not implemented; see 11.6 |
| D-4 | No new maximum shift length | Not implemented; existing type-specific limits unchanged |
| D-5 | Flexible break windows wholly inside the applicable shift window | SC-03 |
| D-6 | Fix generally applicable legacy duration checks; do not enable modes | SC-04 |
| D-7 | Defer SPLIT break-to-block relationship | SPLIT still skipped |
| D-8 | Defer midnight-crossing flexible breaks | Still refused |

### 11.2 Status

| ID | Status | Where |
|---|---|---|
| SC-02 | Implemented (done first) | `organisation/schemas.py`: `ShiftName` (trim, then length 1-100) on `ShiftCreate`, `ShiftUpdate`, `ShiftSetup`, `ShiftBreakCreate` |
| SC-01 | Implemented | advisory lock + `IntegrityError` mapping in `service.py` (`_assert_shift_name_free`, `create_shift`, `update_shift`); migration `20261117090000_shift_name_unique.py` |
| SC-04 | Implemented | `service.py` `_validate_break_durations` runs for every break; only the AUTO_DEDUCT rule still depends on `mode` |
| SC-03 | Implemented | `service.py` `_validate_breaks_boundaries_for_publish` now checks flexible-duration windows too (FIXED and FLEXIBLE shifts; SPLIT skipped) |
| SC-05 to SC-08 | Deferred / unchanged | per decisions |

### 11.3 What changed, exactly

**SC-02.** A name is trimmed (all whitespace, including tabs and newlines) before the length check, so
`"  Morning "` is stored as `"Morning"` and a blank name is a 422. Same for break names. The JSON schema
of every shift model is byte-identical before and after (checked by dumping `model_json_schema()` from
HEAD and from the working tree), so OpenAPI and the mobile contract fixtures are unaffected.

**SC-01.** Three layers.
1. `_assert_shift_name_free` first takes `pg_advisory_xact_lock(hashtext('shift_name:' || company || ':' ||
   lower(btrim(name))))`. A concurrent create or rename of the same normalised name waits for the first
   transaction to commit and then sees it, giving the existing clean 409 `SHIFT_NAME_ALREADY_EXISTS`.
   Different names do not contend; the lock is taken before the code-assignment lock, so there is no
   lock-order cycle. `POST /shifts/setup` is one transaction, so the lock is held across create, fill and
   publish.
2. Partial unique index `shift_company_live_name_key ON shift (company_id, lower(btrim(name))) WHERE
   deleted_at IS NULL`. `create_shift` and `update_shift` turn its violation into the same 409.
3. Check constraint `shift_live_name_not_blank_check` refusing a blank live name (regex
   `^[[:space:]]*$`, so tabs and newlines count as blank).

**Migration `20261117090000`** (revises `20261116120000`):
- `SET LOCAL lock_timeout = '15s'`, then `LOCK TABLE shift IN SHARE ROW EXCLUSIVE MODE` (reads continue,
  writes wait), so nothing can be created between the check and the build.
- Refuses to run as a role subject to row-level security (it would see no rows and report "clean").
- Counts live blank names and live duplicate groups. If either exists it raises one exception that lists,
  for each: company id, shift id(s), code, active flag and the quoted name, and states "no row was
  changed" (first 100 of each kind). Same pattern as `20261027091000`.
- Otherwise builds the index and adds the check, in one transaction. Downgrade drops both and keeps data.
- Never edits, renames, merges or deletes a row.

**SC-04.** The numeric rules now run for every break: `max_minutes >= 1`; `min <= max`; `scheduled <=
max`; `scheduled >= min`; a fixed window's `scheduled_minutes` must not exceed the window (wrap-aware).
Messages and `INVALID_SHIFT_BREAK` code are unchanged; the field is `breaks.<index>`. The one
mode-dependent rule (an AUTO_DEDUCT flexible break needs `scheduled_minutes`) is unchanged and still only
runs when a mode is present. The schema still refuses any `mode` while `shift_break_modes_enabled` is false
(default). No mode was enabled or given new behaviour. Rules apply only when `breaks` is sent; stored
breaks are not re-validated by an unrelated save.

**SC-03.** At publish, a `FLEXIBLE_DURATION` break's `window_start`-`window_end` must be wholly inside the
shift's window using the same wrap-aware containment and the same bounds as fixed breaks (FIXED: start to
end; FLEXIBLE: window start to window end plus `required_minutes`, SH-11). Error is the existing
`INVALID_SHIFT_BREAK` "break falls outside the shift's scheduled window". Drafts may still hold any window
until publish (the shift times may not exist yet), exactly as for fixed breaks. SPLIT is skipped (D-7).
Published versions are never re-validated.

### 11.4 Files

Modified, entirely mine:
- `apps/api/src/hrms/modules/organisation/schemas.py`

Modified, **shared with other uncommitted work** (must be staged by hunk, see 11.7):
- `apps/api/src/hrms/modules/organisation/service.py` - my 10 hunks are the constant (line ~279) and
  lines ~2182-2920; the other 7 hunks (line ~3816 onward) are the unrelated `request_calendar_recalc` work.
- `apps/api/tests/conftest.py` - my one line adds `test_shift_name_unique_migration.py` to
  `_QA_SANDBOX_ONLY`; the line `"test_attendance_r2_migrations.py",` above it belongs to other work.

New:
- `apps/api/alembic/versions/20261117090000_shift_name_unique.py`
- `apps/api/scripts/sql/shift_name_and_break_rules_impact_report.sql` (read-only impact report)
- `apps/api/tests/unit/modules/organisation/test_shift_name_schema.py` (48 tests)
- `apps/api/tests/unit/modules/organisation/test_shift_break_validation.py` (32)
- `apps/api/tests/integration/modules/organisation/test_shift_name_integrity.py` (26)
- `apps/api/tests/integration/modules/organisation/test_shift_break_rules.py` (27)
- `apps/api/tests/integration/migrations/test_shift_name_unique_migration.py` (14, QA sandbox)
- this report

No change to web or mobile code. No change to `.github/`, `.env`, or any other uncommitted file.

### 11.5 Test evidence

Environment: throwaway databases only (`hrms_sc_test` on the dev Postgres container, migrated to head
including the working tree's uncommitted migrations; a disposable `postgres:16-alpine` on 127.0.0.1:15432 for
the migration sandbox exactly as CI's migration job sets it up). All removed afterwards. `hrms_dev` was
only read (the impact report).

| Run | Result |
|---|---|
| Baseline before any change: `test_shift.py`, `test_shift_version.py`, organisation unit | 256 passed |
| New unit tests (names, break validation) | 80 passed |
| New integration tests (names, break rules) | 53 passed; name file repeated 3 times, stable |
| New migration tests, QA sandbox | 14 passed (N1-N11, see below) |
| Organisation unit + integration + migrations dir, final code | 734 passed, 48 skipped (the skips are the sandbox-only migration files in a plain run) |
| Wide regression: all unit + organisation + attendance + leave + employee integration | 5173 passed, 22 skipped, 1 xfailed, **1 failed** |
| Sandbox guards: `test_migration_test_guards.py` with the new file | 13 passed (27 total with the 14) |
| Web: `vitest` on `src/lib/shift` and `src/app/app/shifts` | 64 passed (7 files) |
| `ruff check`, `ruff format --check`, `mypy src/hrms/modules/organisation` | clean |

The one failure, `tests/integration/modules/attendance/test_punch_after_last_working_day.py::
test_self_punch_on_last_working_day_passes_and_after_it_is_rejected` ("DID NOT RAISE AppError"), is
**pre-existing and unrelated**: it fails identically when run against the fully committed HEAD source
(`git archive HEAD` copy of `apps/api/src`) and against HEAD organisation files over the working tree. I
did not investigate or touch it.

**Tests fail without the fix.** Running the new tests against HEAD `service.py`/`schemas.py` (copy in the
scratchpad, working tree untouched) fails 75 of 133 (the unique index was left in the database, which is why
not all do). A reproduction of the old check-then-insert with no lock and no index: 8 rounds of 4 parallel
creates produced 24 duplicate shifts (32 shifts for 8 names). With the index alone and the old check there
were none, and the loser received a mapped 409, which is the backstop path.

**Migration cases (sandbox).** N1 clean data, no row rewritten (table digest unchanged) and empty table;
N2 duplicates (case, spaces, one inactive, two companies) abort with a report naming every company, shift
id, code and "active=false", version unchanged, no index, digest unchanged, then succeeds after manual
renames; N3 blank names (empty, spaces, tab/newline) reported, good shift not listed, and blank plus
duplicate reported together; N4 deleted shifts never conflict; N5 a deactivated shift still conflicts (D-1);
N6 the same name in five companies is fine; N7 afterwards the database refuses a duplicate and a blank live
name but allows another company, a released name, a blank deleted row, a rename, and deactivation does not
release a name; N8 downgrade removes both objects and keeps data, re-upgrade works; N9 padded and
mixed-case stored names are untouched (D-2); N10 an uncommitted writer in flight is waited for and its
duplicate is then caught; N11 a held ACCESS EXCLUSIVE lock makes the migration fail on lock timeout with
nothing half-applied, and it succeeds once released.

**API and concurrency cases (integration).** Trim and blank refusal on create, rename, setup and break names;
duplicates by case, spaces and tab; two companies; deactivated keeps its name (D-1); deleted releases it;
rename clash and rename to own name; 4 parallel creates of one name over 8 rounds (exactly one 201, three
409, one draft per shift); 6 parallel creates of different names (all succeed, distinct codes); 3 parallel
setups of one name over 8 rounds (no orphan shift or draft); 3 parallel renames to one name over 8 rounds;
a create racing a rename; raw SQL duplicate and blank refused by the database; a write that skips the check
is turned into the same 409 for create and rename; a legacy padded name is still listed and still blocks
its trimmed duplicate. Break rules: 8 incoherent duration shapes refused at save with `breaks.0`; flexible
windows inside, equal, after, before, early start, late end for FIXED; overnight (before midnight, after
midnight, daytime gap); FLEXIBLE shift bounds; SPLIT unchanged; draft keeps an outside window until publish;
a published version with an outside break is left alone and a following version publishes; saving other
fields does not re-validate stored breaks; fixed-break rules unchanged; setup with a bad break leaves no
shift; modes still refused while the feature is off.

### 11.6 Compatibility and unaffected data

- **API:** error code `SHIFT_NAME_ALREADY_EXISTS` (409) and `INVALID_SHIFT_BREAK` (422) are reused; no new
  code, field or status. The generated JSON schemas of `ShiftCreate`, `ShiftUpdate`, `ShiftSetup`,
  `ShiftBreakCreate`, `ShiftVersionCreate`, `ShiftVersionUpdate`, `ShiftRead`, `ShiftBreakRead` are identical
  to HEAD, so the OpenAPI document and `apps/mobile/test/fixtures/contract` need no refresh.
- **Web:** `validate-shift.ts` already trims the name; break errors arrive as `breaks.<n>` and are shown as a
  message on the breaks section (`mapShiftVersionApiErrors`). The web form only sends min/max for flexible
  breaks, so the new fixed-break min/max rules cannot be hit from the form; `scheduled_minutes` over a fixed
  window and a flexible window outside the shift now give a readable message there. 64 web shift tests pass.
- **Mobile:** has no shift or break editing screen (only the attendance policy and calendar), so there is
  no payload to break.
- **Existing data:** dev database (`hrms_dev`, read-only): 9 live shifts, 7 breaks, 9 published versions;
  **0** blank names, **0** duplicate groups, **0** stored breaks failing a duration rule, **0** flexible breaks
  outside their shift. The new report script was proved on seeded bad data (flagged the blank, the duplicate
  including an inactive one, three duration violations and one outside window; did not flag the clean rows).
  Assignments, rosters, published versions and attendance calculations are not read or written by any of
  these changes; the attendance, leave and employee suites above pass (apart from the one pre-existing
  failure). Run the report against each real environment before applying the migration there.

### 11.7 SC-05 deferred: the need for a recoverable correction workflow (D-3)

No limit was added. What the code does today (verified in 1-10): a published version cannot be edited; the
next version must have an `effective_from` after the current version's; deletion is blocked once a shift was
ever assigned, rostered or used. So a mistyped future `effective_from` on a first or latest version cannot
be corrected by a new version before that date, and the only exit (delete) disappears once the shift is
used. A recoverable workflow is needed, for example: allow withdrawing or correcting a published version
that has not started and is referenced by nothing (no assignment, roster row, calculated day or
regularization), with a reason and an audit record, and a clear block once anything references it. This is
a product design item (who may do it, what counts as "not started", effect on queued recalculation) and
is **not implemented**; it should be specified before any `effective_from` guard is considered.

### 11.8 Remaining risks and items for review

1. **Migration chain.** `20261117090000` revises `20261116120000`, which is itself uncommitted along with
   `20261116090000`, `20261116100000`, `20261116110000`. The four must be committed before or with mine, or
   the chain has two heads. Migrations under `apps/api/alembic/` are also a "person must merge" path in
   `AGENTS.md`.
2. **CI does not run the new migration test yet.** The migration job in `.github/workflows/ci.yml` lists its
   test files by name. Adding `test_shift_name_unique_migration.py` there means editing a protected file that
   also has uncommitted changes, so I did not. Until it is added the tests run only with `HRMS_QA_STRICT=1`.
3. **Shared files need hunk-level staging.** `service.py` and `tests/conftest.py` contain other people's
   uncommitted hunks (11.4). Plain `git add` of those files would commit work that is not mine.
4. **Migration can abort a deploy by design.** If a real environment has duplicate or blank live names, the
   upgrade stops until a person renames them. Run the report script there first. The dev database has none.
5. **Lock keys are hashed.** `hashtext` collisions only make two unrelated names wait for each other
   briefly; they cannot allow a duplicate.
6. **`btrim` versus tabs.** The index trims spaces only (as the existing check did); the schema now trims
   every whitespace character, so new names never have padding of either kind. A legacy name padded with a
   tab would compare unequal to its trimmed twin; the migration's blank detection uses the broader regex,
   and such a name is shown by the report (1c) as information only.
7. **SC-04 is stricter on re-save.** A draft that already holds an incoherent legacy break (for example a
   fixed break whose `scheduled_minutes` exceeds its window) will now be refused when its breaks are saved
   again. Published versions and stored rows are untouched. The dev database has none.
8. **Unrelated failing test** in attendance (above) should be looked at by whoever owns that work.


---

## 12. Commit hold and staging plan (17 November 2026)

Decision: **wait.** The SC-01 to SC-04 commit is held until the attendance, leave and overtime migrations it
sits on top of are committed. The migration is not re-parented. Nothing is staged or committed; the real
index is empty.

### 12.1 Migration dependency chain

| Revision | Parent | Committed? |
|---|---|---|
| `20261115090000` shift_remediation | `20261114090000` | yes (HEAD `dd71571`; the only head at HEAD) |
| `20261116090000` overtime_supersede_action | `20261115090000` | **no** |
| `20261116100000` leave_balance_shortfall | `20261116090000` | **no** |
| `20261116110000` leave_application_half_day | `20261116100000` | **no** |
| `20261116120000` attendance_policy_mark_credit_ceiling | `20261116110000` | **no** |
| `20261117090000` shift_name_unique (this work) | `20261116120000` | **no** (held) |

Checked by reading every revision file at HEAD and in the working tree: 141 revisions at HEAD with one head
(`20261115090000`); 146 in the working tree with one head (`20261117090000`), no dangling parent, no branch.
Expected Alembic head when this lands: **`20261117090000`**, provided nobody adds another migration first.
Shared dev database `hrms_dev` (SELECT only, never altered): one `alembic_version` row =
`20261117090000`, with the index and the check constraint present. It is ahead of the committed code until
these commits land.

### 12.2 Files that belong only to SC-01 to SC-04

New: `alembic/versions/20261117090000_shift_name_unique.py`, `scripts/sql/shift_name_and_break_rules_impact_report.sql`,
`tests/unit/modules/organisation/test_shift_name_schema.py`, `.../test_shift_break_validation.py`,
`tests/integration/modules/organisation/test_shift_name_integrity.py`, `.../test_shift_break_rules.py`,
`tests/integration/migrations/test_shift_name_unique_migration.py`, and this report.
Modified, whole file: `organisation/schemas.py` (its entire diff is SC-02; 7 hunks).
Shared (hunk only): `organisation/service.py`, `tests/conftest.py`.

### 12.3 Hunk plan for the two shared files

`service.py`, stage 10 hunks (`git diff -U0`, new-file line numbers): 279 (constant), 2182, 2247, 2260, 2278,
2395, 2720, 2753, 2890, 2919. Leave 7 (the calendar-recalculation work, all containing
`request_calendar_recalc`): 3816, 3911, 4020, 4245, 4497, 4642, 4734 (92 added lines).
`tests/conftest.py`, stage 1 hunk (the added line `"test_shift_name_unique_migration.py",` at line 188);
leave the added line `"test_attendance_r2_migrations.py",` at line 185.

Method (prepared and proven, not applied): `backups/sc01_04_commit_prep/stage_plan.py` writes a hunk-only
patch and applies it to a **temporary** index (`GIT_INDEX_FILE`) built from HEAD, then checks that the staged
`service.py` has no `request_calendar_recalc`, the staged `conftest.py` has no `attendance_r2`, and both
staged files compile. Real staging will use the same patch with `git apply --cached --unidiff-zero`, and no
`git add` of a whole shared file, no stash, no checkout. Result of the dry run: 11 paths, listed in 12.2, and
the working tree minus that staged set is exactly the other work. The whole folder is git-ignored
(`backups/`), so it is never part of a commit.

### 12.4 CI registration (prepared, not applied)

The migration job in `.github/workflows/ci.yml` is itself uncommitted (the file has 106 uncommitted lines
starting at line 293) and lists test files by name, so it cannot be changed without editing a protected and
shared file. The one-line change, verified with `patch --dry-run` against the working-tree file, is
`backups/sc01_04_commit_prep/ci_register_shift_name_migration_test.patch`:

```diff
@@ -368,6 +368,7 @@
         run: >-
           uv run pytest
           tests/integration/migrations/test_attendance_r2_migrations.py
+          tests/integration/migrations/test_shift_name_unique_migration.py
           tests/unit/core/test_migration_test_guards.py
```

Two further notes for whoever commits that job: `tests/integration/migrations/conftest.py` and
`tests/unit/core/test_migration_test_guards.py` are also untracked, and the required-pass counter in that
conftest only counts `test_attendance_r2_migrations.py`; with `HRMS_QA_STRICT=1` set by the job my file cannot
skip silently, but it is not counted in the minimum either.

### 12.5 Migration tested from the last committed state

Fresh disposable `postgres:16-alpine` (as CI's migration job), a scratch copy of the alembic tree containing
only the **committed** revisions plus my migration re-parented to `20261115090000` (scratch copy only; the
repository file still points at `20261116120000`), and my migration test with its starting revision set to
`20261115090000`: **14 of 14 pass** (clean upgrade, duplicate and blank reports, deleted shifts, deactivated
keeps its name, enforcement afterwards, downgrade and re-upgrade, no rewrite, writer in flight, lock timeout).
So the SQL does not depend on any of the four uncommitted migrations. The full working-tree chain also passed
earlier (14 of 14). The containers were removed afterwards.

### 12.6 Recheck once the dependencies land

Run `bash backups/sc01_04_commit_prep/recheck.sh` (read-only). It reports whether the four migrations are
committed, the graph at HEAD and in the tree and its heads, my migration's parent, the dev database version
(SELECT only), and re-proves the staging plan. After the dependencies land: confirm one head
`20261117090000` and the parent unchanged; regenerate the patch (hunks move if `service.py` or `conftest.py`
changed); rerun the SC test set and the organisation, attendance and leave suites; show the exact staged
diff; and **ask for approval before committing**. One commit, no unrelated change. No push without explicit
approval.

### 12.7 Risk while waiting

`service.py` and `tests/conftest.py` are shared. If anyone commits either file whole (`git add <file>`), my
hunks are swept into their commit. The recheck will notice this (my hunks would no longer appear in the
diff); if it happens the plan changes to "my work is already in commit X" and I will say so rather than
re-commit it.

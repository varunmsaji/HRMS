# HR rules fixes: handoff for any coding agent

**Read-only.** Do not edit, move or delete this file. If it disagrees with the code, trust the code
and tell the owner. Only the owner changes it, with `chmod u+w` first.

Written 6 Nov 2026. Everything below about status was true then, so check it with section 3 before
acting on it.

## 1. What this work is

An audit found that this HRMS can produce wrong pay, leave balances and overtime. This work fixes
those rules. The system is **NO-GO for payroll** until the "must fix" items are merged and the owner
has tried them in the app.

There is only test data today, so no old figures need protecting. That stops being true when a pilot
company starts: ask the owner if you are unsure.

Sources, in order:

1. `AGENTS.md` at the repo root, and `apps/web/AGENTS.md`. They bind you and override this file.
2. The rules audit, findings R-01 to R-18. It is not on `test` or `main`. Read it with:
   `git show 04ba31d:docs/audits/HRMS_RULES_POLICY_ATTENDANCE_AUDIT_2026-11-05.md`
3. The earlier audit, findings F1 to F11 and decisions D-1 to D-9:
   `docs/audits/ATTENDANCE_LEAVE_POLICY_OVERTIME_INTERACTION_AUDIT_2026-11-04.md`

## 2. Rules you must follow

- Work on `test`. Never commit to or push `main`, never force-push, never merge a PR yourself.
- If the working tree has changes you did not make, leave them alone and tell the owner. Section 4
  may describe them.
- Stage files by name. Never `git add .` or `git add -A`.
- Never skip or weaken a check to get a build passing. If a test seems wrong, ask the owner. Some tests
  record behaviour as a "characterization": changing one needs an owner decision, stated in your report.
- A PR touching `apps/api/alembic/`, `.github/`, `.gitleaks.toml`, `AGENTS.md` or `CLAUDE.md` does
  not auto-merge. Tell the owner it is waiting for them. Keep migrations out of a PR that could
  otherwise auto-merge.
- Report honestly what you ran and what you did not. CI passing does not mean the app was tried.

### Rule changes in this codebase

- All day calculation is in `apps/api/src/hrms/modules/attendance/calculation.py` (`evaluate_day`), a
  pure function with no database.
- Any change to what the engine calculates must bump `ENGINE_VERSION` and extend the comment above it.
- The backend decides every rule. If a rule's meaning changes, update its wording everywhere:
  the policy form and templates in `apps/web/src`, `apps/mobile/lib`, and
  `apps/web/src/lib/settings-guide/content.json`. Then run `npm run guide:docs` in `apps/web`, which
  regenerates `docs/user-guide/SETTINGS_GUIDE.md`. Never edit that markdown by hand.
- Each fix needs tests, including the case that must not change.
- If a pull request adds `Mobile contract fixtures match the API schemas` to CI, an API schema change
  must refresh the fixtures: `apps/api/.venv/bin/python apps/mobile/tool/export_contract_fixtures.py`.

### Running tests

- `python run_full_tests.py` from the repo root is the full check, on an isolated database. See
  `docs/testing/FULL_TEST_SUITE.md`. Use this before pushing.
- **Run the whole integration suite before pushing.** A rule change broke a test in the employee module
  that a partial run missed.
- **Never run two test runs against the same database.** They collide while seeding plans, and the
  errors look like real failures. If that happens, rebuild the database and run again.
- The tests refuse the shared `hrms_dev` stack. Do not bypass that with `HRMS_TEST_ALLOW_SHARED_DEV`.
- If a local `apps/api/.env` breaks settings, export `FACE_PROVIDER_COMPARISON_ENABLED=false`.
  `tests/unit/core/test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback`
  fails locally when that `.env` sets `CORS_ALLOWED_ORIGINS`; it looks local, so confirm it in CI.
- Scripts in `apps/api/.venv/bin` may have a broken path. Use `.venv/bin/python -m pytest`, and the same
  for `ruff`, `mypy` and `alembic`.
- When editing a file with a script, read it fully before opening it for writing. Opening first empties it.

## 3. Find out where things stand

```bash
git status --short
git log --oneline -5
gh pr list --repo varunmsaji/HRMS --state open
```

To check a finding, look at the code, not this file. Examples:

- R-05: does `drop_stray_punches` exist in `calculation.py`?
- R-06: does `supersedes_punch_id` exist in `attendance/models.py`?
- R-02: does `_compute_day_breakdown` in `leave/service.py` look at other applications?

## 4. Status on 6 Nov 2026

### Merged to `main` in PR #36

| Finding | Result |
|---|---|
| F1, F2, F3, F4, F6, F8 | Fixed |
| F5 and N-3 | Half-day leave splits the shift at the midpoint, or around a fixed break spanning it |
| N-1 | Work on a day off the shift does not operate is never late or penalised, and all of it counts |
| N-4 | A daily-wage employee's worked unpaid off day pays overtime only; with none, the hour bands decide |
| N-2 | A recompute keeps a two-step overtime record at HR unless the detected minutes changed |
| R-01 | The sandwich rule covers a run of off days inside one application |
| R-03 | Late and excess-break rules give a half day on every Nth day (3rd, 6th, 9th) |
| R-10 | Overtime rounding NEAREST rounds midpoints up |

### Written but possibly not committed: R-05, R-06, R-07, R-08

On 6 Nov this was uncommitted in the owner's working tree on `test`, on one machine only. It includes
migration `20261109090000_punch_supersedes.py`. If `git status` shows these files, they are this work:
**do not revert or discard them.**

- R-05: a same-direction punch within 30 minutes of another is dropped (`STRAY_PUNCH_WINDOW_MINUTES`).
  The earliest IN and latest OUT stand. A longer gap stays INCOMPLETE.
- R-06: an approved WRONG_PUNCH replaces the nearest punch of that direction through
  `punch.supersedes_punch_id`. The old punch stays on record but no longer counts.
- R-07: year end writes the last month's accrual before applying the lapse or cap.
- R-08: `run_due_months` catches up missed months, at most `ACCRUAL_CATCH_UP_MONTHS` (3).

To finish it:

1. Open PR #37 (mobile parity) was waiting for the owner to merge. Do not push until it has merged and
   `test` is level with `main`, or the migration lands in that PR.
2. Refresh the mobile contract fixtures, because `PunchRead` gained a field.
3. Run the full tests, commit by area, push `test`, open a PR to `main`, and tell the owner it needs
   their merge because of the migration.

Last result before the final small edits: 992 of 994 integration tests passed, and the 2 failures were
then fixed and those tests re-run. The full suite has not run on the final code.

Known limits of this work, to report rather than hide:

- A dropped punch is only named in the day's snapshot (`stray_punch_ids`). HR has no review screen.
- Reviewers do not see which punch a WRONG_PUNCH will replace before approving.
- WRONG_STATUS and WFH requests still only add punches, so they can leave a day INCOMPLETE.
- R-08 only writes a log warning, and does not recover one employee whose accrual kept failing.
- Rejecting a daily-wage employee's off-day overtime leaves that day unpaid.
- A daily-wage employee working a roster week-off on a half-day weekly off can still get 0.50 LOP.
- Punches are loaded from 2 hours before the shift, so earlier ones on a day off stay orphaned.

## 5. Remaining work, in order

Details and test cases are in the audits named in section 1.

### Next

1. **R-04:** correcting an earlier day's lateness does not recompute later days of that month. The
   every-Nth rule makes this matter more, since one correction changes which days are the 3rd and 6th.
   After `is_late` or the excess-break state changes, recompute later days of that month.
2. **R-09:** adding a holiday or back-dating a shift or policy does not recompute past days, and finalize
   can lock stale results. Record what changed and block finalize with `STALE_ATTENDANCE` until
   recomputed, or recompute inside finalize.
3. **R-02:** sandwich across separate applications of the same leave type. Cancelling one side must give
   back the off days charged to the other, and no partial reversal exists yet, so design that first.
   Do this after R-04 and R-09, as only employees who split their leave benefit.

### Then

4. **R-11:** prorate probation days out of monthly accrual, from employment dates.
5. **R-12:** a leave cancelled after year end must not escape that year's lapse or cap.
6. **F7:** leave must respect roster week-offs, and HR needs a way to release leave days from the
   calendar impact screen.
7. **F11:** on-duty plus overtime.
8. **N-5:** overtime caps count detected minutes, so partial approvals and leave days use up the cap.
9. **R-16:** apply decision D-11 below.

### Smaller

R-13 (partial cancel), R-15 (server or UTC dates used as business dates), F9 (`GRADE_VIA_ASSIGNMENT`),
F10, R-14 (stored but unused policy fields), R-17 (document only), R-18 (shifts page wording), and job
health checks for leave jobs.

## 6. Decisions the owner has made

Follow these. Do not reopen them.

| ID | Decision |
|---|---|
| D-1 | All minutes on a non-operating day off are overtime; on an operating day, only beyond the shift |
| D-2, D-3 | The worked half of a half-day leave is judged on its own, from the split in section 4 |
| D-4 | On-duty on an unpaid off day is a paid day |
| D-5 | On-duty plus punched overtime pays both only when the policy requires punches |
| D-6 | Leave treats a published roster week-off as non-consuming, and roster holiday-working as consuming |
| D-7 | When a calendar change hits approved leave, HR releases it from the impact preview |
| D-9 | Remove `GRADE_VIA_ASSIGNMENT`: reject on publish and migrate existing versions to ALWAYS |
| D-10 | Half day on every Nth late or excess-break day |
| D-11 | A day can be late and earn overtime, but only minutes after the scheduled end count |
| D-12 | The sandwich rule applies across applications of the same leave type |
| D-13 | Prorate probation days out of accrual, with no retroactive credit |
| D-14 | Missed accrual catches up automatically, with an alert |
| N-2 | A recompute keeps the manager's approval unless the minutes changed |
| N-4 | Daily-wage work on an unpaid off day pays overtime only |

D-8 was built differently from the audit's suggestion: the overtime record stays as decided and the day
pays zero while the leave stands, so cancelling the leave restores it. Keep that.

The 30-minute stray-punch limit and the 3-month catch-up limit were the previous agent's choices, not the
owner's. Mention them if they matter.

## 7. Before any real company uses this

1. Recompute open periods so older days use the new rules.
2. The owner tries these in the app: work on a weekly off, Friday-to-Monday leave over a two-day weekend,
   manager-then-HR overtime approval, a wrong-punch correction, and an extra punch.
3. Run one month for a pilot company and have HR compare old and new figures.

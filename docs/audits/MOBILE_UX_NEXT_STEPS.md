# Mobile UX audit: where we paused (2026-11-15)

To pick this up again, tell Claude: "continue the mobile UX audit from MOBILE_UX_NEXT_STEPS.md".

The audit is `docs/audits/MOBILE_UX_AUDIT_2026-11-15.md`. Each phase in its section 5 has a
"Status" note listing what was done and what wasn't.

This file is local notes only. It is not committed; delete it once the work is finished.

## Where things stand

| Phase | Commit | Pull request | In `main`? |
|---|---|---|---|
| 1. Critical fixes | `6b885b1` | #59 | Yes, merged by hand |
| 2. High-impact improvements | `f3e8f73` | #59 | Yes |
| 3. Design consistency (part) | `624023d` | #59 | Yes |
| 4. UX enhancements (first pass) | `dc97795` | #60 | Yes, auto-merged after CI passed |

`test` and `main` are level at `a830369` (the merge of #60).
Mobile checks pass locally: `flutter analyze` is clean and all 1,396 tests pass.

None of Phases 1–4 has been tried on a phone yet. The checklist for each phase is in the
"Before release" sections of PRs #59 and #60.

## First thing when resuming

1. Run `git checkout test && git pull --ff-only origin test`. Make sure you are on `test` with a
   clean tree; this file is the only untracked one.
2. Start with step 1 below.

## Next steps (Phase 4, continued)

Suggested order. Everything in this list is a change to the app only:
1. **MOB-UX-029:** split the 28-field new-employee form (`employees/domain/employee_forms.dart`)
   into sections: Basics, Address, Emergency, More. The form engine (`core/forms/`) needs a
   section or heading field kind, plus pickers for state and country.
2. **MOB-UX-048:** on phones, show per-day lists instead of the employee-by-day grids
   (`workforce_roster_screen.dart`, `attendance_calendar_screen.dart`, the insights heatmap).
   Keep the grid as an option.
3. **MOB-UX-045 (rest):** replace the employee record's 13-tab strip with a sectioned Overview.
   Deactivate and "Confirm employment" are already done.
4. New features:
   - Swipe to approve on decision cards.
   - Bulk approve for overtime.
   - A "who's off" calendar while applying for leave.
5. **MOB-UX-047:** quick chips on Team attendance ("Not in yet", "Late", "Missing punch").

Needs your decision first:
- **MOB-UX-046:** a server-side status filter for `GET /employees`. This is an API change in
  `apps/api/src/hrms/modules/employee/router.py`; the mobile list currently filters only the
  pages it has loaded.
- **MOB-UX-032:** an offline banner and a cached Home. This needs a new dependency,
  `connectivity_plus`.

Still open from Phase 3:
- **MOB-UX-041:** one component kit (retire the `Dd*` widgets in `home/presentation/dashboard_design.dart` and
  `_Panel` in the dashboard). This needs design sign-off.
- **Dark mode for employees** depends on 041.

Then Phase 5, polish: MOB-UX-022, 058, 049–055 and 057.

## Also outstanding
- **Push notifications (MOB-UX-002):** needs a Firebase project, the Android and iOS config
  files, an APNs key, and a sender on the backend.
- **Biometric unlock:** deferred. It needs native changes tested on real devices.
- **Reminders:**
  - Commit only on `test`. Stage files by name.
  - Mobile checks: `export PATH=$HOME/flutter/bin:$PATH`, then `flutter analyze` and
    `flutter test` in `apps/mobile`.
  - Regenerate a changed golden with
    `flutter test test/screens_golden_test.dart --update-goldens --plain-name <name>`, look at
    the image, then delete `test/failures/`.

# Error Handling — Final Decision & Execution Gate

Date 2026-11-25. **No implementation has started. No code was changed. Nothing proceeds without your explicit go-ahead.**

## 1. Verdict

The backend already meets the central requirement (unexpected exception → generic envelope + server-side traceback + request-id correlation). Gaps: one confirmed data-as-error leak (import row errors), a non-structural guard on 5xx messages, and — the larger gap — **developer visibility into web/mobile failures and error recurrence**. No Critical/High findings.

Not safe to claim "users can never see technical errors" until Phase 1 (EH-B-01, EH-W-01) is done and the sentinel tests exist. After Phases 1–2 the claim becomes structurally enforced for the API.

## 2. Decisions needed from you (blockers)

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| D1 | Error tracking approach: **A** client beacon into existing logs / **B** self-hosted GlitchTip / **C** hosted Sentry | **A** now, revisit B later. C conflicts with the recorded "no vendor, employee data stays on VPS" decision | Phases 3–4 reporting, Phase 6 |
| D2 | User-facing reference: reuse `request_id` with display form `ERR-xxxxxxxx` | Yes (no second ID system) | Phase 2–4 |
| D3 | Clean up existing `IMPORT_ROW_FAILED` rows that contain raw exception text? | Look at how many exist first, then decide | Phase 1 follow-up |
| D4 | Mobile telemetry: permitted to send class names + code locations to your API? (store data-safety/privacy copy) | Yes, no message text, no PII | Phase 4 reporting |
| D5 | Log retention for `errors.log` (tracebacks) | Choose days; confirm what `0` means today | Phase 6 |
| D6 | Start the Prometheus overlay in production or alert from `hrms_monitor.sh` for unhandled-error rate | Yes — otherwise no one is told | Phase 6 |

## 3. Priority order

1. **Phase 1** — EH-B-01, EH-W-01, EH-B-06 (+ verify EH-B-07). Smallest, removes the only confirmed exposure.
2. **Phase 2** — `public_message` guard + `ERR-` reference.
3. **Phase 6 (endpoint + redaction)** and **Phase 3/4 reporters** — gives you the developer view.
4. **Phase 3 UI consolidation**, **Phase 4 mobile cleanup**.
5. **Phase 5** worker retry classification.
6. **Phase 7** tests and manual verification.

Phases 1 and 2 are API+web only and need no migration, so they will auto-merge after CI. Nothing in the plan touches `.github/`, `AGENTS.md`, `CLAUDE.md`, `.gitleaks.toml` or `apps/api/alembic/` (the "person must merge" list) unless you choose an option that needs a table.

## 4. Preconditions before implementation begins

- [ ] You answer D1–D6 (at least D1, D2).
- [ ] Your uncommitted attendance work (43 entries on `test`) is committed or you confirm I may work alongside it; I will stage by file name only and not touch those files (AGENTS.md).
- [ ] `git pull --ff-only origin test` clean at start of each phase.
- [ ] Baseline test run recorded: API `pytest`, web `vitest`, mobile `flutter test` — so failures can be attributed.
- [ ] One phase per PR; after merge, `git pull --ff-only origin test`.

## 5. Acceptance criteria (implementation complete when)

1. Sentinel tests (Test Matrix §"Tests that prove…") pass for backend, web, mobile.
2. A forced backend 500, a forced web render crash, an unhandled web promise rejection and a forced mobile crash each produce one searchable record keyed by the `ERR-…` shown to the user.
3. No grep hit for `str(exc)` persisted to a user-readable column, `AppError(…{exc}…)`, widget `e.toString()`, or non-API `.message` rendered in UI.
4. Every Celery task is classified retry/no-retry in a documented table.
5. Redaction covers Aadhaar-12, bank account numbers and `*_reason` free text; retention for error logs documented.
6. Manual run-through of the 20 scenarios (AGENTS.md: CI does not click through the app).

## 6. Caveats

- This audit did **not** read every file (see "What I did not inspect" in the comprehensive audit) and did not run any tests or the app.
- "Existing / GAP" in the Test Matrix is based on searching test files, not on running them.
- The brief's RQ, payment, resume and AI/LLM items do not exist in this system and are marked N/A; face providers and payroll are audited in their place.

# Error Handling — Implementation Plan

Date 2026-11-25. **Plan only. Nothing here is approved or started.** Work happens on `test`, reaches `main` by PR (AGENTS.md). Phases 1–3 touch `apps/api`, `apps/web`, none touch `.github/`, migrations or `AGENTS.md`, so CI-green PRs auto-merge. Phase 6 adds an Alembic migration only if the optional client-error table is chosen; the recommended design needs **no migration**.

Order is dependency-driven: leak fix → backend guard → shared reference → web → mobile → workers → observability → tests. Each phase can ship alone.

## Phase 1 — Stop technical exposure (small, ~½–1 day)

| | |
|---|---|
| **Findings** | EH-B-01, EH-B-06, EH-B-07 (verify), EH-W-01 |
| **Files** | `apps/api/src/hrms/modules/employee_import/service.py` (`_record_row_error`), `modules/attendance/face_comparison_admin.py` (`_discard`), `apps/web/src/lib/api/errors.ts` (`describeApiError`) |
| **Changes** | Import: replace `message = str(exc)` with fixed text + log exception once with `batch_id`/`row_number`. `_discard`: log warning. Web: non-`ApiError` → fixed generic string. Trace `embedding_service.py:133` to confirm log-only. |
| **Dependencies** | none |
| **Regression risks** | Import error screens lose the (unsafe) detail; HR users get less diagnostic text for unexpected failures — intended. Existing rows already stored keep old text: query `error_code='IMPORT_ROW_FAILED'` first and decide on a one-off cleanup (your call). |
| **Tests** | unit: inject `DBAPIError`/`KeyError` in import loop → stored text contains neither; API test on `/errors`; web: `describeApiError(new TypeError("secret"))` |
| **Done when** | tests pass; grep shows no `str(exc)` persisted to a user-readable column |

## Phase 2 — Central backend guard + reference

| | |
|---|---|
| **Findings** | EH-B-02, EH-B-03 |
| **Files** | `core/errors/base.py`, `core/errors/handlers.py`, `core/errors/envelope.py`, `core/observability/request_context.py` |
| **Changes** | `AppError.public_message`; handler uses it for status ≥ 500; server-generated id for 5xx and optional `error.reference` (`ERR-xxxxxxxx`); log record carries `reference`. |
| **Dependencies** | Phase 1 not required; Phase 3/4 consume `reference` (optional field, backward compatible) |
| **Risks** | Clients that parse `request_id` keep working. Test fixtures asserting exact 5xx messages may need updating (search `tests/` for `"An unexpected error occurred"`). |
| **Tests** | parametrised test over every `AppError` subclass with `status_code>=500`; envelope snapshot; log contains `reference` |
| **Done when** | any 5xx body is independent of the exception message by construction |

## Phase 3 — Web global handling and consistent UI

| | |
|---|---|
| **Findings** | EH-W-02, EH-W-03, EH-W-04, EH-W-05 |
| **Files** | new `components/common/api-error-state.tsx`; `lib/api/errors.ts`, `lib/api/client.ts`; new `lib/observability/report-client-error.ts`; root `app/layout.tsx` (mount listener); `route-error.tsx`; ~50 pages listed in the audit (mechanical replace of `<ErrorState message={error.message}>`) |
| **Changes** | see Target Architecture §5. Mechanical replacement should be one PR per module group to keep reviews small. Silent `.catch(() => {})` → `reportHandled()` where useful. |
| **Dependencies** | Phase 2 (`reference`) for display; Phase 6 (endpoint) for reporting — the component and listener can ship first with reporting behind a no-op flag. |
| **Risks** | Large mechanical diff; snapshot/RTL tests that look for specific error text; the permission-regex in `ErrorState` that picks the "Access restricted" title. |
| **Tests** | vitest for category→message mapping, listener registration, `describeApiError`; extend `route-error.test.tsx`; Playwright: stub a 500 and assert generic text + `ERR-…` and no raw message |
| **Done when** | grep: no page renders `error.message` outside `ApiErrorState`; unhandled rejection is reported |

## Phase 4 — Mobile standardisation

| | |
|---|---|
| **Findings** | EH-M-01, EH-M-02, EH-M-03 |
| **Files** | `lib/core/diagnostics/app_diagnostics.dart`, `lib/main.dart`, `lib/core/widgets/…` (shared `StateMessage` call sites), the 40 empty-catch sites, new "Copy diagnostics" row |
| **Changes** | persist buffer; report to `/v1/client-errors`; central `describeApiError` use; replace silent catches; route `FlutterError.onError` release path to reporting. |
| **Dependencies** | Phase 2 (reference), Phase 6 (endpoint) |
| **Risks** | Offline queue growth, battery/data; PII — payload limited to class names/frames/route; privacy copy for the Play/App Store data-safety form if telemetry is added (needs your decision). |
| **Tests** | `flutter test`: diagnostics ring/persist/flush; api_error mapping; widget test that a thrown error in a child shows the generic placeholder |
| **Done when** | no widget displays `e.toString()`/raw `.message` of non-`ApiError`; mobile crash appears in server logs |

## Phase 5 — Workers

| | |
|---|---|
| **Findings** | EH-B-04 |
| **Files** | `core/celery_app.py` (base task), attendance/notification/digest `tasks.py` (opt-in) |
| **Changes** | transient-only autoretry for idempotent tasks (list to be agreed per task), explicit no-retry for the rest; document in a task table |
| **Dependencies** | none |
| **Risks** | Retrying a non-idempotent task duplicates side effects (emails, pushes, punches) — default must be *no retry*, opt in per task. `acks_late` interplay with Redis visibility timeout. |
| **Tests** | unit with `task_always_eager`/simulated `OperationalError`: retried N times then `celery_task_failed`; non-idempotent task not retried |
| **Done when** | every task is classified (retry / no-retry) in one table in the repo |

## Phase 6 — Developer error tracking

| | |
|---|---|
| **Findings** | EH-X-01, EH-S-01/02/03 |
| **Files** | new `modules/observability/client_errors_router.py` (+ rate-limit), `core/observability/redaction.py`, `core/config/settings.py` (retention), `docker-compose.prod.yml`/monitoring overlay (decision) |
| **Changes** | `POST /v1/client-errors` (Option A), shared redaction, log viewer filter by `ERR-` prefix and `source`; redaction tweaks; retention decision; start the monitoring overlay or add a log-based alert for unhandled-error rate. If Option B chosen: GlitchTip compose + SDK wiring — separate approval. |
| **Dependencies** | endpoint needed by Phases 3–4 reporting |
| **Risks** | Unauthenticated ingestion = abuse vector → per-IP + per-user limits, size cap (4 KB), schema-strict, no echo. Log volume — sample duplicates. |
| **Tests** | endpoint rejects oversize/invalid, redacts PII, rate-limits; log record has user/company when token valid |
| **Done when** | a forced web crash and a forced mobile crash each yield a searchable `ERR-…` record |

## Phase 7 — Verification and release gate

Implement the `ERROR_HANDLING_TEST_MATRIX.md` items marked **GAP**; add CI check (grep-test) forbidding `str(exc)`/`f"{exc}"` inside `AppError(...)` constructors and `.message` of non-`ApiError` in widgets. Manual: run the app, trigger each scenario once (AGENTS.md: CI is not a substitute for trying the app). **Done when** every matrix row has an automated test or a recorded manual check.

## Total effort (rough)

P1 ½–1 d · P2 1 d · P3 3–4 d · P4 2–3 d · P5 1–2 d · P6 2 d (A) or +3–5 d (B) · P7 1–2 d. Phases 1–2 alone remove the only confirmed leak and make the guarantee structural.

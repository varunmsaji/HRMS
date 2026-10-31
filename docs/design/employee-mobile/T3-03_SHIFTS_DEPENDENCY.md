# T3-03: the `/shifts` regularization dependency

Written 2026-10-30. Nothing in the backend, the schema or the mobile code was changed for this. The question is whether a backend change is needed; the answer is **only for one option inside the correction form**, and it needs a decision.

## Exact dependency

| Link | Where |
|---|---|
| The correction form has a "Correct the assigned shift instead of punch times" toggle and a "Correct shift" choice field (`choiceKey: 'shifts'`). | `apps/mobile/lib/features/attendance/domain/request_resources.dart:46-47` |
| The form asks for its choice sources up front: `createChoiceKeys: ['shifts']`. | `request_resources.dart:123` |
| The `shifts` source is `GET /shifts`. `loadChoices` is all-or-nothing: one failing source throws. | `apps/mobile/lib/core/forms/choice_sources.dart:28,43` |
| On a throw the form shows "Could not load the options for this form." and leaves the choice empty. | `apps/mobile/lib/core/forms/spec_form_screen.dart:63` |
| `GET /shifts` requires `ORG.SHIFT.MANAGE`. | `apps/api/src/hrms/modules/organisation/router.py:648-652` |
| `ORG.SHIFT.MANAGE` is held by `COMPANY_ADMIN`. It is **not** granted to `HR_ADMIN`, `BRANCH_MANAGER`, `REPORTING_MANAGER` or `EMPLOYEE` in the seeded roles. | `organisation/service.py` role grants |
| The correction itself accepts `requested_shift_id` and needs either `requested_punches` or `requested_shift_id`. The API checks the shift belongs to the company. | `attendance/schemas.py:1715-1745`, `attendance/service.py:4585` |

## Answers to the five questions

1. **Affected screens and workflows.** Only the *create correction* form (`/app/regularizations`, "New" button), for anyone without `ORG.SHIFT.MANAGE`. That is every employee, manager and HR admin on the seeded roles. Lists, detail, cancel, approve and reject do not load `/shifts`.
2. **Does it block attendance recording?** No. Punching, face punching, today's status, the day list, the month card and Home never call `/shifts`. It blocks nothing but the correction form.
3. **Does it block the correction workflow?** Partly. The form opens, shows the error banner, and punch-time corrections (missing punch, wrong punch, WFH, on duty and so on) can still be filled in and submitted: the banner is cosmetic for them. The **"correct the shift" option cannot be completed** because the choice list is empty and `requested_shift_id` is required once the toggle is on. This is finding F-1 in the API matrix.
4. **Actual permission requirement.** Reading shifts needs `ORG.SHIFT.MANAGE`. Submitting a correction needs `ATTENDANCE.REGULARIZATION_REQUEST` (plus `_ON_BEHALF` for someone else). Nothing links the two.
5. **Existing alternative?** None. The only shift-reading routes are under `/shifts` and all require `ORG.SHIFT.MANAGE`. `GET /employees/{id}/assignments` returns the employee's own `shift_id` (an id, no name) under `EMPLOYEE.VIEW`, so the app can know *which* shift they have but cannot list the others or name any of them. Day rows carry `shift_id` and `scheduled_start/end` only. The app could show the scheduled times of the day it is correcting, but cannot offer a choice of shifts.

## What is not a backend problem

The banner and the all-or-nothing load are a mobile presentation defect. T3-03 already plans the fix: load choices per key, lazily (only when the toggle is switched on), tolerate a 403 on `shifts`, and disable just that toggle with a caption. That change touches no backend and is **not** done in this slice (T3-03 is Phase 3).

## Proposed backend change, for approval (not made)

Only needed if employees must be able to *choose a different shift* in a correction.

* Add a read-only **`GET /shifts/options`** (name suggestion) returning `[{id, name, code}]` for **active** shifts only.
* Gate it on `ATTENDANCE.REGULARIZATION_REQUEST` or `ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF` (whoever can submit the correction can name the shift), not on `ORG.SHIFT.MANAGE`.
* No shift configuration, versions or policy data in the response: id, name, code only.
* Tenant-scoped like every other read; add a test that an `EMPLOYEE` gets the list and cannot reach `/shifts` itself.

Alternatives: (a) leave "correct the shift" as an HR-only option (hide the toggle for users who cannot read `/shifts`; the API already lets HR route such a request); (b) drop the option from the employee flow. Both are mobile-only. **Recommendation:** do (a) now with the T3-03 presentation fix, and approve the endpoint only if the product wants employees to request shift changes themselves.

## Resolution (mobile only, 2026-10-30, second slice) — no backend change

Approved and implemented as the first option above. The decision on the optional `GET /shifts/options` endpoint is still open and is not needed for this.

| Requirement | How |
|---|---|
| Load fields independently | `loadChoicesTolerant` (`lib/core/forms/choice_sources.dart`): required sources fail the form as before; *optional* sources are loaded one by one and reported, never thrown. Opt-in per form through `RequestConfig.optionalChoiceKeys`; only the regularization form uses it. `loadChoices` itself is unchanged for every other form. |
| A 403 on `/shifts` must not fail the form | The form opens with no banner. Punch-time corrections are untouched (the two time fields, the request type and the date). |
| Disable only the shift option, with an explanation | `SpecForm` switches off a toggle whose only purpose is to reveal a choice field with an unavailable source: "Not available with your access. Ask HR to change this for you." (403) or "Couldn't load the options for this. Try again later." (any other failure). |
| No repeated retry of an unauthorized endpoint | A 403 is remembered per user for the session (`deniedChoiceSourcesProvider`), so reopening the form never calls `/shifts` again. A transient failure (network, 5xx) is not remembered, so it is retried once the next time the form opens. |
| Existing permission checks, no new endpoint, no weaker authorization | Unchanged. A holder of `ORG.SHIFT.MANAGE` gets the call, the list and the toggle exactly as before. |

Tests: `test/correction_form_choices_test.dart` (9 cases: 403, remembered, holder, 500, required-source failure, and the loader itself).

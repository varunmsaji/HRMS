# Onboarding workflow and customisable candidate email — implementation audit

Audit date: 2026-10-27. Scope is the working tree as inspected, including uncommitted onboarding and email changes. This document records what the code does. It does not implement a feature.

Evidence is cited as repository-relative paths. Line numbers refer to that working tree. Where a behaviour is named in product docs but has no writer in application code, it is marked `NOT IMPLEMENTED`. Where the code was not traced far enough to decide, it is marked `UNVERIFIED`.

---

## 1. Executive summary

Onboarding is a company-scoped **pre-employee case**, not a recruitment candidate record and not an offer. HR creates an `onboarding_case` with a name, personal email, optional placement (branch, department, designation) and a proposed joining date. Sending an invite mints a hashed public token, moves `DRAFT` to `INVITED`, and queues a **hardcoded** HTML/plain-text email through a transactional outbox. The recipient opens `/onboarding/{token}` with no login, fills sections, uploads documents, and submits. HR reviews sections and documents, may request changes, and activates a `VERIFIED` case into an employee, employment, and assignment. Activation also queues a welcome email and, best-effort, an account-invite email. The login account is created only when that separate invite is accepted.

There is **no HR-editable subject or body, no preview, no saved email template, no placeholder engine, and no offer-letter workflow**. `ONBOARDING.CANCEL` is granted and unused. Case statuses `EXPIRED` and `CANCELLED` are recognised by queries and never written. The invite email interpolates the candidate first name and company name into HTML **without escaping**. Delivery status visible to HR means “queued”, not “accepted by the provider” and not “delivered to the inbox”.

The smallest safe feature is an **editable onboarding invitation** that reuses `send-invite` and the existing outbox. A formal offer, salary, acceptance, or e-signature workflow is a later product, because those records do not exist.

---

## 2. Repository and working-tree baseline

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0` |
| HEAD subject | `docs(api): mobile API documentation package, audit and remediation report` |
| Staged changes | none (`git diff --cached` empty) |
| Working tree | large set of modified and untracked files from other work; not reset, stashed, committed, or discarded |

Onboarding and email behaviour described below includes these **uncommitted** files, because they are the code that would run:

- `apps/api/src/hrms/modules/onboarding/email_outbox.py`
- `apps/api/src/hrms/modules/onboarding/tasks.py`
- `apps/api/src/hrms/modules/onboarding/email_sender.py` (modified)
- `apps/api/src/hrms/modules/onboarding/service.py` (modified)
- `apps/api/src/hrms/modules/onboarding/schemas.py` (modified)
- `apps/api/src/hrms/modules/platform/models.py` (`EmailLog`, `EmailOutbox`)
- `apps/api/src/hrms/modules/platform/email_log_router.py`
- `apps/api/alembic/versions/20261021090000_email_log.py`
- `apps/api/alembic/versions/20261027090000_email_outbox.py`
- `apps/api/alembic/versions/20261027091000_onboarding_case_email_unique.py`
- `apps/api/alembic/versions/20261026090000_hr_admin_attendance_onboarding_grants.py`
- Related tests under `apps/api/tests/integration/modules/onboarding/test_b13_*.py` and `test_b12_*.py`

`docs/product/modules/04_ONBOARDING_AND_BULK_IMPORT.md` still says HR Admin receives none of the onboarding permissions. The working tree grants them. The code is the source of truth for this audit.

---

## 3. Actual onboarding architecture

There is no recruitment module. Logging maps the onboarding package to a “recruitment” category only as a label (`apps/api/src/hrms/core/observability/file_sink.py`).

```
HR web or mobile (authenticated, X-Company-Id / tenant token)
  → /v1/onboarding-cases*          require_permission(ONBOARDING.*)
  → OnboardingCaseService | TokenService | DocumentService | ReviewService | ActivationService
  → onboarding_case / onboarding_token / onboarding_document / onboarding_section_review
  → on send-invite, request-changes, activate:
       queue_email_after_commit → email_outbox row in the same DB transaction
       after commit → Celery email_outbox.deliver_message (or inline / sweep)
       → EmailSender (logging | smtp | mailtrap | hostinger)
       → email_log row (separate transaction, provider acceptance or failure)

Candidate (no JWT)
  → /v1/public/onboarding/{token}*
  → SHA-256(token) lookup on onboarding_token (no RLS)
  → set RLS company from the token’s company_id
  → read/update the case
```

Routers are mounted at `/v1` in `apps/api/src/hrms/app.py` (onboarding router and public router). Admin routes do not apply `DataScope` narrowing; isolation is `company_id` plus Postgres RLS (`apps/api/src/hrms/modules/onboarding/router.py` module docstring).

The case is the only pre-joining identity. Activation copies section JSON into employee tables and sets `onboarding_case.employee_id`. There is no separate candidate table and no conversion job.

---

## 4. Frontend route and component inventory

Navigation shows Onboarding to every signed-in web user. The sidebar item is not permission-filtered (`apps/web/src/components/layout/nav-items.ts`, comment at the `NavItem` type and the `/app/onboarding` entry). The API still returns 403, and the pages render an error state.

### 4.1 Web — HR

| Screen / component | Role (UI) | Entry | Actions | API | Data | Status change | Missing |
|---|---|---|---|---|---|---|---|
| `apps/web/src/app/app/onboarding/page.tsx` `OnboardingPage` | Button gated by `ONBOARDING.CREATE`; list requires `ONBOARDING.VIEW` on the API | Sidebar “Onboarding” | List cases, open create dialog, create | `GET /onboarding-cases?page=`, `GET /branches`, `GET /departments`, `GET /designations`, `POST /onboarding-cases` | Case fields from API; org names from reference lists (looked up only as form options, not shown as labels in the table) | Create → `DRAFT`, then route to detail | No status filter in the UI (API supports `status`). No edit, cancel, or email compose |
| `apps/web/src/components/onboarding/onboarding-case-form.tsx` | Same dialog | “Start Onboarding” | Enter first name, last name, email, mobile, designation, department, branch, joining date | None (parent posts) | Form state | None | No manager, grade, offer, or email fields. Client validation in `apps/web/src/lib/onboarding/validate-onboarding.ts` |
| `apps/web/src/app/app/onboarding/[id]/page.tsx` | `ONBOARDING.CREATE` invite, `.REVIEW` review/request-changes, `.ACTIVATE` activate; login link uses employee invite permission on the API | Row link | Send/resend invite, copy link, verify section, reject section, verify all, review documents, request changes, activate, send employee login link | `GET /onboarding-cases/{id}`, `GET .../documents`, `POST .../send-invite`, `POST .../sections/{section}/review`, `POST .../documents/{id}/review`, `POST .../request-changes`, `POST .../activate`, `POST /employees/{id}/invite` | Detail schema including section JSON and `token_status` | See lifecycle | No subject/body editor, preview, template picker, or delivery timeline. Toast treats `email_sent` as “an email was sent” (`handleSendInvite`). Backend now defines `email_sent` as queued (`schemas.py` `OnboardingInviteRead`). Web type `OnboardingInvite` in `apps/web/src/lib/onboarding/types.ts` does not declare `email_queued` or `email_delivery_status` |
| `section-review-dialog.tsx`, `document-review-dialog.tsx` | `.REVIEW` | Reject buttons on the detail page | Capture a rejection reason | `POST .../review` then refetch | Dialog state | Section/document → `REJECTED` | — |
| `onboarding-status-badge.tsx` | Display | List and detail | None | None | `status` string | None | — |

Loading, empty, 403, 404, 409 duplicate-email, and 422 field errors are implemented on the list page. Detail handles 403/404 and action failures with toasts.

### 4.2 Web — candidate portal

| Screen | Role | Entry | Actions | API | Notes |
|---|---|---|---|---|---|
| `apps/web/src/app/onboarding/[token]/page.tsx` | Anyone with the link | Email link `{web_app_base_url}/onboarding/{token}` | Step through welcome, personal, address, emergency, bank, statutory, previous employment, education, nominees, documents, review; save section; upload/delete document; submit | `GET/PATCH/POST/DELETE /public/onboarding/{token}...` | No password. Steps are a fixed list in this file (`STEPS`). Invalid/expired token surfaces as an API error. `writable: false` blocks editing (submitted, verified, activated) |
| Wizard steps under `apps/web/src/components/onboarding/wizard/` | Same | Used by the page above | Per-section forms and upload | Called by the page | `compensation-info-step.tsx` exists and is **not imported** by the public page. CTC is not collected in the web wizard |

Public validation and payloads live in `apps/web/src/lib/onboarding/public-wizard.ts`.

### 4.3 Web — not onboarding of a hire

`apps/web/src/app/app/setup/page.tsx` is company setup progress, not candidate onboarding. `apps/web/src/app/platform/emails/page.tsx` is the platform-admin email log viewer, not an HR template editor.

Employee self-service onboarding: **NOT FOUND**. Signed-in employees do not complete the candidate wizard. Post-activation documents use the employee document panel, which is a different store.

### 4.4 Mobile

Mobile mirrors the same APIs. It is not a different workflow.

| Screen | Path | APIs |
|---|---|---|
| `OnboardingCasesScreen` | `/app/onboarding` (`app_router.dart`) | `GET/POST /onboarding-cases` via `OnboardingRepository` |
| `OnboardingCaseDetailScreen` | pushed from the list (not a separate GoRoute in the snippet inspected) | get, documents, send-invite, section/document review, request-changes, activate |
| `PublicOnboardingScreen` | `/onboarding/:token`, listed in `_alwaysPublicPaths` | `PublicOnboardingRepository` unauthenticated calls |
| `setup_screen.dart`, `users_screen.dart` | Company setup and user invites | `/companies/current/setup-progress`, `/users`, `/users/invite` — not candidate onboarding |

Mobile send-invite success copy is “Invite ready.” and stores `invite_url` (`onboarding_case_detail_screen.dart`). It does not claim the provider delivered the message.

Mobile tests: `onboarding_case_detail_screen_test.dart`, `public_onboarding_screen_test.dart`, `onboarding_form_spec_test.dart`, contract fixture parsing in `contract_fixtures_test.dart`. No web page test for the HR onboarding screens was found (only compensation helpers in `apps/web/src/lib/api/errors.test.ts`).

---

## 5. Backend endpoint and service inventory

Prefix `/v1`. Auth for admin routes: tenant bearer plus permission. Public routes: token only.

| Method and path | Permission | Request / response | Writes | Email | Tests (representative) |
|---|---|---|---|---|---|
| `POST /onboarding-cases` | `ONBOARDING.CREATE` | `OnboardingCaseCreate` → `OnboardingCaseRead`. Optional `Idempotency-Key` | Insert `onboarding_case` `DRAFT`. Advisory lock + partial unique index on live email | None | `test_onboarding_case.py`, `test_b12_duplicate_onboarding.py` |
| `GET /onboarding-cases` | `ONBOARDING.VIEW` | Query `status`, `page`, `per_page` → list | Read | None | `test_onboarding_case_pagination.py` |
| `GET /onboarding-cases/{case_id}` | `ONBOARDING.VIEW` | `OnboardingCaseDetailRead` (sections, reviews, token status, decrypted PII) | Read | None | `test_onboarding_case.py` |
| `POST /onboarding-cases/{case_id}/send-invite` | `ONBOARDING.CREATE` | No body. `OnboardingInviteRead` (`case`, `invite_url`, `email_sent`, `email_queued`, `email_delivery_status`) | Revoke live tokens, insert token, `DRAFT`/`EXPIRED` → `INVITED`. Audit `ONBOARDING_INVITE_SENT` | Queues invite. Failure to enqueue is swallowed; link is still returned | `test_onboarding_invite.py`, `test_b13_email_outbox.py::test_invite_flows_store_one_message_per_issue_and_expose_explicit_status_fields` |
| `GET .../documents` | `ONBOARDING.VIEW` | Documents plus presigned download URL | Read | None | `test_onboarding_documents.py` |
| `POST .../documents/{document_id}/review` | `ONBOARDING.REVIEW` | `{status, rejection_reason?}` | Document status; may move case `SUBMITTED` → `UNDER_REVIEW` and auto-`VERIFIED` | None | `test_onboarding_documents.py` |
| `POST .../sections/{section}/review` | `ONBOARDING.REVIEW` | Same | Section review upsert; same case transitions | None | `test_onboarding_review.py` |
| `POST .../request-changes` | `ONBOARDING.REVIEW` | No body | `UNDER_REVIEW` → `CHANGES_REQUESTED` if something is `REJECTED` | Queues changes email. **No `message_key`** | `test_onboarding_review.py::test_request_changes_reopens_only_rejected_section_and_resubmit_resets_it` |
| `POST .../activate` | `ONBOARDING.ACTIVATE` | No body | Employee graph, case `ACTIVATED`, `employee_id`. Row lock | Welcome email `message_key=onboarding_activated:{case_id}`. Account invite in a savepoint | `test_onboarding_activation.py`, `test_b12_activation_integrity.py` |
| `GET /public/onboarding/{token}` | Token | `PublicOnboardingCaseRead` | First open: token `used_first_at`, `INVITED` → `IN_PROGRESS` | None | `test_onboarding_public.py` |
| `PATCH /public/onboarding/{token}/sections/{section}` | Token | Section schema, `extra=forbid` | JSONB section. Resets a `REJECTED` review to `PENDING` | None | `test_onboarding_public.py` |
| `POST /public/onboarding/{token}/submit` | Token | None | Writable status → `SUBMITTED` if required sections non-empty | None | `test_onboarding_submit.py` |
| `POST/GET/DELETE /public/onboarding/{token}/documents...` | Token | Multipart, 10 MiB, sniffed content type | `onboarding_document` + object storage | None | `test_onboarding_documents.py`, upload bound/rate-limit tests |

**Not present as routes:** cancel, update case header (email, joining date, placement), template CRUD, preview, offer accept/reject. `docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` describes `POST /onboarding-cases/{id}/cancel`. The router has no such path. `ONBOARDING.CANCEL` is listed in `docs/api/PERMISSIONS.md` with no endpoint.

Validation highlights:

- Create: `EmailStr`, names length-bounded, org FKs must belong to the company (`_assert_*_ownership`). `legal_entity_id` is derived from the branch, not sent by the client. Email stored lower-cased and stripped.
- Duplicate live case for the same company and email: `409 DUPLICATE_ACTIVE_ONBOARDING_CASE`.
- Invite allowed only for `DRAFT`, `EXPIRED`, `INVITED`, `IN_PROGRESS`, `ACTIVATED` (`ONBOARDING_CASE_INVITABLE_STATUSES`). Not for `SUBMITTED`, `UNDER_REVIEW`, `VERIFIED`, `CHANGES_REQUESTED`, `CANCELLED`.
- Public writes only while status is `INVITED`, `IN_PROGRESS`, or `CHANGES_REQUESTED`. A section already `VERIFIED` stays locked.
- Submit requires every name in `ONBOARDING_SECTION_NAMES` to be non-empty. That tuple **excludes** `compensation_info` and does not require documents (`schemas.py` lines 57–69, `submit_case`).
- Activate requires `VERIFIED` and a legal entity. Missing branch/department/designation fails inside assignment creation (`AssignmentFieldsRequiredError`), tested by `test_activate_without_placement_fields_bubbles_assignment_error`.
- Token failures are all `404` `NOT_FOUND` (`OnboardingTokenInvalidError`), including unknown, revoked, expired, and `EXPIRED`/`CANCELLED` cases.

Transactions: request-scoped session commits on success (`OnboardingActivationService` docstring). Outbox insert is in that transaction via a savepoint (`enqueue_email`). Delivery runs after commit (`defer_until_commit`). Activation’s account-invite is in its own savepoint so an invite failure does not roll back the employee.

---

## 6. Current lifecycle and status transitions

Declared statuses (`schemas.py` `ONBOARDING_CASE_STATUS_VALUES`): `DRAFT`, `INVITED`, `IN_PROGRESS`, `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `VERIFIED`, `ACTIVATED`, `EXPIRED`, `CANCELLED`.

| Stage | Trigger | Current status | Actor | API / service | Database | Email |
|---|---|---|---|---|---|---|
| 1. HR starts onboarding | Create dialog or mobile form | **Implemented.** New row `DRAFT` | HR with `ONBOARDING.CREATE` | `OnboardingCaseService.create_case` | Insert case, empty JSON sections, audit `ONBOARDING_CASE_CREATED` | None |
| 2. Candidate information collected | HR form, then candidate wizard | **Partial.** HR collects header fields only. Candidate fills sections after the link works | HR then token holder | Create, then `update_section` | Header columns, then JSONB | None at this step |
| 3. Template or checklist selected | — | **NOT IMPLEMENTED.** Sections are a fixed code list. No checklist entity | — | — | — | — |
| 4. Invitation generated | Send invite | **Implemented** for invitable statuses | HR `ONBOARDING.CREATE` | `OnboardingTokenService.issue_token` | New `onboarding_token`, previous live tokens `revoked_at` set. `DRAFT`→`INVITED` | Not yet; token exists before the queue call |
| 5. Invitation delivered | Same request queues mail | **Partial.** Queued in `email_outbox`; worker sends. API returns `QUEUED`, not delivery | Worker | `queue_email_after_commit` → `email_outbox.deliver_message` | Outbox row; later `SENT` and bodies blanked, or `FAILED` | Hardcoded `build_invite_email` |
| 6. Recipient opens link | `GET /public/onboarding/{token}` | **Implemented.** `INVITED`→`IN_PROGRESS` on first successful resolve | Token holder | `resolve_and_touch` | `used_first_at` if null; status update | None |
| 7. Recipient authenticates | — | **NOT IMPLEMENTED.** Possession of the URL is the credential. No OTP, password, or email proof | — | — | — | — |
| 8. Recipient completes forms | PATCH sections | **Implemented** while writable | Token holder | `update_section` | JSONB; PII keys encrypted | None |
| 9. Documents uploaded | POST documents | **Implemented**, optional | Token holder | `OnboardingDocumentService.upload_document` | Row + object storage, status `PENDING` | None |
| 10. HR reviews | Section/document review | **Implemented** only in `SUBMITTED` or `UNDER_REVIEW` | HR `ONBOARDING.REVIEW` | `review_section`, `review_document` | Review rows; first review `SUBMITTED`→`UNDER_REVIEW`; all verified → `VERIFIED` | None |
| 11. Corrections requested | Request changes | **Implemented** | HR `ONBOARDING.REVIEW` | `request_changes` | `CHANGES_REQUESTED`. Rejected sections become writable again; verified sections stay locked | `build_changes_requested_email`. Does **not** include a new link. Comment in `email_templates.py`: the original link remains valid |
| 12. Offer acceptance | — | **NOT IMPLEMENTED.** `policy_ack_at` / `policy_ack_ip` columns exist and have **no writer** outside the migration (`models.py` lines 101–102; grep of `policy_ack_at` hits only the model and `20260905090000_onboarding_o1.py`). Public router states `accept-policies` is not built | — | — | — | — |
| 13. Employee activated | Activate | **Implemented** from `VERIFIED` only | HR `ONBOARDING.ACTIVATE` | `activate_case` | Employee `PRE_JOINING` then employment creation sets `PROBATION` in the same request (`employee/service.py` create sets `PRE_JOINING`; `create_employment` promotes `PRE_JOINING`→`PROBATION`). Employment, assignment, optional bank/statutory/compensation/experience/education/dependents, document copy, case `ACTIVATED` | Welcome email. Separate account-invite email if `issue_for_employee` succeeds |
| 14. Joining date and module enablement | — | **Partial.** `proposed_joining_date` becomes `Employment.joining_date` and assignment `effective_from`. This audit did **not** verify that attendance, leave, or payroll refuse activity before that date. Activation does not flip feature flags | System inside activate | `EmploymentService.create_employment` | Employment row | Welcome text says HR will be in touch before the start date. That is copy, not a gate |
| 15. Remaining tasks | — | **NOT IMPLEMENTED** as tasks. After `VERIFIED`, activation does not wait for extra checklist items. Documents are optional, so a case can verify with zero documents (`_maybe_auto_verify_case`) | — | — | — | — |

`EXPIRED` and `CANCELLED` are terminal for duplicate-email checks (`ONBOARDING_CASE_TERMINAL_STATUSES`) but **no service assigns them**. A lapsed token does not change case status; the case stays `INVITED` or `IN_PROGRESS` and the next public call returns 404 until HR resends (resend is allowed for `INVITED` and `IN_PROGRESS`). `EXPIRED` is invitable if a row were ever in that status; nothing in application code puts it there.

Email is sent (queued) at three onboarding points: **send-invite**, **request-changes**, and **activate**, plus the account-invite side effect of activate.

---

## 7. Candidate-to-employee conversion

| Question | Finding |
|---|---|
| Separate candidate record? | **No.** The case *is* the pre-joining person. Fields: `candidate_first_name`, `candidate_last_name`, `personal_email`, `personal_mobile` (`models.py` `OnboardingCase`). |
| Offer received / accepted? | **NOT IMPLEMENTED.** No offer status. |
| Pre-joining person who is not an employee? | The case, until `employee_id` is set at activation. |
| Employee with incomplete onboarding? | **Not modelled.** Activation requires `VERIFIED`, then the case is `ACTIVATED`. There is no post-hire onboarding task list. |
| Active employee | After activation the employee status becomes `PROBATION` when employment is created, not `ACTIVE`. Confirmation to `ACTIVE` is a separate employee action (`employee/service.py` around the `PROBATION` check). `Employment.status` defaults to `ACTIVE` on the employment row (`employee/models.py`). |
| Start without a candidate record? | **Yes.** HR types the person into the case. No prior candidate id. |
| Start directly for an existing employee? | **No onboarding route does this.** Account invite (`POST /employees/{id}/invite`) is a different flow for someone who already has an employee row. |
| Copy into the employee? | **Yes, at activate.** `personal_info` (minus encrypted keys, re-applied via identity update), case email and mobile, address and emergency mappings, bank, statutory, compensation if the JSON is non-empty, experience, education, nominees, documents. The employee’s **name comes from `personal_info.first_name`**, not from `candidate_first_name`. Those can diverge. The invite email uses `candidate_first_name`. |
| Duplicates? | One **live** case per company per lower-cased email (advisory lock `lock_onboarding_case_email` and partial unique index `onboarding_case_company_live_email_key`). Terminal cases do not block a new case. No unique constraint was found that stops two employees sharing a personal email. Concurrent activation of one case is single-winner (`get_case_for_update`, `test_b12_activation_integrity.py`). |
| Company, department, designation, manager, joining date | Company = tenant. Department, designation, branch optional at create; branch sets `legal_entity_id`. All three are required in practice at activation because the first assignment demands them. **Reporting manager, grade, cost centre, and work-location type are not on the case** and are not passed in `AssignmentCreate` inside `activate_case` (schema supports `reporting_manager_id`; the call does not set it). Joining date is required on create and is not editable afterward. |
| User account timing | **After** onboarding, not before or during the wizard. Activation calls `AccountInviteService.issue_for_employee` best-effort. The user row is created when the invite is accepted (account-invite module). A failed auto-issue does not undo activation (`test_activation_failure_isolation.py`). HR can also press “send login link” on the web detail page after `employee_id` exists. |
| Cancelled, rejected, expired, withdrawn | Section/document `REJECTED` is implemented. Case `CANCELLED` and `EXPIRED` are **NOT IMPLEMENTED** as transitions. No withdraw. |

Inconsistencies:

- Plan and `PERMISSIONS.md` advertise cancel. Router does not.
- Product note that HR Admin lacks onboarding grants is stale; `organisation/service.py` grants all five codes at company scope, and migration `20261026090000_hr_admin_attendance_onboarding_grants.py` backfills them.
- `compensation_info` is in `SECTION_SCHEMAS`, so a crafted `PATCH .../sections/compensation_info` can store CTC, but it is not in `ONBOARDING_SECTION_NAMES`, so it is not required, not reviewed, and not shown in the web wizard. The React component `compensation-info-step.tsx` is unused by the page.
- Web copy says the email “was sent” when the API only queued it.

---

## 8. Existing email infrastructure and inventory

### 8.1 Providers and transport

`Settings.email_provider`: `logging` (default), `smtp`, `mailtrap`, `hostinger` (`settings.py`). Non-development boot refuses `logging`. SMTP and Mailtrap use `smtp_from_name` and `smtp_from_email`. Hostinger sends as the configured mailbox and sets `display_name` from `smtp_from_name`. **No reply-to field** was found. Sender identity is **process-wide**, not per company. No logo or company colour in any onboarding template; only `company.name` is interpolated.

HTML and plain text are both sent (`EmailMessage.set_content` plus `add_alternative`, and the JSON APIs set `text` and `html`).

Links use `Settings.web_app_base_url` (`{base}/onboarding/{raw_token}`). Optional `mobile_app_link_base` adds a second link via `hrms.core.links`. Production refuses an unsafe web base URL.

### 8.2 Outbox versus direct send

**Outbox (durable, after commit)** — `queue_email_after_commit` → `email_outbox`:

- Onboarding invite, changes-requested, activated.
- Account invite (`account_invite/service.py`, `message_key=account_invite:{invite.id}`).

**Direct `EmailSender.send` inside the request (not the outbox):**

- Password reset and email verification (`identity/service.py`).
- Company status notifications (`platform/service.py`).
- Attendance incomplete-day reminder and HR digest (`attendance/reminders.py`).

The outbox is the right pipe for a new onboarding invitation. It does not need a second mail stack. It is not yet the pipe for every email in the product.

### 8.3 Outbox behaviour

`email_outbox` (`platform/models.py` `EmailOutbox`, migration `20261027090000`):

- Status `PENDING` → `SENDING` (leased) → `SENT` or back to `PENDING` with backoff, or `FAILED`.
- `message_id` unique. Same key does not insert a second row.
- Invite key is `onboarding_invite:{case_id}:{sha256(raw_token)[:24]}`. Each new token is a new message. A resend is intentionally a new email; the previous token is revoked.
- Activation key is stable per case, so a replay does not queue a second welcome.
- Changes-requested passes **no** `message_key`, so each successful call is a new UUID message.
- Claim uses `FOR UPDATE SKIP LOCKED`. Attempts default 6, exponential backoff, lease 300s.
- Celery task `email_outbox.deliver_message` after commit; Beat `email_outbox.sweep` every 60 seconds.
- Bodies are **cleared** when the row becomes `SENT` or final `FAILED` (`email_outbox.py` `_record_success`, `_record_failure`). The outbox is not a long-term copy of the rendered letter.
- Provider acceptance is not inbox delivery. `email_sender.py` `_accepted` logs `email.provider.accepted` and the docstring says bounces are invisible. `email_log.status` is `ACCEPTED`, `FAILED`, or `LOGGED_ONLY`.
- At-least-once to the provider: if the worker dies after the provider accepts and before `SENT` is recorded, a retry can send again (`email_outbox.py` module docstring). Duplicate enqueue of the same `message_id` does not.

`email_log` (migration `20261021090000`) is append-only, written in its own transaction by `record_email`. Tokens in `/onboarding/`, `/reset-password/`, `/verify-email/`, and `/accept-invite/` links are masked before storage (`_mask_tokens`). Platform admins read it at `GET /v1/platform/emails` (`email_log_router.py`). Viewing a body emits `security.platform.email_viewed`. **Tenant HR has no email-log API.**

### 8.4 Inventory

| Email type | Trigger | Recipient | Template source | Provider / queue | Status tracking |
|---|---|---|---|---|---|
| Onboarding invite | `POST .../send-invite` | `case.personal_email` | `build_invite_email` in `email_templates.py` | Outbox, then configured provider | Outbox row; `email_log` per attempt; API only `QUEUED`/`NOT_QUEUED`. Audit `email_sent` means queued |
| Changes requested | `POST .../request-changes` | Same | `build_changes_requested_email` | Outbox, new id every call | Same. No new link in the body |
| Onboarding activated | `POST .../activate` | Same | `build_activated_email` | Outbox, stable key | Same. Swallowed enqueue failure does not roll back activation |
| Account invite | Auto on activate, or `POST /employees/{id}/invite` | Employee login email | `account_invite/email_templates.py` | Outbox | Account-invite record plus outbox |
| Email verification | Company registration / resend | New admin | `identity/email_templates.py` | Direct send | `email_log` only if send is attempted |
| Password reset | `POST /auth/password/forgot` | User | Same | Direct send | Same. Response is always success (anti-enumeration) |
| Company approved/rejected/suspended/reactivated/terminated | Platform status change | Company admin | `platform/email_templates.py` (HTML escaped) | Direct send | `email_log` |
| Attendance incomplete reminder | Reminder job | Employee login email | `attendance/email_templates.py` (HTML escaped) | Direct send | Audit row on the period, not per message in the outbox |
| Attendance HR digest | Same job | Users with `ATTENDANCE.LOCK` | Same | Direct send | Same |

No database email-template table. No template editor. Templates are Python functions. They are not tenant-scoped; company name is a parameter.

The existing infrastructure **can** carry an editable invitation: build the subject and bodies in the onboarding service (as it already does), then call `queue_email_after_commit`. That does not require a new provider.

---

## 9. Customisable email capability assessment

| Requirement | Status | Evidence |
|---|---|---|
| Edit subject | **NOT IMPLEMENTED** | `build_invite_email` fixes the subject. `send_invite` takes no body |
| Edit body | **NOT IMPLEMENTED** | Same |
| Formatted content | **PARTIAL** | Emails are HTML, but the HTML is authored in code. No editor |
| Preview before send | **NOT IMPLEMENTED** | No preview route. HR sees the raw URL after send, not the message |
| View final rendered email | **NOT IMPLEMENTED** for HR | Platform console can open `email_log` bodies. Outbox bodies are wiped after send |
| Restore a default | **NOT IMPLEMENTED** | The code function *is* the only template |
| Save without sending | **NOT IMPLEMENTED** | — |
| Reuse a template later | **NOT IMPLEMENTED** as data | Every invite uses the same function |
| Select a company-approved template | **NOT IMPLEMENTED** | — |

---

## 10. Placeholder and data-source inventory

There is no `{{placeholder}}` substitution. The invite function receives three values and string-interpolates them. Missing values are not a template concern today: create requires first name, email, and joining date; company name comes from the company profile.

| Proposed field | Actual source | Nullable | Used in invite email today | If missing |
|---|---|---|---|---|
| Candidate full name | `candidate_first_name` required; `candidate_last_name` optional. Wizard later stores `personal_info.first_name` / `last_name`, which activation uses for the employee | Last name nullable. Wizard name can differ from case name | First name only | Create rejects an empty first name |
| Company name | `OrganisationService.get_company_profile(company_id).name` | Required on the company | Yes, unescaped in HTML | Profile lookup failure would fail the invite request before queue (`send_invite` does not catch that) |
| Company branding | **NOT FOUND** on the company model (no logo field in `organisation/models.py`) | — | Name only | — |
| Job title | `designation_id` UUID, optional. Display name would require a designation read | Nullable | **Not in the email** | Activation fails later if designation is missing when an assignment is required |
| Department | `department_id` optional UUID | Nullable | Not in the email | Same |
| Designation | Same as job title in this model | Nullable | Not in the email | Same |
| Proposed joining date | `proposed_joining_date` required `date` | No | **Not in the email** | Create 422 |
| Work location | `branch_id` optional. Assignment also has `work_location_type`, not set by onboarding | Nullable | Not in the email | Branch absence blocks activation via assignment rules |
| Reporting manager | **NOT ON THE CASE.** `AssignmentCreate.reporting_manager_id` exists and is not passed | — | Not available | Would render blank unless HR supplies it later on the employee |
| HR contact | **NOT FOUND** as a case or company field used by these templates | — | Not in the email | — |
| Portal URL | Built at send time from the raw token. Raw token is not stored | — | Yes | If enqueue fails, HR still receives `invite_url` in the API response to copy |
| Offer / salary | `compensation_info.annual_ctc_minor` and `currency` only if something wrote that JSON. Not in the wizard’s required sections | Effectively empty in the normal UI | **Must not be assumed present.** Not in the invite | Activation skips compensation when the dict is empty |

A future placeholder engine must resolve on the server from an allowlist and refuse to send if a required token is still literal text. Client-supplied HTML must not be trusted to “fill in” `{{candidate_name}}` by itself.

---

## 11. Database and schema impact

Existing tables that the feature can use:

| Table | Role for an editable invite |
|---|---|
| `onboarding_case` | Recipient, names, placement ids, joining date, status. No subject/body columns |
| `onboarding_token` | Link credential. Unchanged if the email is still “here is your link” |
| `email_outbox` | Queue. Good for send. Poor as the audit copy because bodies are deleted on `SENT`/`FAILED` |
| `email_log` | Per-attempt copy with masked links. Platform-admin only. Not tenant-scoped by RLS (model docstring: platform tables are tenant-free). `company_id` is informational |
| `audit_log` | `ONBOARDING_INVITE_SENT` stores case fields and `email_sent`, not the body |

**No email-template table. No offer table.**

Recommended schema (not implemented):

1. **Phase 1 can avoid a template table.** Accept subject and body on the send (or on a draft stored on the case). Render on the server. Persist the exact rendered subject, text, and HTML on a **tenant-scoped** `onboarding_message` (or similar) row that is not blanked: case id, company id, actor user id, template version or “ad hoc”, placeholder snapshot (non-secret fields only), outbox `message_id`, timestamps. Link status by reading the outbox row for HR, or copy `SENT`/`FAILED` onto the message when the worker finishes. Do not put PAN, Aadhaar, bank account, or CTC in that snapshot unless a later offer phase explicitly requires it and access is restricted.
2. **Phase 2:** `email_template` with `company_id`, name, subject, body, status (`DRAFT`/`ACTIVE`/`RETIRED`), version integer. Sent messages store `template_id` + version so later edits do not rewrite history. Retire rather than hard-delete, or block delete while referenced. Concurrent edits: optimistic `version` column, same pattern as `onboarding_case.version` (the case version exists; this audit did not find it used as a compare-and-set on invite).
3. **Do not store offer compensation in the invitation body or in `email_log`** for phase 1. `email_log.html_body` is visible to every platform admin.

Tenant ownership: case, documents, and section reviews already have `company_id` and RLS (`20260905090000_onboarding_o1.py`). `onboarding_token` RLS was **removed** (`20260906090000_onboarding_o2.py`) because lookup happens before a tenant GUC exists; the following case read is RLS-scoped. A new template table must use RLS. `email_outbox.company_id` is nullable and the outbox is not described as RLS-protected in the model docstring (platform models file says those tables are tenant-free; `EmailOutbox` lives in that module and has an optional `company_id`). HR must not query `email_outbox` directly without a tenant filter. Prefer a tenant-owned message table.

---

## 12. Security and tenant isolation

### 12.1 Permissions (backend enforced)

| Action | Permission | Enforced on API | UI hide |
|---|---|---|---|
| Start case, send/resend invite | `ONBOARDING.CREATE` | Yes | Button hidden; API 403 still applies |
| List/detail/documents | `ONBOARDING.VIEW` | Yes | Page shows 403 |
| Review, request changes | `ONBOARDING.REVIEW` | Yes | Buttons hidden |
| Activate | `ONBOARDING.ACTIVATE` | Yes | Button hidden |
| Cancel | `ONBOARDING.CANCEL` | **No route** | No button |
| Edit templates, preview | — | **NOT IMPLEMENTED** | — |
| View email history | Platform admin session, not an onboarding permission | `get_current_platform_admin` | HR UI has no log |

Granted to `COMPANY_ADMIN` and `HR_ADMIN` at `DataScopeLevel.COMPANY` (`organisation/service.py` around the HR admin onboarding comment). UI hiding is not the control.

### 12.2 Tenant isolation

- Case, document, and section-review queries include `company_id` and RLS.
- Create checks designation, department, and branch belong to the company.
- Public routes take `company_id` and `case_id` only from the token row (`public_router.py` docstring, `OnboardingTokenContext`).
- Cross-tenant tests: `test_onboarding_case_cross_tenant_isolation`, `test_review_section_cross_tenant_isolation`, `test_admin_documents_cross_tenant_isolation`, `test_activate_cross_tenant_isolation`, `test_public_tokens_do_not_cross_tenant_boundaries`, `test_account_invite_onboarding_token_isolation.py`.
- Token table has no RLS by design. Security depends on unguessable hashes and the subsequent RLS case read. A forged `company_id` cannot be supplied by the client on these routes.

`email_log` and `email_outbox` are not tenant-authorized reads for HR. A future HR “sent mail” screen must not reuse the platform router.

### 12.3 Invitation security

| Control | Actual behaviour |
|---|---|
| Entropy | `secrets.token_urlsafe(32)` (`issue_token`). SHA-256 hex stored. Unique on `token_hash` |
| Expiry | `expires_at = now + 7 days`. `ttl_days` parameter exists; `send_invite` does not pass an override, so it is always 7. Plan text said HR-configurable; **not exposed** |
| Single use | **No.** `used_first_at` records the first open. The token keeps working until expiry or revoke |
| Revocation | Resend sets `revoked_at` on every non-revoked token for the case |
| Replay of the link | Allowed until revoke/expiry. Replay of the HTTP send creates a **new** token and a new outbox message |
| Logs | `email_log` masks the path token. Structured failure logs are documented to omit the recipient. Dev `logging` provider writes the body to stderr, and production refuses that provider |
| Binding | Token binds to one case and that case’s company. It does not re-check that the person opening it controls `personal_email` |
| Resend | Invalidates previous tokens. Old links 404 |
| Cross-company | Hash lookup then RLS case fetch. Terminal `EXPIRED`/`CANCELLED` rejected. `ACTIVATED` still resolves **read-only** |

### 12.4 Email content

| Issue | Severity | Evidence | Scenario | Mitigation (for a later change) |
|---|---|---|---|---|
| Onboarding HTML is not escaped | Medium | `email_templates.py` interpolates `candidate_first_name`, `company_name`, and rejection `reason` into HTML. Attendance and platform templates call `html.escape`. Onboarding, identity, and account-invite templates do not | A company name or candidate first name containing `<a href="https://evil">` or a rejection reason with HTML is rendered as markup in mail clients that honour HTML. Script execution in mail clients is uncommon; link and layout injection is realistic. Values are entered by HR or company admin, so this is insider or compromised-admin content, not anonymous candidate HTML on the invite itself. Rejection reasons are HR-authored | Escape every interpolated value. If HR later edits HTML, sanitize to an allowlist and treat placeholders as data, not HTML |
| Header injection via subject | Low | Subject is `Complete your onboarding at {company_name}` passed to `EmailMessage["Subject"]` | A company name containing CR/LF could attempt header injection if the library does not reject it. `EmailMessage` typically rejects newlines in headers. **UNVERIFIED** against the installed `email` library behaviour; do not rely on it without a test | Strip CR/LF from subject and display name before send |
| Wrong recipient | Low for the current flow | Recipient is the case email, which cannot be updated after create (no PATCH) | Resend always uses the original address. A typo requires a new case after the old one is terminal, and it cannot be marked terminal through the API | Editable email needs an explicit confirmed recipient and should not silently follow a changed address without a new send |
| Duplicate send | See edge cases | Outbox dedupes by `message_id` only | Two concurrent `send-invite` calls mint two tokens and two messages. The first link is revoked if the second commit wins the revoke, but both messages can be delivered | Lock the case row around issue+enqueue, same idea as activation’s `FOR UPDATE` |
| Secrets in the mailed HTML | By design for the link | The raw token is the link | Anyone with mailbox access can open the wizard and read/write PII while the case is writable, including bank account, PAN, and Aadhaar as returned decrypted on the public read | Keep tokens single-purpose; do not also put compensation in the same mail. Consider shorter TTL as a product choice |
| Platform admins can read masked bodies | Accepted design | `email_log_router.py` | Invitation content and PII in the body are visible to platform operators. Tokens are masked, so the log should not be a usable link | Keep offer/CTC out of phase-1 bodies |

No live exploit was attempted.

---

## 13. Failure handling and edge cases

| Case | Current behaviour | Classification |
|---|---|---|
| No email address | Create requires `EmailStr`. Cannot happen for a case | Handled |
| Email changes later | No update API. Invite always uses the stored address | Gap if the address was wrong. Not a silent update bug |
| Person already has an employee | Onboarding does not look up employees. Activation creates another employee. Account invite may then skip if that new employee’s invite rules refuse (`AppError` logged as `account_invite.auto_issue_skipped`) | Risk: duplicate people. Not prevented by the case email index |
| Invitation expired | Public routes 404. Case status unchanged. HR can resend while status is `INVITED` or `IN_PROGRESS` | Implemented for the token, not for case status `EXPIRED` |
| Resend | New token, old tokens revoked, new outbox row because the key includes the token hash. Status stays `INVITED` or `IN_PROGRESS` | Implemented. Two emails can exist; only the latest link works |
| Template edited while sending | No template record. Not applicable | Design question for phase 2: snapshot version on the message |
| Required placeholder missing | No placeholders | Design requirement for the new feature |
| Provider down | Outbox retries transient failures with backoff, then `FAILED`. Permanent SMTP/HTTP failures fail immediately (`test_b13_email_outbox.py`) | Implemented for outbox mail. API still returned `QUEUED` |
| Provider accepts then app times out | Documented at-least-once duplicate (`email_outbox.py` docstring). Test `test_worker_killed_before_and_after_the_provider_accepted` | Known limit, tested as behaviour |
| DB commit succeeds, delivery fails | Message remains `PENDING`/`FAILED`. Case is already `INVITED`. HR can copy `invite_url` from the response only on that request; it is not stored | Implemented separation. Lost HTTP response means HR cannot recover the raw URL except by resend, which revokes the previous token |
| Worker retries same message | Same `message_id`, claim is exclusive. Retry of a failed attempt resends the **same** body. That can duplicate at the provider if the earlier attempt actually succeeded | Known at-least-once risk |
| Cancel after send | **Cannot cancel.** Token stays valid until expiry or a resend | Confirmed gap (`ONBOARDING.CANCEL` unused). QA register OBS-HRA-03 |
| Joining date changes after send | **Cannot change.** Email did not include the date anyway | Gap |
| Activate with incomplete tasks | Activation requires `VERIFIED`. Documents are not mandatory, so “incomplete” optional documents do not block. There is no task list | By design of `_maybe_auto_verify_case` |
| Two HR users create for the same email | Advisory lock + unique index. One 201, one 409. Test `test_def_b11_03_concurrent_creates_for_one_email_make_exactly_one_case` | Fixed in this working tree (DEF-B11-03) |
| Two HR users send invite together | No row lock in `send_invite` | Potential duplicate emails and a revoked first link. **Not a confirmed test failure**; no test asserting a single winner for send-invite |
| Client retries create after timeout | Optional idempotency key on create | Safe if the client sends the same key |
| Client retries send-invite | **No idempotency key** on send-invite. Each call is a new token and a new email | Duplicate invitations |
| Client retries request-changes after success | Second call sees `CHANGES_REQUESTED` and returns 409, so it does not send again | Safe after commit |
| Client retries request-changes concurrently | No row lock and no `message_key` | Potential double email. Risk, not a cited failing test |
| Client retries activate | Row lock; second sees `ACTIVATED` and 409. Welcome `message_key` is stable | Tested (`test_def_b11_02_eight_concurrent_activations_have_exactly_one_winner`) |
| Changes requested while the link is the only way back | Email tells the candidate to use the earlier link. `CHANGES_REQUESTED` is **not** invitable, so HR cannot send a fresh link without a code change | Operational trap if the candidate lost the original mail |

---

## 14. Test coverage and gaps

| Requirement | Test | Gap |
|---|---|---|
| Happy-path create | `test_create_onboarding_case_success` | — |
| Existing vs new person | `test_create_onboarding_case_duplicate_active_blocked`, `test_retry_after_the_blocking_case_is_terminal_is_allowed` | No test that an existing **employee** blocks a case |
| Invite create and open | `test_send_invite_success_transitions_draft_to_invited`, `test_public_get_case_transitions_invited_to_in_progress` | — |
| Resend revokes | `test_resend_invite_revokes_previous_token` | — |
| Template edit / preview | **NO TEST FOUND** | Feature absent |
| Placeholder substitution | **NO TEST FOUND** | Feature absent |
| Tenant isolation | Cross-tenant tests named in section 12 | — |
| Permission denial | `test_create_onboarding_case_without_permission_rejected`, `test_send_invite_without_permission_rejected`, `test_review_section_without_permission_rejected`, `test_activate_without_permission_rejected` | No test that `ONBOARDING.CANCEL` has no route (covered as a QA harness note in `docs/testing/QA_B11_PLAN.md`, not re-run here) |
| Invalid/expired token | `test_get_public_case_unknown_token_returns_404`, `test_expired_token_returns_404` | — |
| Provider failure | `test_b13_email_outbox.py` permanent and transient cases; `test_email_failure_classification.py` | No test of a real SMTP server (by policy of this audit, none was sent) |
| Retry / duplicate delivery | `test_duplicate_task_delivery_and_duplicate_enqueue_send_once`, `test_concurrent_workers_deliver_every_message_exactly_once` | Duplicate **logical** invites from two send-invite calls are not the same as duplicate outbox delivery |
| Concurrent create | `test_def_b11_03_concurrent_creates_for_one_email_make_exactly_one_case` | — |
| Concurrent activate | `test_def_b11_02_eight_concurrent_activations_have_exactly_one_winner` | — |
| Concurrent send-invite | **NO TEST FOUND** | — |
| Cancel | **NO TEST FOUND** for a successful cancel | Absence is the behaviour |
| Resend | `test_resend_invite_revokes_previous_token` | — |
| Activation graph | `test_activate_success_creates_full_employee_graph` and the experience/education/nominee/document tests | — |
| Audit | Create/submit/invite/activate record audit actions in services. Dedicated assertion coverage was not line-checked in every test | Partial |
| Sensitive data in logs | `test_activation_email_failure_is_logged_without_the_address`, `test_smtp_send_failure_does_not_log_the_email_body`, `test_dev_logging_sender_keeps_content_out_of_the_structured_log` | — |
| HTML sanitisation of onboarding templates | **NO TEST FOUND** | Attendance templates escape; onboarding templates do not, and nothing asserts that |
| Web HR UI | **NO TEST FOUND** for `app/app/onboarding/page.tsx` | Mobile widget tests exist |
| `email_sent` means queued | `test_invite_flows_store_one_message_per_issue_and_expose_explicit_status_fields` | Web toast not covered |

This audit did not run the suite.

---

## 15. Confirmed defects versus potential risks

### Confirmed in code (not all are regressions of this week’s diff)

1. **`EXPIRED` and `CANCELLED` are unreachable**, while `ONBOARDING.CANCEL` is granted. Documented earlier as OBS-HRA-03. Still true: no `set_status(..., "CANCELLED"|"EXPIRED")` in the onboarding package.
2. **Onboarding HTML templates do not escape interpolated text**, unlike attendance and platform templates.
3. **Web UI reports “An email was sent”** when `email_sent` is only “queued” (`[id]/page.tsx` `handleSendInvite` versus `OnboardingInviteRead`).
4. **Changes-requested email cannot be reissued with a fresh link**, because that status is not invitable, and the email omits the URL on purpose (the raw token is not stored).
5. **Invite TTL is not HR-configurable** despite the comment on `DEFAULT_TOKEN_TTL_DAYS`.
6. **Case header is immutable** after create (email, date, placement).
7. **Compensation section is API-writable and UI-hidden**, and is outside the review checklist.
8. **`policy_ack_*` is unused.**

### Potential risks (not demonstrated as a failing test in this audit)

1. Concurrent `send-invite` can emit two emails and revoke one of the links.
2. Concurrent `request-changes` can emit two emails.
3. Provider at-least-once can duplicate a message the provider already accepted.
4. A second employee can be created for an email that already belongs to an employee.
5. Public link is multi-use and unauthenticated for up to 7 days, with decrypted PII on the public read.
6. Newline in company name in the subject (header injection) is unverified against the mail library.

### Fixed in this working tree relative to older QA notes (do not re-open as current defects)

- Parallel activation creating many employees: row lock, `test_b12_activation_integrity.py`.
- Parallel create of many cases for one email, then `MultipleResultsFound`: advisory lock, unique index, `test_b12_duplicate_onboarding.py`.
- Email after rollback: outbox row shares the business transaction, `test_rollback_and_savepoint_rollback_leave_nothing_deliverable`.

---

## 16. Recommended target workflow

Map of the requested HR journey onto the current system:

| Step | Today | Change |
|---|---|---|
| 1. Open or create the case | Exists | Keep |
| 2. Review candidate and joining details | Detail page shows them. They cannot be edited | Phase 1: show them in the compose screen. Editing the case header is optional and should be a separate, permissioned update if product wants corrections |
| 3. Choose a company-approved template | Missing | Phase 1: one built-in default. Phase 2: saved templates |
| 4. Edit subject and body | Missing | New |
| 5. Insert dynamic fields | Missing | Server allowlist, inserted as tokens the server replaces |
| 6. Preview rendered message | Missing | New read-only render, no token minted yet **or** preview with a fake link |
| 7. Validate recipient and required fields | Email is already required | Add unresolved-placeholder and empty-recipient checks |
| 8. Explicit confirm | Send button exists but does not show the body | Confirm on the preview |
| 9. Queue via existing infrastructure | `queue_email_after_commit` | Keep. New `message_key` must change when the content or token changes, and must not change on a pure retry of the same send |
| 10. Show send status and times | Only case status and token expiry | Show outbox status for that message |
| 11. Retry failure without a duplicate | Resend always mints a new token, which is correct for a new link, and always sends again | Retry of a `FAILED` outbox row should resend the **same** body and the **same** still-valid token. A new link should be a different action (“revoke and resend”) |
| 12. Record who sent it and the exact content | Audit records the actor and `email_sent`, not the body. Outbox body is deleted after send | New tenant-scoped snapshot |

Phase 1 should not be a visual email designer. A textarea (or a small rich-text control whose HTML is sanitized server-side) plus an insert-field menu is enough.

---

## 17. Proposed phases

### Phase 1 — Core editable onboarding invitation

- Default template remains the current invite copy, now with explicit placeholders for name, company, joining date, and portal URL.
- HR can edit subject and body on that send, preview, and confirm.
- Server renders, rejects leftover `{{...}}`, escapes data in HTML.
- Queue through `queue_email_after_commit`.
- Persist a tenant-owned snapshot and surface queued / sent / failed to HR.
- Do not include salary.
- Keep the public wizard unchanged.

### Phase 2 — Template management and versioning

- Company-scoped templates, version, retire, optimistic concurrency.
- Sent messages point at the version used.
- Still not a drag-and-drop designer.

### Phase 3 — Offer letter and acceptance, only if product asks

New requirements, not present today: compensation authority, offer document, expiry, accept/reject, evidence, and a decision that the email is not itself the contract. `compensation_info` is not an offer.

### Phase 4 — Automation

Reminders before token expiry, case transition to a real `EXPIRED`, cancel that revokes tokens, joining-date edits, manager on the case. Each is a product decision. Do not bundle them into phase 1.

---

## 18. Files likely to change in a later implementation

Backend:

- `apps/api/src/hrms/modules/onboarding/email_templates.py` — default copy and a render function.
- `apps/api/src/hrms/modules/onboarding/service.py` — `send_invite`, preview, status.
- `apps/api/src/hrms/modules/onboarding/schemas.py` — request/response fields.
- `apps/api/src/hrms/modules/onboarding/router.py` — preview and possibly message status.
- `apps/api/src/hrms/modules/onboarding/models.py` and a new Alembic revision — snapshot and optional template tables.
- `apps/api/src/hrms/modules/onboarding/repository.py`
- `apps/api/src/hrms/modules/onboarding/email_outbox.py` — only if HR status must be copied back when the worker finishes. Avoid blanking the tenant snapshot.
- `apps/api/src/hrms/modules/onboarding/permissions.py` — only if preview/send should be a distinct code. Today send is `ONBOARDING.CREATE`.

Web:

- `apps/web/src/app/app/onboarding/[id]/page.tsx` — compose, preview, honest status.
- `apps/web/src/lib/onboarding/types.ts`
- New compose component under `apps/web/src/components/onboarding/`.

Mobile, if parity is required:

- `apps/mobile/lib/features/onboarding/presentation/onboarding_case_detail_screen.dart`
- `apps/mobile/lib/features/onboarding/data/onboarding_repository.dart`

Tests beside the existing onboarding integration and email outbox tests. No change to identity or attendance senders is required for phase 1.

---

## 19. Proposed API changes

Not implemented. Sketch only.

- `POST /v1/onboarding-cases/{case_id}/invite-preview`  
  Permission: `ONBOARDING.CREATE`.  
  Body: `{ "subject": "...", "body": "..." }` using an agreed placeholder syntax.  
  Response: rendered subject, text, and HTML, with a **non-functional** link sample or a clearly marked placeholder for the URL. Does not mint a token.

- `POST /v1/onboarding-cases/{case_id}/send-invite`  
  Extend the empty body to optional `{ "subject", "body", "template_id"? }`. Omit means today’s default. Response keeps `invite_url` and adds `message_id` plus an honest `email_delivery_status`. Stop overloading `email_sent` in new UI.

- `GET /v1/onboarding-cases/{case_id}/messages`  
  Permission: `ONBOARDING.VIEW`. Tenant-scoped snapshots and outbox status. Not `GET /platform/emails`.

Idempotency: accept `Idempotency-Key` on send, or define the `message_key` as the idempotency key of that confirmed payload so a timeout retry does not create a second token. A deliberate resend needs a different key and should revoke the previous token only when HR chooses “replace link”.

---

## 20. Proposed database changes

Not implemented.

Phase 1 minimum:

- `onboarding_outbound_message` (name flexible): `id`, `company_id`, `onboarding_case_id`, `kind`, `message_id` (FK-by-value to `email_outbox.message_id`), `subject`, `text_body`, `html_body`, `actor_user_id`, `created_at`. RLS like `onboarding_case`. No CTC columns.

Phase 2:

- `onboarding_email_template`: `company_id`, `name`, `subject`, `body`, `status`, `version`, `updated_by`, timestamps. Partial unique index on one active name per company.

Do not add offer tables in phase 1.

---

## 21. Acceptance criteria for a future phase 1

1. HR with `ONBOARDING.CREATE` can preview a rendered invite without creating a token or an outbox row.
2. A placeholder that has no value blocks send. The recipient never sees raw `{{...}}`.
3. HTML rendering escapes case and company data. A name containing `<` does not become a tag.
4. Confirming send uses the existing outbox. The case still moves `DRAFT`→`INVITED` only when a token is actually issued.
5. The API does not tell HR the message was delivered to the inbox. It distinguishes queued, provider-accepted (if the worker has written that back), and failed.
6. Retry of a failed delivery does not mint a second live token unless HR explicitly replaces the link.
7. A second concurrent send for the same confirmation does not create two live tokens.
8. The stored snapshot is visible to `ONBOARDING.VIEW` in that company and not to another company.
9. The snapshot and the email omit compensation and government identifiers.
10. Existing public wizard, review, and activation behaviour stay as they are.
11. Tests cover preview, missing placeholder, HTML escape, tenant isolation, permission denial, failed provider, and idempotent retry. Existing invite and outbox tests still pass.

---

## 22. Risks, unresolved questions, and product decisions

1. Is phase 1 an invitation only, or must the first release look like an offer letter? This audit recommends invitation only.
2. May the email include designation, department, branch name, and joining date? Those ids exist; names need extra reads. Manager does not exist on the case.
3. Should HR edit the case email and joining date before send? Today they cannot.
4. Should a resend revoke the old link? Today it always does. A delivery retry should not.
5. Is a 7-day multi-use link acceptable once the email is a richer letter?
6. Who may edit company templates later: every `ONBOARDING.CREATE` holder, or a narrower permission?
7. Should HR see historical message bodies, given they can contain a live link? The snapshot should store a masked link the way `email_log` does, plus the fact of send, unless product insists on the exact URL.
8. Should `ONBOARDING.CANCEL` be implemented so a sent invite can be killed? Separate from the email feature, but it is the main operational hole once mail goes out.
9. Should `CHANGES_REQUESTED` be allowed to send a new link? Today the candidate is stranded if they lose the first mail.
10. Web versus mobile: does phase 1 ship on web only?
11. Direct-send emails (password reset, verification, attendance, platform) stay outside the outbox. Unifying them is out of scope unless product wants one delivery console for everything.
12. `docs/product/modules/04_ONBOARDING_AND_BULK_IMPORT.md` disagrees with HR Admin grants. Update that doc when behaviour is next changed, so the next audit is not split.

---

## 23. Safety confirmation

This audit added only this report:

`docs/audits/onboarding_email_implementation_audit.md`

No application code, migration, test, configuration, environment file, or generated application artefact was modified. No migration was executed. No database row was inserted, updated, or deleted. No email was sent and no email provider was called. No candidate, employee, onboarding case, or template was created. Git history was not changed. Existing uncommitted work was left in place.

`AUDIT COMPLETE — NO APPLICATION CODE, DATABASE RECORDS, MIGRATIONS, OR EMAILS MODIFIED`

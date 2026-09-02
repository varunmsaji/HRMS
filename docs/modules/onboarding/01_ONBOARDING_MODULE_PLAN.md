# Employee Onboarding — Module Plan

**Status:** Proposed — not yet implemented. Nothing in this document exists in code today.
**Relationship to prior work:** builds on the already-delivered Employee vertical
(`docs/modules/employee/01`–`40`) — `Employee`, `Employment`, `EmployeeAssignment`,
`EmployeeCompensation`, `EmployeeStatutory`, `EmployeeBank` models/services/routers all exist
and are RBAC/data-scope enforced. This plan does **not** duplicate them; it adds a front door
that ends by calling them.
**Relationship to product docs:** `docs/product/17_SRS_Phase1_Core_Modules.md` §9 (FR-ONB-001–010)
specifies the *full* onboarding vision (candidate pre-boarding portal, task-pack automation,
auto-provisioning, buddy program) and `docs/product/VERSION_1_ROADMAP.md` defers that in full to
V2, bundled with Recruitment. This plan is deliberately a **narrower slice**: HR/Admin manually
starts onboarding for a known new hire (no ATS/candidate object), the hire self-fills their own
data behind a secure link, HR verifies and activates. No task packs, no auto-provisioning, no
buddy workflow, no day-1 induction content — see §14 for what is explicitly out.

---

## 1. Goal

> HR/Admin starts onboarding for a new hire → the new hire receives a secure link → they fill in
> their own personal, address, bank, and statutory details and upload identity/education
> documents → HR/Admin reviews and verifies each piece → on approval, the system creates the
> real `Employee` + `Employment` + `Assignment` (+ `Compensation`/`Statutory`/`Bank` if collected)
> records automatically.

This turns the *already-built* "HR fills six panels by hand" workflow
(`apps/web/src/app/app/employees/[id]/page.tsx`) into "the new hire fills their own six panels
through a public wizard, HR just reviews and clicks Activate."

## 2. Why this design: reuse, don't duplicate

The employee module already has validated `*Create` Pydantic schemas and service methods for
every piece of data a new hire needs to provide: `EmployeeCreate`, `EmploymentCreate`,
`AssignmentCreate`, `CompensationCreate`, `StatutoryCreate`, `BankCreate`
(`apps/api/src/hrms/modules/employee/schemas.py`), backed by `EmployeeService`,
`EmploymentService`, `EmployeeAssignmentService`, `EmployeeCompensationService`,
`EmployeeStatutoryService`, `EmployeeBankService` (`.../employee/service.py`), all of which
already enforce field-level validation and DataScope rules.

**Decision:** the onboarding module does not re-model this data. It stages the candidate's input
in a single new `onboarding_case` row (JSONB sections) plus a `onboarding_document` table for
uploads, and the **Activate** step (§8.6) calls the existing employee-module services directly,
in one DB transaction, to create the real rows. Onboarding becomes a thin staging + verification
layer in front of employee creation, not a parallel data model. This also means every validation
rule already written for "HR adds an employee" is inherited for free — no rule gets written twice.

## 3. End-to-end flow

```
HR/Admin                         Candidate (new hire)                  System
--------                         --------------------                  ------
Start Onboarding
 (name, personal email/phone,
  designation, department,
  branch, joining date)
     │
     ▼
Case created (DRAFT) ──────────────────────────────────────────►  Token minted, hashed & stored
     │                                                              Invite email sent
     ▼
                                  Opens link (no login)  ◄─────────
                                       │
                                  Fills Personal Info
                                  Fills Address / Emergency Contact
                                  Fills Bank Details
                                  Fills Statutory Details
                                  Uploads Documents
                                  (autosave each section)
                                       │
                                  Reviews & Submits ─────────────►  Case → SUBMITTED
     │                                                              HR notified
     ▼
Reviews each section
Verifies / Rejects fields
Verifies / Rejects documents
     │
     ├─ any rejection ──────────────────────────────────────────►  Case → CHANGES_REQUESTED
     │                              Candidate notified, link          Candidate edits only the
     │                              reopens for rejected items  ◄──   rejected sections, resubmits
     │                                                                (loops back to review)
     │
     └─ everything verified
             │
             ▼
        Clicks Activate ──────────────────────────────────────►  Employee + Employment +
                                                                    Assignment (+ Compensation/
                                                                    Statutory/Bank) created
                                                                    Case → ACTIVATED
                                                                    Candidate notified: welcome +
                                                                    account/login info (out of
                                                                    scope here, see §14)
```

## 4. Data model (new tables, `hrms.onboarding` schema module)

### 4.1 `onboarding_case`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `company_id` | uuid FK | tenant scope, RLS-enforced like every other table |
| `status` | enum | `DRAFT, INVITED, IN_PROGRESS, SUBMITTED, UNDER_REVIEW, CHANGES_REQUESTED, VERIFIED, ACTIVATED, EXPIRED, CANCELLED` (§6) |
| `candidate_first_name`, `candidate_last_name` | str | set by HR at creation |
| `personal_email`, `personal_mobile` | str | invite delivery target |
| `designation_id`, `department_id`, `branch_id`, `employment_type_id` | uuid FK | pre-filled context so the candidate never chooses their own job data |
| `proposed_joining_date` | date | |
| `created_by_user_id` | uuid FK | HR/Admin who started the case |
| `personal_info`, `address_info`, `emergency_contact`, `bank_info`, `statutory_info` | jsonb | one column per wizard section; shape validated server-side against the *matching field subset* of `EmployeeCreate`/`BankCreate`/`StatutoryCreate` (§7.2) |
| `policy_ack_at`, `policy_ack_ip` | timestamptz, inet | e-sign/acknowledgement capture |
| `employee_id` | uuid FK, nullable | set on activation, links back to the real `employee` row |
| `created_at`, `updated_at` | timestamptz | |

### 4.2 `onboarding_token`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `onboarding_case_id` | uuid FK | |
| `token_hash` | text | SHA-256 of the raw token; **raw token is never stored** (mirrors how `jwt_refresh_secret`-style secrets are handled — never logged, never persisted in plaintext) |
| `expires_at` | timestamptz | default 7 days, HR-configurable per case at send/resend time |
| `used_first_at` | timestamptz, nullable | first successful open |
| `revoked_at` | timestamptz, nullable | set on resend (old token dies) or explicit HR revoke |
| `created_at` | timestamptz | |

Only one *live* token per case at a time — issuing a new one (resend) revokes the previous row
rather than deleting it, preserving an audit trail of every link ever sent.

### 4.3 `onboarding_document`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `onboarding_case_id` | uuid FK | |
| `document_type` | enum | `PHOTO, PAN, AADHAAR, ADDRESS_PROOF, EDUCATION_CERTIFICATE, PREVIOUS_EMPLOYMENT_PROOF, BANK_PROOF, OTHER` |
| `s3_key`, `original_filename`, `content_type`, `size_bytes` | | `s3_bucket_documents` (already in `Settings`, unused today — this is its first real consumer) |
| `status` | enum | `PENDING, VERIFIED, REJECTED` |
| `verified_by_user_id`, `verified_at`, `rejection_reason` | | |
| `uploaded_at` | timestamptz | |

### 4.4 `onboarding_section_review`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `onboarding_case_id` | uuid FK | |
| `section` | enum | `PERSONAL_INFO, ADDRESS, EMERGENCY_CONTACT, BANK, STATUTORY, DOCUMENTS` |
| `status` | enum | `PENDING, VERIFIED, REJECTED` |
| `reviewed_by_user_id`, `reviewed_at`, `rejection_reason` | | |

Keeping section-level review as its own table (rather than a status column baked into
`onboarding_case`) is what makes the "reject just this one section, candidate only redoes that
one" loop (§3) clean — the candidate-facing UI can show exactly which sections are reopened.

All four tables get RLS policies scoped by `company_id` following the pattern in
`docs/architecture/POSTGRES_RLS_ROLE_IMPLEMENTATION_REPORT.md`, same as every other tenant table.

## 5. The hard architectural problem: public routes have no tenant context

Every existing authenticated route derives `company_id` for Postgres RLS from the caller's JWT
(`apps/api/src/hrms/core/tenancy/middleware.py`). The candidate-facing endpoints are, by
definition, unauthenticated — there is no JWT, no logged-in user, no company membership.

**Design:** a new FastAPI dependency, `get_onboarding_case_from_token(token: str)`, that:
1. Hashes the incoming raw token and looks up `onboarding_token` by `token_hash` (index on the
   hash column, not a table scan — the token space is large enough that this is still safe
   against timing attacks in practice, but use a constant-time compare on the hash lookup result).
2. Rejects if `revoked_at` is set, `expires_at` has passed, or the case status is terminal
   (`ACTIVATED`, `CANCELLED`).
3. On success, sets the RLS session variable for `company_id` from the case's own `company_id`
   (same mechanism the JWT-derived middleware uses today, just fed a different source), scoped
   **only** to that one case's tenant — the public router can never see or touch any other
   company's data because every query still goes through `company_id`-scoped RLS, it's just that
   the *source* of the scope value is a validated token instead of a validated JWT.
4. Records `used_first_at` on first successful validation and moves `INVITED → IN_PROGRESS`.

This dependency is the single security boundary for the entire public surface — every public
route takes it as a required dependency and gets back a `company_id`-scoped, case-scoped context.
No public route ever accepts a `company_id` or `case_id` as a client-supplied parameter.

**Rate limiting:** reuse `apps/api/src/hrms/shared/rate_limit.py` (already exists, used
elsewhere) on the public router, keyed by token/IP — a brute-force token-guessing attempt is
whichever is worse, but with a 256-bit random token this is defense-in-depth, not the primary
control.

## 6. State machine

```
DRAFT ──send-invite──► INVITED ──candidate opens──► IN_PROGRESS ──candidate submits──► SUBMITTED
  │                       │                                                               │
  │                    (resend)                                                           ▼
  │                       │                                                          UNDER_REVIEW
  │                       ▼                                                          │        │
  │                    EXPIRED (token lapsed, no submission)                    all verified   any rejected
  │                                                                                  │              │
  │                                                                                  ▼              ▼
  └───────────────cancel (any non-terminal state)──────────────► CANCELLED       VERIFIED   CHANGES_REQUESTED
                                                                                      │              │
                                                                                      ▼          (reopens the
                                                                                  ACTIVATE        relevant
                                                                                      │           section(s)
                                                                                      ▼           for the
                                                                                 ACTIVATED         candidate,
                                                                                                    token stays
                                                                                                    valid, status
                                                                                                    → IN_PROGRESS)
```

`CANCELLED`, `EXPIRED`, `ACTIVATED` are terminal. Every transition is server-enforced (no client
can, say, PATCH a `SUBMITTED` case's data directly — only the section reopened by a rejection is
writable again).

## 7. API design

### 7.1 Admin-side (authenticated, RBAC-protected — `apps/api/src/hrms/modules/onboarding/router.py`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/onboarding-cases` | `ONBOARDING.CREATE` | creates `DRAFT` case |
| POST | `/onboarding-cases/{id}/send-invite` | `ONBOARDING.CREATE` | (re)issues token, sends email, `DRAFT/EXPIRED → INVITED` |
| GET | `/onboarding-cases` | `ONBOARDING.VIEW` | list + status filter, DataScope-enforced like Employee list |
| GET | `/onboarding-cases/{id}` | `ONBOARDING.VIEW` | full detail incl. sections + documents |
| POST | `/onboarding-cases/{id}/sections/{section}/review` | `ONBOARDING.REVIEW` | body: `{status: VERIFIED\|REJECTED, reason?}` |
| POST | `/onboarding-cases/{id}/documents/{doc_id}/review` | `ONBOARDING.REVIEW` | same shape, per document |
| POST | `/onboarding-cases/{id}/request-changes` | `ONBOARDING.REVIEW` | bulk-applies any pending section rejections, notifies candidate, `UNDER_REVIEW → CHANGES_REQUESTED` |
| POST | `/onboarding-cases/{id}/activate` | `ONBOARDING.ACTIVATE` | see §8.6 — 409 if any section/document isn't `VERIFIED` |
| POST | `/onboarding-cases/{id}/cancel` | `ONBOARDING.CANCEL` | any non-terminal state → `CANCELLED` |

Permission codes are new, following the `EMPLOYEE.*` catalogue's own naming precedent
(`apps/api/src/hrms/modules/employee/permissions.py`): `ONBOARDING.CREATE`, `ONBOARDING.VIEW`,
`ONBOARDING.REVIEW`, `ONBOARDING.ACTIVATE`, `ONBOARDING.CANCEL`. `ONBOARDING.ACTIVATE` is kept
separate from `.REVIEW` deliberately — activation is irreversible (real employee records get
created) and mirrors why `EMPLOYEE.TERMINATE` got its own code rather than folding into `.UPDATE`.

### 7.2 Public/token-side (unauthenticated, token-authenticated — separate router, no JWT dependency)

| Method | Path | Notes |
|---|---|---|
| GET | `/public/onboarding/{token}` | returns case status, which sections are open for editing, previously-saved draft values |
| PATCH | `/public/onboarding/{token}/sections/{section}` | autosave; body validated against the matching subset of `EmployeeCreate`/`BankCreate`/`StatutoryCreate` fields (§2) so a candidate can never submit a shape the activation step would later reject |
| POST | `/public/onboarding/{token}/documents` | multipart upload → S3, creates `onboarding_document` row `PENDING` |
| DELETE | `/public/onboarding/{token}/documents/{doc_id}` | candidate can remove/replace before submit |
| POST | `/public/onboarding/{token}/accept-policies` | records `policy_ack_at`/`policy_ack_ip` |
| POST | `/public/onboarding/{token}/submit` | validates all required sections+documents present, `IN_PROGRESS → SUBMITTED`, locks further edits, notifies HR |

Only sections currently in `PENDING`/reopened-by-rejection state are writable — once a section is
`VERIFIED`, the public PATCH for it 409s, so a candidate can't quietly change already-approved data.

## 8. Key implementation notes

### 8.1 Token generation
`secrets.token_urlsafe(32)` (stdlib, already the kind of primitive used for the JWT secrets) →
raw token embedded in the link, `hashlib.sha256(raw).hexdigest()` stored as `token_hash`.

### 8.2 Section validation reuse
`PATCH .../sections/personal_info` validates its body against a `PersonalInfoOnboardingSchema`
that is a strict field subset of `EmployeeCreate` (same field names/types/constraints) — not a
hand-rolled copy that can drift. Same pattern for `bank_info` against `BankCreate` and
`statutory_info` against `StatutoryCreate`.

### 8.3 Document storage
First real usage of `Settings.s3_bucket_documents`/`aws_region`/`aws_access_key_id` — needs a
thin `DocumentStorageService` wrapping `boto3` (put/get/delete + presigned GET URLs for the admin
review UI, so document bytes never round-trip through the API server for viewing). Virus scanning
(mentioned in `docs/product/17` FR-EMP-007) is explicitly **out of scope for the first cut**
(§14) — flag this as a follow-up, not silently skip it.

### 8.4 Email delivery
**Blocking gap:** the Notifications engine (`docs/product/VERSION_1_ROADMAP.md` row 6) is
"Not started" and there is no existing email-sending code anywhere in the API
(`grep` for SES/SMTP/sendgrid across `apps/api` returns nothing real). Two options:
- **(a) Recommended:** build a minimal, onboarding-scoped `EmailSender` port (one interface,
  one SES or SMTP implementation, three templates: invite, changes-requested, activated) —
  small, unblocks this module now, and is designed to be swapped for the real Notifications
  engine later without touching onboarding's business logic.
- (b) Treat the full Notifications engine as a prerequisite and build a minimal slice of it
  first, with onboarding as its first consumer.
This plan assumes (a); flag to the user as a decision point (§15).

### 8.5 Section-level review UI reuses existing panel patterns
The admin review screen for each section can visually mirror the existing
`EmploymentPanel`/`CompensationPanel`/`StatutoryPanel`/`BankingPanel` components
(`apps/web/src/components/employee/`), just rendered read-only with Verify/Reject controls
instead of edit forms — same visual language the HR team already knows from the employee detail
page.

### 8.6 Activation — the transaction that matters most
`POST /onboarding-cases/{id}/activate`, single DB transaction:
1. Assert every `onboarding_section_review` and `onboarding_document` row is `VERIFIED` (409 with
   the list of what's outstanding if not — no partial activation).
2. Call `EmployeeService.create_employee(EmployeeCreate(**case.personal_info))`.
3. Call `EmploymentService.create_employment(EmploymentCreate(employee_id=..., joining_date=case.proposed_joining_date, employment_type_id=case.employment_type_id, ...))`.
4. Call `EmployeeAssignmentService.create_assignment(AssignmentCreate(change_type=INITIAL, department_id=case.department_id, designation_id=case.designation_id, branch_id=case.branch_id, ...))`.
5. If `bank_info`/`statutory_info` were collected, call `EmployeeBankService.create_bank(...)` /
   `EmployeeStatutoryService.create_statutory(...)`.
6. Set `onboarding_case.employee_id`, `status = ACTIVATED`.
7. Fire the "welcome" notification (§8.4) — login/account-creation itself is out of scope (§14).

Every one of these calls already exists and already enforces its own validation — activation's
own code is just orchestration, not new business rules.

## 9. Frontend plan

**Admin app** (`apps/web/src/app/app/onboarding/`):
- `page.tsx` — case list, status-filtered, "Start Onboarding" button opening a dialog that
  mirrors the existing "Add Employee" dialog (`apps/web/src/app/app/employees/page.tsx:78-139`)
  but collects only the minimal pre-fill fields (§4.1) plus personal email/mobile.
- `[id]/page.tsx` — case detail: candidate summary, per-section review cards (Verify/Reject +
  reason), document list with presigned-URL preview/download and Verify/Reject, "Resend link" /
  "Copy link" / "Cancel" actions, "Activate" button (disabled with a tooltip listing what's still
  unverified until everything is green).

**Public candidate wizard** (new route group **outside** the authenticated `/app` shell, e.g.
`apps/web/src/app/onboarding/[token]/`): a mobile-friendly multi-step form — Welcome → Personal
Info → Address & Emergency Contact → Bank Details → Statutory Details → Document Upload → Policy
Acknowledgement → Review & Submit → Confirmation. Each step autosaves via its `PATCH` route so a
candidate can close the tab and resume later without losing progress.

## 10. Testing plan

- Unit: state-machine transition legality, token hashing/expiry/revocation, section-schema
  validation (subset-of-`EmployeeCreate` conformance), activation orchestration with mocked
  employee-module services.
- Integration: full public-token flow hitting real routes with no auth header (mirrors the
  existing JWT-linkage security tests, `0b217f0`'s pattern, but for the *absence* of a JWT);
  cross-tenant isolation test (token for company A must never be able to see/affect company B's
  data — the RLS-from-token mechanism in §5 is the highest-risk piece in this whole plan and
  deserves the most test weight); full end-to-end activation test asserting the real `Employee`/
  `Employment`/`Assignment` rows land correctly from a completed case.

## 11. Migrations

New Alembic revision adding `onboarding_case`, `onboarding_token`, `onboarding_document`,
`onboarding_section_review`, their RLS policies, and seeding the five new `ONBOARDING.*`
permission codes into the existing permission catalogue (same seed mechanism used in
`seed_b1_foundation`, per the pattern noted in `employee/permissions.py`'s own history).

## 12. Phased delivery

| Phase | Delivers | Depends on |
|---|---|---|
| O1 | Data model + migrations + admin create/list/detail (no link yet) | — |
| O2 | Token issuance + `get_onboarding_case_from_token` + public GET/PATCH sections, RLS-from-token proven with cross-tenant test | O1 |
| O3 | Minimal `EmailSender` (§8.4) + send-invite/resend | O2 |
| O4 | Candidate-facing wizard UI | O2, O3 |
| O5 | Document upload (`DocumentStorageService`, S3) + document review UI | O1 |
| O6 | Section review + changes-requested loop | O2, O4 |
| O7 | Activation transaction (§8.6) | O1–O6 |

Each phase is independently shippable and testable, same granularity as the employee module's own
E-01…E-09 slices.

## 13. Open questions for product/stakeholder sign-off

1. **Email sender approach** — build the minimal scoped `EmailSender` now (§8.4 option a,
   recommended) or block on the full Notifications engine?
2. **Link channel** — email only for V1, or also SMS? (Affects whether `personal_mobile` is
   required at case creation.)
3. **Document virus scanning** — required before this ships, or an accepted follow-up?
4. **Post-activation account creation** — does Activate also provision the new employee's login
   (`identity` module user + ESS access), or is that a separate manual step? ESS itself isn't
   built yet (roadmap: "Not started"), so this plan assumes login provisioning is out of scope
   and Activate only creates the HR-side employee record — confirm this is acceptable.
5. **Re-onboarding / duplicate prevention** — what happens if HR starts a second case for the
   same `personal_email`? (Recommend: block while an active, non-terminal case exists for that
   email within the company.)

## 14. Explicitly out of scope (deferred to the V2 `FR-ONB` automation, per the roadmap)

Department/designation-specific task-pack templates, automatic IT/Admin/Finance/Manager task
creation and reminders, auto-provisioning webhooks to external systems, buddy/mentor assignment
and 30/60/90-day check-ins, day-1 induction content/videos, no-show handling, onboarding status
dashboard/analytics (joiners this week, completion %). All ten of `FR-ONB-001–010`
(`docs/product/17_SRS_Phase1_Core_Modules.md` §9) beyond "candidate self-fills a form and HR
verifies it" stay V2, unchanged from the existing roadmap decision.

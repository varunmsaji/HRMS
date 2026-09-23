# Employee Account Provisioning & Login — Audit & Implementation Plan

**Date:** 2026-09-12
**Status:** Audit + implementation plan. **Phase 1 (role seeding, §8) has since shipped** — see the
"Phase 1 — Implemented" addendum at the end of this document. Phases 2-6 remain planning only.
Decisions P2 and P4 (§5) were OPEN at authoring time; both were resolved by the product owner on
2026-09-12 and are now LOCKED (see their sections below) — Phase 2 can proceed against a settled
spec.
**Method:** Independently re-verified against the current working tree via direct file reads and
grep (file:line citations below), not assumed from any prior document's claims.

**Relationship to prior documents:** `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` ("Decisions")
locked the authorization *scope model* (`COMPANY`/`SELF`/`REPORTEES`/`REPORTEE_TREE`, attached
per role-permission grant) and proposed, but explicitly did not build, three new default roles
(`EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN` — Decision H). `docs/modules/employee/25_..._PLAN.md`,
`39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md`, and their corresponding `_REPORT.md` files
shipped the *enforcement machinery* for that scope model across the Employee, Attendance, and Leave
modules (real code, real migration `20260815120000_role_permission_data_scope.py`, real tests).

**What none of those documents cover, and what this document is about:** every one of them assumes
a `User` already exists for the person being authorized. None of them address *how an Employee gets
a login in the first place*. That gap is independently confirmed still open in this document (§1)
and is the subject of the plan in §5 onward. This is also why the enforcement work above is
currently **dormant** — `39_...md`'s own executive summary independently confirms every
`EMPLOYEE.*` permission is seeded at `COMPANY` scope for the one role that exists (`COMPANY_ADMIN`);
there is no second role and no second user for any of `SELF`/`REPORTEES`/`REPORTEE_TREE` to ever
apply to.

---

## 1. Executive Summary

The authorization *enforcement* layer for employee self-service (data-scope resolution, 404-not-403
on out-of-scope records, JWT `employee_id` linkage) is real, tested, and wired into the Employee,
Attendance, and Leave modules. **The account layer underneath it does not exist.** Specifically:

- No code path anywhere creates a `User` row for an `Employee`, or ever sets the pre-existing
  `Employee.user_id` column. It is `NULL` for every employee in every company, always.
- The three roles the scope model needs to mean anything (`EMPLOYEE`, `REPORTING_MANAGER`,
  `HR_ADMIN`) are designed on paper (Decisions doc, Decision H) but not seeded anywhere — not at
  real company registration, not in the demo seed.
- There is no invite, password-set, or password-reset flow for anyone except the single
  self-registering `COMPANY_ADMIN`. `SETTINGS.USER.MANAGE` and `SETTINGS.ROLE.MANAGE` are dead
  permission codes with no endpoint behind them.
- A working, tested, production token-issue/hash/TTL/resolve/RLS pattern already exists for a
  structurally identical problem — the onboarding module's candidate invite link
  (`onboarding/public_router.py`, `OnboardingTokenService`) — and is the recommended template
  rather than a new design.

**Net effect today:** a company can only ever have one login (the admin who registered it). Every
employee record created through onboarding, manual entry, or CSV import is permanently
un-loggable-in-as, regardless of how sophisticated the scope enforcement behind that hypothetical
login would be.

**Recommendation:** treat this as three separable, sequentially-dependent pieces of work — (A) seed
the three proposed roles with correct scope grants, (B) build account provisioning (invite → set
password → `User` created, linked, role-assigned), (C) build the minimal frontend an employee needs
once they can log in — plus one cross-cutting piece, password reset, that (B) exposes the need for
immediately. Plan in §5.

---

## 2. Scope

**In scope:** how a `User` gets created for an `Employee` and linked (`Employee.user_id`); how that
user gets a role (`EMPLOYEE` / `REPORTING_MANAGER` / promotion between them); how a company admin
adds a *second* administrative/HR user (the same underlying mechanism, different role); the
invite/password-set/password-reset flows this requires; the minimal frontend (login company-picker,
invite-acceptance page, and the smallest useful ESS surface) needed for any of this to be usable.

**Out of scope, deliberately, and why:**
- Re-litigating the scope model itself (`COMPANY`/`SELF`/`REPORTEES`/`REPORTEE_TREE`) — already
  locked and implemented. This plan consumes it, does not change it.
- A general custom-role-builder UI (create arbitrary roles with arbitrary permission sets). Decision
  H's own reasoning (a small fixed role catalogue, not a config-driven engine ahead of need) applies
  equally here — role *assignment* among four fixed roles is in scope; role *authoring* is not.
- `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` scope levels, subscription/plan management, notification
  settings — unrelated pre-existing gaps (tracked separately), not blocking this work and not
  addressed by it.
- Fixing `localStorage` token storage's XSS exposure (`token-storage.ts:14-21`'s own docstring
  already flags this as a known tradeoff). Noted as a risk this plan increases the stakes of (§7),
  not something this plan fixes.

---

## 3. Sources Inspected

`core/db/models/identity.py` (`User`, `UserCompany`, `Role`, `RolePermission`, `UserRole`);
`modules/employee/models.py` (`Employee.user_id`), `repository.py` (`get_employee_by_user_id`),
`service.py` (`resolve_employee_id_for_user`, `create_employee`); `modules/identity/router.py`,
`service.py`, `schemas.py`; `modules/onboarding/service.py` (`activate_case`,
`OnboardingTokenService`), `public_router.py`, `dependencies.py`, `email_sender.py`;
`modules/organisation/service.py` (`register_company`), `repository.py` (`insert_role`,
`insert_role_permission`); `seed/bootstrap.py`; `core/auth/jwt.py`, `types.py`, `dependencies.py`;
`core/rbac/types.py`, `service.py`, `dependencies.py`; `apps/web/src/lib/auth/*`;
`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`;
`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md`;
`docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md`.

---

## 4. Current State — Verified Findings

**F1 — `User` has no `employee_id`; the FK runs the other way, and is write-never.**
`User` (`core/db/models/identity.py:81-95`) has no Employee-linkage column at all. `Employee.user_id`
(`modules/employee/models.py:45-47`) is a nullable FK to `user.id`, present since the original schema
(`apps/api/scripts/sql/001_init_schema.sql:224-239`), with no DB uniqueness constraint
(`employee/repository.py:94-97`, documented explicitly). It is read in exactly one place
(`get_employee_by_user_id`, `employee/repository.py:91-108`, used to resolve `employee_id` into the
JWT — `identity/service.py:232`, `employee/service.py:143-152`) and **written in zero places** —
confirmed by grep across `employee/service.py`'s `create_employee`, `onboarding/service.py`'s
`activate_case` (lines 864-1013, calls `EmployeeService.create_employee` at line 908 with an
`EmployeeCreate` schema that never carries a `user_id`), and `organisation/service.py`. The JWT
`employee_id`-resolution machinery (`fecb740`) is real and correct; it simply has nothing to resolve
for any employee today, because the column it queries is always `NULL`.

**F2 — The three roles the scope model needs don't exist anywhere.**
`organisation/service.py:register_company` seeds exactly one role, `COMPANY_ADMIN`
(`COMPANY_ADMIN_ROLE_CODE`, line 200; `insert_role(...)` at 435-442), granted essentially every
permission in the system via repeated `insert_role_permission` calls (lines 341-459+).
`insert_role_permission` (`organisation/repository.py:142`) takes no `data_scope` argument, so every
grant lands at the migration's column default, `COMPANY`. `seed/bootstrap.py` (demo-only) adds a
second role, `EMPLOYEE_VIEWER` (line 81, `EMPLOYEE.VIEW` only, still `COMPANY` scope) — not present
in the real registration path. `EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN` (Decisions doc, Decision
H) appear in zero code paths, confirmed by exact-string grep.

**F3 — No invite, password-set, or password-reset flow exists for anyone.**
`identity/router.py` (99 lines, read in full) exposes only `POST /auth/login`,
`POST /auth/token/refresh`, `POST /auth/logout`, `GET /auth/me`, the dead `GET
/auth/admin/users-check` stub, and `GET /auth/companies/{company_id}`. Grep for
`forgot_password|reset_password|set_password|password_reset` across all of `apps/api/src/hrms/`
returns zero matches. The only way any `User.password_hash` is ever set is inline, at
self-registration (`organisation/service.py`'s `register_company`).

**F4 — A production-grade, reusable invite-token pattern already exists (onboarding).**
`OnboardingTokenService.issue_token` (`onboarding/service.py:396-432`): `secrets.token_urlsafe(32)`
raw token, only `hashlib.sha256(...)` persisted, TTL-bound `expires_at`, prior live tokens for the
same subject revoked before issuing a new one. `get_onboarding_case_from_token`
(`onboarding/dependencies.py:50-62`) resolves a raw token with no `AuthenticatedUser`/JWT available,
sets the RLS `company_id` GUC from what the token resolves to, and returns a minimal context object.
`onboarding/public_router.py` mounts this as a fully unauthenticated router. `email_sender.py`
provides a `Protocol`-based sender (`LoggingEmailSender` for dev, `SesEmailSender` for prod) already
used to deliver these links. This is the template for §5 Phase 1/2, not a new design problem.

**F5 — Login already supports N companies/roles per user; nothing downstream uses that generality
for employees.**
`IdentityService.login` (`identity/service.py:37-91`) fetches every `UserCompany` membership for the
authenticating user (`list_user_companies_for_login`, line 58), builds a `CompanySummary[]`, and
either auto-picks the primary/first membership or validates a caller-supplied `company_id` against
the caller's actual memberships (anti-enumeration: same generic error either way). This was clearly
built to support a user holding multiple company memberships and/or multiple roles — it is simply
unused today because no user has ever had more than one `UserCompany` row.

**F6 — Frontend has permission-code gating, no scope/role concept, no company-switcher UI, no
invite-acceptance page.**
`apps/web/src/lib/auth/use-permissions.ts` (`usePermissions()`) is UI-only convenience over the flat
`permissions: string[]` from `/auth/me` — explicitly documented as not a security boundary. No
`PermissionGate`/`RoleGate` component exists (confirmed by grep); permission checks are inlined in
~35+ page/component files. `auth-context.tsx`/`token-storage.ts` store a `companies: CompanySummary[]`
array from login but there is no UI built on it — no company picker, despite the backend already
returning the data for one. No page exists that parallels `/onboarding/[token]` for an account-setup
token.

---

## 5. Design Decisions

Following this project's own convention (see Decisions doc): **LOCKED** where the codebase already
gives a clear, low-risk answer; **OPEN** where it genuinely requires the user's judgment call.

### Decision P1 — How does an Employee get a `User`? Invite-based, not auto-created-with-a-password.

**LOCKED: never auto-generate or email a plaintext password. Always issue a time-boxed,
single-use, hashed invite token (F4's pattern) that lets the employee set their own password.**

Reasoning: this is what onboarding already does for candidates, for the same class of problem
(getting a credential to someone who isn't authenticated yet, without the operator ever holding
their password). Reusing it means no new security review surface for "how do we deliver a
password" — the same threat model onboarding invites already passed applies unchanged.

### Decision P2 — Who can trigger an invite, and when?

**LOCKED (two trigger points, both funnelling into the same `AccountInviteService`):**
1. **At onboarding activation** (`activate_case`, `onboarding/service.py:864-1013`) — if the case's
   `personal_email` is present (it always is; the field is required earlier in the wizard), issue an
   invite automatically as part of activation, in the same transaction that creates the `Employee`
   row. This is the common-path, zero-extra-clicks case.
2. **On-demand, from the Employee detail page**, for employees who already exist without a login
   (every employee created before this feature ships, plus anyone created via manual entry or CSV
   import, which have no onboarding case at all). A new `POST /employees/{id}/invite` endpoint,
   gated by a new permission (`EMPLOYEE.INVITE` — see P5), re-issues the invite (revoking any prior
   live one, same as onboarding's own re-invite behavior).

**LOCKED (resolved 2026-09-12): on-demand only. CSV bulk import does not auto-trigger an invite.**
A bulk-imported employee gets exactly the same account state as one entered manually — an
`Employee` row with no `User`, invited later via the on-demand path (path 2, above). Reasoning
(product owner's stated rationale, matching this document's own recommendation): auto-inviting on
import risks emailing dozens/hundreds of people at once from a single admin action with no
per-row review step; on-demand invitation lets an admin choose deliberately, after import
completes and any row errors are resolved. Revisit only if bulk-invite becomes a real, explicitly
requested ask — do not build it speculatively.

### Decision P3 — What happens if two Employees share a personal email, or an Employee's email
matches an existing `User` (e.g., the `COMPANY_ADMIN` who is also an employee)?

**LOCKED:** invite issuance must look up `User` by email **within the company** first. If a `User`
with that email already exists as a member of the same company (e.g., the registering admin later
gets an `Employee` row created for themselves), the invite flow attaches the *existing* `User` (sets
`Employee.user_id` to it, adds a `UserRole` for the new role if not already held) rather than
attempting to create a duplicate `User` — `email` has no stated uniqueness constraint at the DB level
today (needs verification as part of Phase 1 spike, not assumed), so this must be an explicit
application-level check, not left to a constraint violation. If the email belongs to a `User` in a
**different** company, treat it as a normal new invite for this company (a person can legitimately
work at, or be an admin of, more than one tenant — this is exactly what `UserCompany` already
models).

### Decision P4 — Default role on acceptance, and promotion to `REPORTING_MANAGER`.

**LOCKED: every invited employee gets `EMPLOYEE` by default.** Matches Decisions doc Decision H's
framing of `EMPLOYEE` as "every ordinary employee's baseline self-service role."

**LOCKED (resolved 2026-09-12): manual only, via P5's role-assignment action.** Becoming another
employee's `reporting_manager_id` (an Assignment-module write) never by itself grants
`REPORTING_MANAGER` or any other role. An admin/HR_ADMIN must separately assign the role through
`PATCH /users/{user_id}/roles` (P5). Reasoning (product owner's stated rationale, matching this
document's own recommendation): access changes should always be a deliberate, auditable action,
never a side effect of an org-chart edit the admin may not think of as "granting more access."
This also composes more simply with P5's endpoint — no event/trigger machinery is needed on the
Assignment write path. Revisit only if manual assignment proves to be real, sustained admin
overhead once real customers use this.

### Decision P5 — Minimal role-assignment endpoint (closes the `SETTINGS.ROLE.MANAGE`/
`SETTINGS.USER.MANAGE` dead-code gap, without building a role-authoring UI).

**LOCKED: one endpoint, `PATCH /users/{user_id}/roles`, that assigns/removes from the four fixed
role codes (`COMPANY_ADMIN`, `HR_ADMIN`, `REPORTING_MANAGER`, `EMPLOYEE`) for a `UserCompany`. No
custom role creation, no permission-picker UI.** Gated by `SETTINGS.ROLE.MANAGE` (the permission
code already exists and is otherwise dead — see F2/§1 of prior audits) — grant it to `COMPANY_ADMIN`
at registration (a gap in itself: recall from prior audit that `SETTINGS.ROLE.MANAGE` and
`SETTINGS.USER.MANAGE` are currently **not even granted** to the self-registered admin; this must be
added as part of Phase 2). Reasoning: this is the smallest change that lets a `COMPANY_ADMIN`
actually use the roles Phase 2 seeds, without reopening the "generic role-authoring engine before a
second consumer exists" question Decision A/H already closed for good reasons.

### Decision P6 — Password reset.

**LOCKED: build it now, not deferred.** Once real employees (not just one admin who wrote down
their own password at registration) exist, "I forgot my password" stops being a hypothetical support
case and becomes routine. Reuse the exact same token pattern as the invite flow (P1) — a
`POST /auth/password/forgot` (email in, always-200 response regardless of whether the email
exists, to avoid account enumeration) and `POST /auth/password/reset` (token + new password).

---

## 6. Data Model Changes

**New table, `account_invite`** (deliberately generalized, not `employee_invite` — the same
mechanism serves both "invite an employee" and "invite a second admin/HR user," per P2/P5's shared
funnel):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `company_id` | UUID FK → `company.id` | RLS-scoped, same pattern as every other tenant table |
| `email` | citext/text | target email; not necessarily an existing `Employee`'s email (P5's admin/HR-invite path has no `Employee` row at all) |
| `employee_id` | UUID FK → `employee.id`, nullable | set when the invite is for an existing Employee (P2 path 1/2); null for a standalone admin/HR invite (P5) |
| `role_code` | text | one of the four fixed role codes (P4/P5); the role granted on acceptance |
| `token_hash` | text | `sha256(raw_token)`, never the raw token — mirrors `OnboardingTokenService` exactly |
| `status` | enum | `PENDING` / `ACCEPTED` / `REVOKED` / `EXPIRED` |
| `expires_at` | timestamptz | |
| `created_by` | UUID FK → `user.id` | who triggered the invite |
| `accepted_at` | timestamptz, nullable | |

**No change needed** to `Employee.user_id` (already exists, just needs to actually get written —
see F1) or to `User`/`UserCompany`/`UserRole` (already shaped correctly for this — see F5).

**New migration** to seed `EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN` role/permission rows per
Decisions doc Decision H's table — as **new rows insertable by a data migration for existing
companies** (see §9 Rollout) as well as by `register_company` for new ones.

---

## 7. API Surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /employees/{id}/invite` | `EMPLOYEE.INVITE` (new code) | Issue/re-issue an invite for an existing Employee (P2 path 2) |
| `POST /users/invite` | `SETTINGS.USER.MANAGE` | Issue an invite for a non-employee user — second admin/HR user (P5's other funnel input) |
| `GET /public/account-invites/{token}` | none (public) | Resolve token → show company name + email being invited, mirrors `onboarding/public_router.py`'s shape |
| `POST /public/account-invites/{token}/accept` | none (public) | Body: `{ password, first_name?, last_name? }`. Creates or reuses `User` (P3), sets `Employee.user_id` if applicable, creates `UserCompany` + `UserRole(role_code)`, marks invite `ACCEPTED`, returns tokens (auto-login, same shape as `/auth/login`) |
| `PATCH /users/{user_id}/roles` | `SETTINGS.ROLE.MANAGE` | Assign/remove among the 4 fixed role codes (P5) |
| `POST /auth/password/forgot` | none (public) | Always-200, issues reset token if the email matches (P6) |
| `POST /auth/password/reset` | none (public) | Token + new password (P6) |

All public endpoints follow the existing `_registration_rate_limit`-style IP rate limiting already
applied to `POST /companies/register` (`organisation/router.py:88`) — same threat model (unauth'd,
publicly reachable, must not be a brute-force or enumeration vector).

---

## 8. Phased Implementation Plan

**Phase 0 — Product decisions.** Resolve the two OPEN items (P2's bulk-import question, P4's
auto-promotion question) before writing code that depends on either answer. Everything else below
can proceed regardless.

**Phase 1 — Role seeding.**
- Migration: seed `EMPLOYEE` / `REPORTING_MANAGER` / `HR_ADMIN` role + `role_permission` rows (with
  `data_scope` values per Decisions doc Decision H's table) into `register_company`'s insert path.
- Backfill migration for existing companies (see §9).
- Add `SETTINGS.ROLE.MANAGE` + `SETTINGS.USER.MANAGE` to `COMPANY_ADMIN`'s grant list in
  `register_company` (currently absent — a pre-existing bug this phase must also fix, or P5's
  endpoint is uncallable by the only role that exists).
- Tests: extend the existing `tests/integration/modules/organisation/test_permission_matrix.py`
  pattern to cover the three new roles' exact grant sets.

**Phase 2 — Account provisioning backend.**
- `account_invite` table + migration (§6).
- `AccountInviteService`: `issue`, `resolve`, `accept` — copy `OnboardingTokenService`'s
  hash/TTL/revoke-prior-on-reissue shape directly (F4).
- Wire into `activate_case` (auto-issue on activation, same transaction, best-effort email send
  matching the existing "activated" email's swallow-failure behavior at `onboarding/service.py:993-1003`).
- `POST /employees/{id}/invite`, `POST /users/invite`, `GET /public/account-invites/{token}`,
  `POST /public/account-invites/{token}/accept` endpoints + router wiring (new `account_invite`
  module, or folded into `identity` — recommend a new module, mirroring how `onboarding` got its own
  module rather than living inside `employee`).
- `PATCH /users/{user_id}/roles` endpoint.
- New permission code `EMPLOYEE.INVITE`, added to `COMPANY_ADMIN`'s and `HR_ADMIN`'s grants.

**Phase 3 — Password reset.**
- `POST /auth/password/forgot` / `POST /auth/password/reset`, same token pattern, in `identity`
  module.

**Phase 4 — Frontend.**
- `/accept-invite/[token]` page — mirrors `/onboarding/[token]`'s public page shape: resolve token,
  show who/what company, password-set form, calls accept endpoint, then auto-logs-in (reuse
  `applyTokenResponse` from `auth-context.tsx`, already built for exactly this "I just got tokens
  from somewhere other than the login form" case).
- `/forgot-password`, `/reset-password/[token]` pages, same pattern.
- Login page: render a company picker when `/auth/login`'s response (or a pre-flight check) shows
  more than one `CompanySummary` — the backend already returns the array (F5); today's frontend
  silently accepts whatever the backend auto-picks.
- "Invite" button on the Employee detail page (calls `POST /employees/{id}/invite`), gated by
  `EMPLOYEE.INVITE` via the existing `usePermissions()` pattern — no new gating mechanism needed.
- A minimal user/role-management screen (list `UserCompany` rows for the tenant + the new
  `PATCH .../roles` action) — this is the first real "Settings > Users" page the product has ever
  had; keep it deliberately small (a table + a role dropdown per row), not a general admin console.
- Minimal ESS surface once an `EMPLOYEE`-role user can log in: reuse existing components under
  `SELF` scope, which the backend already enforces (F1/§1 of this doc's predecessor audits) —
  My Profile (read-only identity/employment/assignment tabs, same components as the admin-facing
  employee detail page, just scoped to the logged-in user's own `employee_id`), My Attendance, My
  Leave (apply + balance). No new backend work required for this slice — it is a frontend routing/
  UI exercise against endpoints that already return correctly-scoped data for a `SELF`-scoped caller.

**Phase 5 — Security hardening.**
- Rate-limit all four new public endpoints identically to registration's existing limiter.
- Confirm invite tokens are single-use (mark `ACCEPTED` and reject reuse) and that re-issuing
  revokes the prior token (mirrors onboarding's existing behavior — don't leave two live tokens for
  the same target).
- Decide (does not have to be fixed here, but must be a conscious call, not silence) whether the
  existing `localStorage`-token XSS tradeoff (`token-storage.ts:14-21`) is acceptable now that the
  number of real logins is about to grow from 1-per-company to potentially every employee — this
  plan does not change the storage mechanism, but it does materially increase what's at stake if
  that tradeoff is ever revisited.

**Phase 6 — Tests.**
- Integration tests for the full accept-invite → login → `/auth/me` shows correct `employee_id` and
  `EMPLOYEE`-role permissions chain (extends the existing pattern in
  `tests/integration/auth/test_employee_jwt_linkage.py`, which already tests the JWT-resolution half
  of this).
- Permission-matrix tests for the two new endpoints (`EMPLOYEE.INVITE`, `SETTINGS.ROLE.MANAGE`).
- Security tests: invite token reuse rejected, expired token rejected, cross-company token rejected,
  password-reset doesn't leak account existence (F3/P6).

---

## 9. Rollout Considerations for Existing Companies

Any company that registered before this ships has: one `COMPANY_ADMIN` user, zero `EMPLOYEE`/
`REPORTING_MANAGER`/`HR_ADMIN` roles, and every `Employee.user_id` `NULL`. Phase 1's role-seeding
migration must **insert the three new roles for every existing company**, not just gate new
registrations — otherwise this feature is invisible to every company that already exists. No
existing `Employee` gets an invite automatically as part of the migration (that would mass-email
every employee at every existing tenant the moment this ships, with no admin in the loop) — existing
employees get invited one at a time via the on-demand path (P2, path 2), same as any employee
created after this ships without an onboarding case.

---

## 10. Open Product Decisions Requiring Your Input

1. ~~**P2:** should CSV bulk import auto-invite every imported row, or stay on-demand-only for
   now?~~ **Resolved 2026-09-12: on-demand only.** See Decision P2.
2. ~~**P4:** should `REPORTING_MANAGER` be auto-granted the moment someone becomes a manager in
   the org chart, or only via the manual role-assignment screen?~~ **Resolved 2026-09-12: manual
   only.** See Decision P4.
3. **Still open, not yet blocking Phase 2's core build:** should the invite email come from a
   staff-spectrum-branded sender, or a customer-configurable "from" name/address** (relevant once
   real companies, not just demo data, are sending these)? `email_sender.py`'s `SesEmailSender`
   would need to know which identity to send as; today it's presumably a single fixed sender for the
   one email onboarding already sends.

---

## 11. Sequencing Recommendation

Phase 1 (roles) → Phase 2 (provisioning backend) → Phase 4's invite-acceptance page (needed to test
Phase 2 end-to-end) → Phase 3 (password reset, independent, can run in parallel with Phase 2) →
Phase 5 (hardening, review gate before any real customer email goes out) → Phase 6 (tests, written
alongside each phase in practice, listed last only because it's the acceptance gate for calling this
done) → the rest of Phase 4 (ESS surface, company-picker, user-management screen) last, since none
of it can be exercised until a real second login exists to test it with.

---

## 12. Addendum — Phase 1 Implemented (2026-09-12)

**Shipped, code + migration, verified against the live dev database:**
- `organisation/repository.py::insert_role_permission` now accepts a `data_scope` parameter
  (default `COMPANY`, every existing call site unaffected).
- `organisation/service.py::register_company` now seeds `HR_ADMIN` (full `EMPLOYEE.*` catalogue,
  `COMPANY` scope), `REPORTING_MANAGER` (`EMPLOYEE.VIEW`, `REPORTEE_TREE` scope), and `EMPLOYEE`
  (`EMPLOYEE.VIEW`/`.VIEW_COMPENSATION`/`.VIEW_STATUTORY`/`.VIEW_BANKING`, `SELF` scope) for every
  new registration, per Decision H. Also grants `COMPANY_ADMIN` the previously-ungranted
  `SETTINGS.USER.MANAGE`/`SETTINGS.ROLE.MANAGE` codes. None of the three new roles is assigned to
  the registering admin.
- New migration `20260920090000_default_roles_backfill.py` — idempotent backfill of the same four
  grants for every company that registered before this shipped (§9 Rollout).

**Verification performed (not just code review):** applied the migration against the dev DB and
confirmed correct backfill by direct SQL query; registered a new company through the live running
API (`curl POST /companies/register`) and confirmed by direct SQL query that all four roles were
created with the correct permission counts and `data_scope` values, and that only `COMPANY_ADMIN`
was assigned to the admin user. `ruff` and `mypy` both pass clean on the changed files.

**Known pre-existing issue, not caused by this change:** `tests/integration/modules/organisation/
test_permission_matrix.py` and `test_registration_flow.py` fail in this dev environment both before
and after this change (confirmed via `git stash` — identical failures either way). Root cause
appears to be the long-lived shared `hrms_dev` database accumulating rows across repeated manual
and automated runs over time (e.g. `MultipleResultsFound` on a query expecting one row), not a
defect in the application or in this migration.

**Not started:** Phases 5-6 (formal hardening review, committed test suite). Decisions P2 and P4
above are now LOCKED, resolved by the product owner on 2026-09-12.

## 13. Addendum — Phase 2 Implemented (2026-09-12)

**Shipped, code + migration, verified end-to-end over real HTTP:**
- New module `hrms.modules.account_invite/` (models, repository, service, schemas, exceptions,
  email template, router, public_router, dependencies) — structural copy of `onboarding`'s
  token-issue/resolve/accept pattern (F4), with **no RLS on `account_invite`** applied up front
  (learned from onboarding's own corrective migration rather than repeating the mistake).
- Migration `20260921090000_account_invite.py` — table + `EMPLOYEE.INVITE` permission code,
  granted to existing `COMPANY_ADMIN`/`HR_ADMIN` roles (idempotent backfill, same pattern as
  Phase 1's).
- `EMPLOYEE.INVITE` added to `employee/permissions.py`'s `EMPLOYEE_PERMISSIONS` list — new
  registrations pick it up automatically via `register_company`'s existing grant loop.
- `Employee.user_id` finally gets a writer: `EmployeeRepository.link_user`, called once at
  invite-acceptance (closes finding F1 from §4 above).
- Endpoints: `POST /employees/{id}/invite` (`EMPLOYEE.INVITE`), `POST /users/invite`
  (`SETTINGS.USER.MANAGE`), `PATCH /users/{user_id}/roles` (`SETTINGS.ROLE.MANAGE`),
  `GET /public/account-invites/{token}`, `POST /public/account-invites/{token}/accept`.
- Auto-invite wired into `onboarding/service.py::activate_case` (Decision P2 path 1) —
  best-effort, wrapped so a failure never undoes the activation, matching the existing welcome-
  email's own error-swallowing convention right next to it.
- Role assignment is a full replace among the four fixed codes; self-role-change is blocked
  entirely (`SelfRoleChangeNotAllowedError`) — a deliberate, narrower substitute for a "last
  admin" check, documented in the exception's own docstring as the thing to replace it with later.

**Verification performed:**
- `ruff`/`mypy` clean across the whole `hrms` package.
- Full scenario suite run directly against the live dev DB (service-layer, then confirmed over
  real HTTP with `X-Company-Id` set): issue invite for an existing employee → resolve →
  accept → auto-login → `Employee.user_id` linked; invite a second, non-employee user (`HR_ADMIN`)
  → accept → correct permissions; role reassignment (`EMPLOYEE` → `REPORTING_MANAGER`) → permission
  set updates accordingly; self-role-change blocked; re-inviting an already-linked employee blocked
  (`EmployeeAlreadyHasAccountError`); accepting for an email already active in the same company
  blocked (`UserAlreadyInCompanyError`); invalid role code rejected on both issue and assign paths.
- Confirmed over real HTTP (not just direct service calls): `POST /users/invite`,
  `GET /public/account-invites/{token}`, `POST /public/account-invites/{token}/accept` all return
  correct 200/201 responses end-to-end, including a working auto-login token pair.

**Unrelated bug found and characterized while testing (not fixed — out of this phase's scope):**
`get_current_user` (`core/auth/dependencies.py:38`) queries the RLS-protected `user_company` table
before any request-scoped RLS context has necessarily been established — it depends entirely on
`TenancyMiddleware` having already set the tenant contextvar from a client-supplied
`X-Company-Id` header (`core/db/session.py::get_session`'s `if tenant_id:` guard). A request that
omits that header hits `current_setting('app.company_id', true)` evaluating to `''` rather than a
real UUID, throwing `invalid input syntax for type uuid: ""` as a 500. Confirmed **pre-existing**
or unmodified `main` (reproduced identically via `git stash`), and confirmed **not customer-
facing** — `apps/web/src/lib/api/client.ts:51` always sends `X-Company-Id` on every authenticated
call, so the real product never hits this path; it only surfaces for a client (raw `curl`, a
future mobile client, an internal script) that omits the header. Worth a dedicated fix later:
`get_current_user` already decodes `company_id` from the JWT itself (line 25) and could set the
RLS GUC from that directly instead of depending on a second, client-supplied header for a value
the token already authoritatively carries.

## 14. Addendum — Phase 3 Implemented (2026-09-12)

**Shipped, code + migration, verified end-to-end over real HTTP:**
- `PasswordResetToken` model (`core/db/models/identity.py`) — same hash-only-storage, TTL-bound
  shape as `RefreshToken`/`account_invite`, no RLS (mirrors `refresh_token`'s own precedent).
- Migration `20260922090000_password_reset_token.py`.
- `IdentityRepository` gains `create_password_reset_token`/`get_password_reset_token_by_hash`/
  `mark_password_reset_token_used`/`update_user_password`.
- `IdentityService.forgot_password`/`reset_password` — always-200-shaped response regardless of
  whether the email matches an account (anti-enumeration); single-use, TTL-bound token; deliberately
  **no** `AuditService.record` call (that table's `company_id` is a real tenant FK — a password
  reset has no company context to attach one to correctly).
- `POST /auth/password/forgot` / `POST /auth/password/reset`, rate-limited on the same `auth`
  bucket as registration.

**Verified over real HTTP:** forgot → email logged with working reset link → reset → old password
rejected → new password accepts login → reusing the same reset token is rejected → forgot-password
for a non-existent email returns the identical 202 (no enumeration).

## 15. Addendum — Phase 4 Implemented, partial (2026-09-12)

**Shipped and verified in the browser (not just built):**
- `/accept-invite/[token]` — public page, resolves the invite, sets a password, auto-logs in via
  `applyTokenResponse`, redirects to `/app/dashboard`. Verified end-to-end in-browser: an invited
  `EMPLOYEE`-role user landed on the dashboard and correctly saw a permission-denied message for
  `DASHBOARD.COMPANY.VIEW` (proof the RBAC enforcement chain works through the real UI, not just
  the API).
- `/forgot-password` and `/reset-password/[token]` pages, plus a "Forgot password?" link added to
  `/login`.
- `GET /users` — a list endpoint the original plan didn't spec (needed once a real UI required
  showing who has access) — new `AccountInviteRepository.list_user_companies_for_company` +
  `AccountInviteService.list_users` + `UserSummary` schema.
- `/app/users` — a minimal Settings-style page: lists every user in the tenant with their roles,
  an "Invite user" dialog (`POST /users/invite`), and a "Manage roles" dialog per user (full
  replace via `PATCH /users/{id}/roles`), gated by `SETTINGS.USER.MANAGE`/`SETTINGS.ROLE.MANAGE`
  via the existing `usePermissions()` pattern — no new gating mechanism introduced. Added to
  `nav-items.ts`.
- An "Invite" button on the Employee detail page (`POST /employees/{id}/invite`), gated by
  `EMPLOYEE.INVITE`, handling the already-has-an-account (409) and missing-email (422) cases with
  toasts.
- Found and fixed one real bug while verifying in-browser: a `Badge` (renders a `<div>`) was
  nested inside a `<p>` on the Users page, causing a React hydration warning — moved the badge
  next to the name in a sibling `<div>` instead. Confirmed fixed via a fresh browser tab.

**Not built** (deferred, not required for the feature to be usable): a company-picker on the
login page for a user with multiple `UserCompany` memberships — the backend already supports and
returns the full list (`CompanySummary[]`), but no multi-company user exists yet to need the UI,
and every test performed here only ever had one membership.

## 16. Addendum — ESS Surface Implemented (2026-09-13)

**Shipped and verified in the browser:**
- `/app/me` — "My Profile". Reuses the exact same components the admin Employee detail page
  already uses (`EmployeeOverview`, `EmploymentPanel`, `AssignmentPanel`, `CompensationPanel`,
  `StatutoryPanel`, `BankingPanel`, `EmployeeAttendancePanel`) against `GET /employees/{id}` etc.
  with the caller's own `employee_id` (from `/auth/me`) — no new backend endpoints needed, since
  `SELF` scope enforcement was already built and proven (§4 F1, and the earlier `RBAC_DATA_SCOPE_
  DECISIONS.md` work). Tabs are filtered by the viewer's actual permissions (e.g. no Attendance
  tab without `ATTENDANCE.VIEW`, which `EMPLOYEE` doesn't hold — deliberately, Decision H). No
  admin action buttons (Edit/Deactivate/Confirm/Invite) — this is a read-only self-service view
  regardless of what the viewer might also be able to do to *other* employees.
- Post-login/accept-invite/registration landing is now permission-aware
  (`lib/auth/landing.ts::landingPathFor`): a user with `DASHBOARD.COMPANY.VIEW` still goes to
  `/app/dashboard`; a user without it but with an `employee_id` goes to `/app/me` instead of
  landing on a dashboard that immediately shows a permission error. `AuthContext.login`/
  `applyTokenResponse` now return the freshly-fetched `UserProfile` so callers can decide the
  redirect without depending on a stale hook closure.
- `/app/me` only appears in the sidebar when `user.employee_id` is set (`NavItem.requiresEmployeeId`,
  the first data-driven — not permission-code-driven — nav filter this list has needed).

**Verified end-to-end in-browser, full lifecycle:** admin creates an employee → invites them →
candidate accepts (sets password) → **lands directly on their own profile**, not the admin
dashboard → sees their own Overview/Compensation (correctly empty-state, not a permission error)
→ no console errors, no hydration warnings.

**Still not built:** dedicated My Attendance / My Leave pages as separate surfaces — Attendance is
reachable as a tab on `/app/me` when the viewer holds `ATTENDANCE.VIEW` (not granted to plain
`EMPLOYEE` today, so dormant until that permission is extended — a product decision, not a bug);
Leave has no self-service surface at all yet, admin or otherwise, so there's nothing to reuse the
way Attendance's existing components could be. The company-picker (above) and Phase 5 remain open.

## 17. Addendum — Phase 6 Implemented, partial (2026-09-13)

**Shipped:** a real, committed pytest suite — 19 tests, all passing — replacing the ad-hoc
verification scripts every earlier addendum relied on.

- `tests/integration/modules/account_invite/` (new module test directory, `conftest.py` mirrors
  `onboarding`'s own exactly) — `test_account_invite.py`, 13 tests: full issue→resolve→accept→
  login lifecycle with a permission-codes assertion against the `EMPLOYEE` role's exact grant set;
  permission-gating (403 without `EMPLOYEE.INVITE`); already-has-account (409); missing-email
  (422); reinvite-revokes-previous-token; unknown/expired token (404); weak password (422);
  second-admin invite via `POST /users/invite` with a permission-codes assertion for `HR_ADMIN`;
  already-in-company (409); role reassignment via `PATCH /users/{id}/roles` reflected in
  `GET /users`; self-role-change blocked (409); invalid role code (422).
- `tests/integration/auth/test_password_reset.py` — 6 tests: token issuance, anti-enumeration
  (identical response for a real vs. nonexistent email), full reset-then-login-with-new-password
  flow with single-use enforcement, unknown token (401), weak password (422), expired token (401).

**Two real bugs found and fixed while writing these — not the RLS/`X-Company-Id` issue, genuinely
new ones in this session's own test code:**
1. A monkeypatched fake `EmailSender.send` was missing its `self` parameter — since `send` is
   normally called as a bound instance method, the mismatched signature raised on every call, but
   the raise was silently swallowed by `forgot_password`'s own best-effort `except Exception:
   pass` around email delivery, making the test's captured-email list stay empty with no visible
   error until the assertion failed. Fixed by adding `self: object` as the first parameter.
2. `_teardown`'s cleanup ordering was wrong twice over: (a) deleting an invited user's `User` row
   before `_cleanup`'s own `UserCompany`/`UserRole` cleanup violated `user_company_user_id_fkey`;
   (b) even after fixing that, the invited user's `refresh_token`/`session` rows (created by the
   accept-flow's auto-login) still referenced `company_id`, blocking `_cleanup`'s later `Company`
   delete via `refresh_token_company_id_fkey`. Fixed by splitting into three explicitly-ordered
   phases: delete the extra user's sessions/refresh-tokens first, run the existing company-wide
   `_cleanup`, then delete the extra user's own `User` row last.

**Confirmed environment-testing detail, not a code bug:** these tests only pass when the shell's
`DATABASE_URL`/`MIGRATIONS_DATABASE_URL` are *unset* (`env -u DATABASE_URL -u
MIGRATIONS_DATABASE_URL pytest ...`), letting `tests/conftest.py`'s own default
(`postgresql://hrms:...`, the schema-owner role that bypasses RLS) take effect. Exporting `.env`
into the shell first — an easy mistake, made twice earlier in this same session — overrides that
default with the app's own RLS-enforced `hrms_app` role, which breaks even the pre-existing demo
seed's own `clear_b1_seed` (RLS silently hides rows outside the current tenant context, so its
deletes affect zero rows and violate FKs downstream). Not a new finding — this is the same root
cause as task_60c1fff1 — but worth restating here since it determines whether this specific suite
appears to pass or fail.

**Not done:** a formal Phase 5 hardening review, and broader regression coverage beyond this
module (the pre-existing suite's own flakiness under RLS/connection-pool state, tracked
separately, was not investigated further here).

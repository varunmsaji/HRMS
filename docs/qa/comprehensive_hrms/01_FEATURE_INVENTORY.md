# 01 — Feature inventory

Inspected on 2026-10-26 from the tree at `436a2e5`, plus uncommitted work that was already present. Status describes the code, not a test run. Every case in this folder is `NOT_RUN`.

| Module | Feature | User roles | UI location | API / service | Data models | Dependencies | Current status | Existing tests | Known defects | Testability |
|---|---|---|---|---|---|---|---|---|---|---|
| Identity | Register company, verify email, login, logout, forgot and reset password | Anonymous, then founder | `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password` | identity auth router | user, session, company membership | captured mail | Implemented | Live AUTH checks, 2026-10-25 | None open from that run | Ready |
| Identity | Lockout | Anonymous | Login | rate limit | failed-attempt counter | Redis | Implemented | AUTH 429 in the live register | None open | Ready |
| Organisation | Branches, departments, designations, legal entities, work calendar, holidays | Company admin. HR is denied by the default grants | `/app` organisation pages | organisation router | branch, department, designation, calendar | tenant | Implemented | Partial API coverage | Nav is not permission-filtered (G-W1) | Ready |
| Organisation | Custom roles and a permission editor | Company admin | none | none | role, role_permission | — | Missing. Five roles are seeded | — | No editor | Blocked. BR-09 |
| Organisation | Department and legal-entity data scopes | — | — | — | data_scope enum | — | Deferred in the RBAC decision record | — | DEPARTMENT scope not implemented | Needs a decision |
| Employee | Create, profile, org placement, manager | HR admin, scoped managers read | `/app` employees | employee service | employee, employment span | org masters | Implemented | EMP checks in the live register | Double-submit without an idempotency key may create two rows. EMP-003 will measure it | Ready |
| Employee | Probation, confirmation, termination, rehire | HR admin | employee profile | employee lifecycle | status, dates | auth | Partial. G-E1: `ON_NOTICE` and `EXITED` look unused. Rehire is not confirmed as its own operation | Limited | G-E1 | Ready for terminate. Rehire may block |
| Onboarding | Case, invitation, public token, activation | HR, candidate | onboarding pages and `/onboarding/[token]` | onboarding service | case, token | captured mail | Implemented. Cancel permission is unused (G-ON1). Activation does not copy grade, manager, shift, or salary | ONB tests exist | G-ON1 | Ready, except cancel |
| Attendance | Punch in and out, day view, team view | Employee self, manager tree, HR view | attendance pages | attendance service | punch, day | shift, calendar | Implemented for the default employee grants in current `register_company` | ATT checks, 13 pass and ATT-15 fail | K-1 / ATT-15. Older gap G-A1 is stale against this code | Ready |
| Attendance | Shifts, rosters, policies, period lock | Company admin for lock and policy | attendance policy, periods, rosters | attendance admin | policy, period, shift | payroll finalise | Partial. G-A2: several policy fields are stored and not evaluated | Policy API tests | G-A2, BR-04 | Ready for lock. Late and grace need the engine check |
| Attendance | Regularisation and overtime approval | Employee request, manager approve | regularisation pages | attendance service | request | punch | Implemented | API tests | None from the live register | Ready |
| Attendance | Face punch | Employee | mobile / experimental API | opensource face engine | face embedding | camera models | Experimental, not a production control | New unit tests in the dirty tree, not executed here | Not production-ready | Blocked for this programme |
| Leave | Types, policies, versions, combination rules, statutory minimums | Company admin writes. HR reads and operates applications | leave settings pages | leave service | type, policy version | calendar | Implemented | Large LV set in the live register | Doc conflicts in the gap register | Ready |
| Leave | Apply, approve, reject, cancel | Employee, snapshotted manager, HR | leave applications | leave service, approval chain | application, day, action, ledger | calendar, employee manager | Implemented. Statuses: SUBMITTED, APPROVED, REJECTED, CANCELLED | LV checks mostly pass. LV-28 was INFO | None open as a counted functional fail | Ready |
| Leave | Balances, adjustments, accrual, year-end, encashment, comp-off | HR adjust. Employee reads own | balances | ledger, accrual, comp-off | ledger | jobs | Partial. Accrual window is narrow. Encashment payroll comment disagrees with the query (BR-03) | Service tests | G-L3, G-L4 | Ready, with the open rules |
| Leave | Reassign approver | HR | no web page | reassign API | application | — | API only | Unknown | No UI | API only |
| Payroll | Components, structures, statutory rates | HR setup. Admin for some rates | payroll settings | payroll service | component, structure, rate | employee | Implemented. Statutory self-verify is weak. TDS is limited | PAY checks | G-PAY notes in the gap register | Ready |
| Payroll | Compute, approve, finalise, mark paid, payslip, bank advice | HR computes. A different user with RUN_APPROVE approves, finalises, and marks paid. Admin downloads advice | pay runs, payslips | payroll service | pay run, line, payslip | attendance, leave | Implemented. One permission covers approve, finalise, and mark paid | PAY checks | G-PAY4 segregation inside that permission | Ready |
| Documents | Upload, download | Employee own, HR where granted | employee documents panel | storage | document metadata, object | bucket | Implemented | DOC checks | Storage failure path unproven in UI | Ready in a disposable bucket |
| Platform | Health, metrics, email log, employee CSV import | Admin / HR for import | platform emails page. Import has no employee UI | platform and import routers | email log, import batch | worker | Import is API-only. Email log is a platform page | DEF-03 fixed | No import UI | API for import |
| Notifications | In-app inbox | — | — | — | — | — | Missing | — | No product | Do not invent cases |
| Recruitment, loans, F&F, reimbursements | — | — | — | — | — | — | Missing | — | Gap register | Out of scope |
| Mobile | Same employee journeys | Employee | Flutter screens | same API | — | Flutter SDK | UI present in the tree. SDK was absent on the last QA host | Widget tests in the tree, not run here | SDK missing | Blocked on this host |
| Web shell | Dashboard, settings | All signed-in roles | `/app` | various | — | — | Implemented. Menu is not filtered by permission | Web unit tests | G-W1 | Ready |

## Routes inspected

Web: login, register, verify email, forgot and reset password, accept invite, public onboarding token, platform shell, and the `apps/web/src/app` pages for employees, organisation, attendance, leave, payroll, onboarding, company, users, and setup. About 81 `page.tsx` files exist under the app router.

API routers: identity, platform, organisation, employee, employee import, attendance, leave, payroll, onboarding, account invite, health, metrics.

## Not claimed

Face attendance, recruitment, in-app notifications, a role editor, an audit-log viewer, payment initiation, and SMS are not features of this catalogue. Cases that would need them are omitted on purpose.

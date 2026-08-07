# Version 1 Roadmap — Core HR Operations

**Document type:** Master product roadmap for Version 1 delivery.
**Status:** Approved product decision — binding on all future development sessions (human or AI) until superseded by a new Change Request.
**Date:** 2026-08-04
**Owner:** Product (CPO) / Program (TPM)
**Relationship to other documents:** This document governs **what ships in V1 and in what order**. It does not replace the underlying specifications:

| For… | Still go to |
|---|---|
| Functional requirements, acceptance criteria | `docs/product/17_SRS_Phase1_Core_Modules.md`, `docs/product/18_SRS_Phase2_Phase3_Modules.md` |
| Data model | `docs/product/08_Database_Architecture.md` |
| API contracts | `docs/product/09_API_Standards.md` |
| Backend/module structure | `docs/product/06_Folder_Structure.md`, `docs/product/07_Backend_Architecture.md`, `docs/architecture/` |
| RBAC/permissions | `docs/product/19_RBAC_and_Permission_Matrix.md` |
| Design system, screens | `docs/product/24_UIUX_Screen_Inventory_and_Design_System.md`, `docs/design/` |
| Testing approach | `docs/product/15_Testing_Strategy.md` |
| Effort-estimation method, team structure, Definition of Done | `docs/product/25_Project_Plan_Estimation_and_Team.md` |
| Risk register, change control process | `docs/product/26_Risk_Register_Open_Questions_and_Change_Control.md` |

**This document supersedes `docs/product/25_Project_Plan_Estimation_and_Team.md` §2–§3 (phase plan and block/sprint sequencing) for Version 1 purposes.** Document 25's estimation methodology, team structure, Definition of Ready/Done, communication plan and risk mitigations (§4–§10) remain valid and should be read alongside this roadmap, not replaced by it. Documents 00, 02, 17, 18 and 25 still describe Recruitment as Phase 1 in their body text — that is now stale and should be corrected in a follow-up documentation pass (§18 of this document); this roadmap is the authority in the meantime.

No code, schema, or UI is generated in this document. This is planning only.

---

## 1. Executive Summary

**The decision:** Recruitment (ATS) — job requisitions, career portal, candidate portal, resume parsing, AI resume screening, candidate ranking, interview scheduling, interview feedback, and offer management — is **removed from Version 1** and moves to **Version 2**. Onboarding automation that is specifically triggered by candidate-to-employee conversion moves with it. **Recruitment remains part of the product vision.** Nothing about it is cancelled; only its release position changes.

**Why this matters for sequencing:** Recruitment was previously Phase 1's second-largest module by effort (`docs/product/25` §4.1: 71 AI-adjusted person-days) and its own ~12-week build block (`docs/product/25` §3, Block B9). Document 25 §8 had already identified "Recruitment module → Phase 2" as the single largest non-destructive scope-reduction lever available (**≈12 weeks saved**), while flagging the cost: "ATS is a strong differentiator; HR can use spreadsheets short-term." This roadmap exercises that lever formally, as a strategic decision rather than a schedule-pressure cut.

**What Version 1 is now:** a company can register, configure its organization, add employees (manually or by import), run attendance, run leave, run payroll end to end including statutory outputs, give employees self-service access, and report on all of it — **without needing to hire anyone through the product**. Companies onboard their existing workforce on day one; recruiting new hires elsewhere and adding them as employees is a fully supported (if manual) V1 workflow.

**Net effect on the plan:**
- **Module count (Phase 1 SRS):** 15 functional areas → 12 (Recruitment, and the candidate-linked slice of Onboarding, removed; everything else unchanged in substance).
- **Screen count (`docs/product/24` §3):** ~185 screens → **~159 screens** (Recruitment's 26 screens removed in full; the 18-screen Onboarding & Exit group reduces to the exit-side workflows only, ~9 screens — see §5).
- **Timeline to stable V1 go-live:** **≈110 weeks (≈25 months)**, down from the original ≈123-week Phase 1 estimate — a **13-week reduction**, consistent with `docs/product/25` §8's own estimate for cutting Recruitment (≈12 weeks) plus a smaller trim from deferring the visual workflow builder (§4) and the candidate-linked portion of onboarding (§5, §14).
- **Effort (`docs/product/25` §4.1 method):** the AI-adjusted module subtotal drops from 984 to **≈900–915 person-days** (Recruitment's 71 days removed in full; Onboarding's 33 days reduced to roughly half, since manual-employee onboarding checklists stay in scope but candidate pre-boarding automation does not).

**Current build status (as of this document):** Foundation (Sprint 1 below) and Auth/RBAC/multi-tenancy (Sprint 2) are **already delivered** — see `docs/SPRINT0_FOUNDATION.md` and `docs/SPRINT_B1_IDENTITY.md`. This roadmap starts active planning at **Sprint 3**.

---

## 2. Product Scope

Version 1 scope, grouped exactly as directed by the product decision:

| Group | Modules |
|---|---|
| **Platform Foundation** | Authentication · Multi-company · RBAC · Company Setup · Organization Setup · Audit Logs · Notifications |
| **Organization** | Company · Branches · Departments · Designations · Employment Types · Work Locations · Holiday Calendar · Shifts · Leave Policies · Payroll Policies |
| **Employee Management** | Employee Directory · Employee 360 · Employee Documents · Employment Information · Reporting Structure · Employee Timeline · Employee Import |
| **Attendance** | Attendance · Shift Management · Attendance Corrections · Overtime · Attendance Reports |
| **Leave** | Leave Types · Leave Requests · Leave Approval · Leave Calendar · Leave Balance |
| **Payroll** | Salary Components · Payroll Processing · Payslips · Loans · Reimbursements · Bonus · Statutory Components · Payroll Reports |
| **Employee Self Service** | Dashboard · Profile · Attendance · Leave · Payslips · Documents · Announcements |
| **Reports** | Employee Reports · Attendance Reports · Leave Reports · Payroll Reports · Executive Dashboard |
| **Settings** | Company Settings · Roles · Permissions · Notification Settings · Email Settings · Audit Logs |

This is a strict subset of the original Phase 1 scope in `docs/product/02_PRD.md` §5.1. Every item above already has a detailed functional specification in `docs/product/17_SRS_Phase1_Core_Modules.md` — this roadmap does not re-derive requirements, only re-sequences them.

**Two scope clarifications not explicit in the source instruction, made as planning judgment calls (flagged for product sign-off, not blocking):**

1. **Approval routing is retained as foundational infrastructure; the visual workflow *builder* is deferred to V3.** Leave requests, attendance regularisation, and payroll sign-off cannot function without *some* approval mechanism (`docs/product/02` BR-02, BR-03; `docs/product/17` §15, tagged P1-foundation in the original spec). What moves to V3 per the product decision is the drag-and-drop **Workflow Builder** — the visual configurator for arbitrary custom workflows. V1 ships a simpler, fixed approval chain (requester → manager → HR-if-over-threshold, per `docs/product/20_Workflow_Approval_Notification_Engine.md`'s default routing) without the builder UI. See §5.
2. **A minimal Employee Exit is retained in V1, without ATS-linked onboarding automation.** The instruction's V1 list has no explicit "Exit" module, and V2's list moves "Onboarding Automation" out as part of Recruitment. But employees leaving a company is a Core HR fact independent of how they were hired, and Payroll's Full & Final settlement (`docs/product/17` FR-PAY-022) and Employee status state machine (FR-EMP-014, states include `EXITED`) both require it. V1 therefore includes **resignation, clearance, F&F settlement, and access revocation** (the exit-side of `docs/product/17` §10), but **not** the candidate pre-boarding portal or onboarding task-pack automation tied to ATS conversion (`docs/product/17` §9), which is genuinely Recruitment-dependent and stays out. See §4 and §5 for the exact boundary.

---

## 3. Version 1 Goals

Restating the mandate as testable outcomes, mapped to the original business objectives in `docs/product/02_PRD.md` §1 (O3, time-to-hire, is the only original objective that does not apply — it is Recruitment-specific and moves to V2's success criteria):

| Goal | What "done" looks like | Source objective |
|---|---|---|
| G1 — Register & configure | A new tenant completes company registration, legal entity, branch, department, designation and payroll-cycle setup without support intervention | `docs/product/02` O1 |
| G2 — Add employees | HR adds employees manually or via bulk import (≤5,000 rows/file, dry-run validated) with zero re-typing between org setup and employee record | `docs/product/17` FR-EMP-001–006 |
| G3 — Manage attendance | Punches capture from biometric device, mobile GPS and web; a status-resolution engine produces one attendance day per employee per date; regularisation and OT work end to end | `docs/product/02` O1, O7 |
| G4 — Manage leave | Leave balance is ledger-derived and explainable; application → approval → attendance recompute happens with zero HR touch for the standard case | `docs/product/02` O1, O4 |
| G5 — Process payroll | A full pay run — components, statutory deductions, TDS, F&F — closes for 500 employees in under 4 hours with a mandatory variance gate before finalisation | `docs/product/02` O2, O4, O6 |
| G6 — Self-service | ≥80% of routine employee interactions (punch, leave, payslip, profile) happen without HR involvement, on mobile and web | `docs/product/02` O5 |
| G7 — Report | Standard report library (attendance, leave, payroll, employee, compliance calendar) covers day-to-day and audit needs without a report-builder dependency | `docs/product/02` §5.1 |
| G8 — Operate daily HR without Recruitment | Every one of G1–G7 is independently completable with the ATS module fully absent — no hidden coupling to Recruitment anywhere in Org, Employee, Attendance, Leave, Payroll, ESS or Reports | This document, §1 |
| G9 — Reliability & compliance carried over unchanged | 99.9% uptime, payroll never fails silently, 100% on-time zero-defect statutory filings | `docs/product/02` O6, O7 |

**Acceptance test for G8 specifically:** before this roadmap is considered satisfied, run a full "buy → register → configure → add 50 employees by import → run attendance for a month → run leave → run payroll → view reports" walkthrough with the Recruitment module's feature flag (`docs/product/17` FR-PLT-008) switched off, and confirm nothing blocks, 404s, or silently depends on candidate/requisition data existing.

---

## 4. Out of Scope

### 4.1 Deferred to Version 2

| Module | Items |
|---|---|
| Recruitment | Job Requisitions · Career Portal · Candidate Portal · Resume Parsing · AI Resume Screening · Candidate Ranking · Interview Scheduling · Interview Feedback · Offer Management · Onboarding Automation |

Full functional detail for these already exists in `docs/product/17_SRS_Phase1_Core_Modules.md` §8 (FR-REC-001–018) and §9 (FR-ONB-001–010) — nothing needs to be rewritten, only re-tagged from Phase 1 to Phase 2 (see §18). The **Offer letter** template (one of the 12 in FR-EMP-016) moves with Offer Management since it is generated from offer data, not employee data. **Referral programme** (FR-REC-015) moves with Recruitment since it is a candidate-sourcing mechanism.

### 4.2 Deferred to Version 3

Per the product decision, unchanged from the original Phase 2/3 grouping in `docs/product/18_SRS_Phase2_Phase3_Modules.md`, plus the Workflow Builder pulled forward into this list explicitly:

Performance Management · Learning Management (LMS) · Asset Management · Expense Management · Visitor Management · HR Helpdesk · **Workflow Builder** (visual configurator — the underlying approval-routing *engine* stays in V1, see §2) · Advanced AI (attrition prediction, attendance anomaly detection, payroll validation AI, AI helpdesk assistant) · Predictive Analytics.

Also carried forward unchanged from `docs/product/18` §4, since nothing in the product decision touches them: Employee Experience (surveys, recognition), Task & Checklist as a generic cross-module entity, and Communication/Announcements as a *standalone broadcast module* — note V1's ESS **Announcements** screen is a read-only display of company announcements (a thin slice needed for G6), not the full Communication module (FR-COM-001–005) with scheduling, targeting and WhatsApp broadcast, which stays in V2 per `docs/product/18` §3.

### 4.3 Already out of scope for the whole product (unchanged, `docs/product/02` §5.4)

Full accounting/GL system · job-board posting purchase · background-verification execution · statutory e-filing submission to government portals · insurance/benefits brokerage · native desktop apps · legacy data migration (separately quotable).

---

## 5. Module Breakdown

| # | Module | Group | Core capability | Primary spec reference | Build status |
|---|---|---|---|---|---|
| 1 | Authentication | Platform Foundation | Email/password, mobile OTP, MFA, JWT + refresh rotation | `docs/product/17` §1 | ✅ Delivered (Sprint 2 / `docs/SPRINT_B1_IDENTITY.md`) |
| 2 | Multi-company | Platform Foundation | User↔company membership, company switcher, tenant isolation via RLS | `docs/product/17` §1, `docs/product/08` §3 | ✅ Delivered |
| 3 | RBAC (core engine) | Platform Foundation | Permission ∧ data-scope ∧ field-mask resolution | `docs/product/19` §1–2 | ✅ Delivered (engine); ⏳ full permission catalogue grows with each module |
| 4 | Company Setup | Platform Foundation | Registration wizard, industry template seeding | `docs/product/17` §3.2, FR-ORG-001–002 | ⏳ Not started |
| 5 | Audit Logs | Platform Foundation | Append-only change log, sensitive-field read log | `docs/product/17` §16 | 🔶 Foundation only (`audit_log` table + `AuditService`, per B1) |
| 6 | Notifications (engine) | Platform Foundation | In-app/email/push channels, template + event catalogue | `docs/product/17` §13 | ⏳ Not started |
| 7 | Approval routing (core, no builder) | Platform Foundation | Fixed approval chains for Leave/Regularisation/Payroll sign-off; delegation, SLA escalation | `docs/product/17` §15, `docs/product/20` | ⏳ Not started — **scope-reduced**, see §2 note 1 |
| 8 | Company / Legal Entity | Organization | Registered entity, PF/ESI/TAN/PAN/GST | `docs/product/17` FR-ORG-003 | ⏳ Not started |
| 9 | Branches / Work Locations | Organization | Address, state (PT/holiday driver), geofence | `docs/product/17` FR-ORG-004 | ⏳ Not started |
| 10 | Departments | Organization | Hierarchy, cost centre, cycle-free tree | `docs/product/17` FR-ORG-005 | ⏳ Not started |
| 11 | Designations & Grades | Organization | Title, band, career path, override chain anchor | `docs/product/17` FR-ORG-006–007 | ⏳ Not started |
| 12 | Employment Types | Organization | Permanent/Contract/Intern etc., statutory applicability flags | `docs/product/17` FR-ORG-010 | ⏳ Not started |
| 13 | Holiday Calendar | Organization | Per-branch/state, fixed/optional/restricted | `docs/product/17` FR-ORG-008 | ⏳ Not started |
| 14 | Shifts | Organization / Attendance | Shift master, flexible/split/cross-midnight | `docs/product/17` §5.3 FR-ATT-001–004 | ⏳ Not started |
| 15 | Leave Policies | Organization / Leave | Accrual, carry-forward, encashment rules | `docs/product/17` FR-LEV-001 | ⏳ Not started |
| 16 | Payroll Policies | Organization / Payroll | Pay cycle, cut-off, pay-date rule | `docs/product/17` FR-ORG-009 | ⏳ Not started |
| 17 | Employee Directory | Employee Management | Search/filter, table + card view | `docs/product/17` FR-EMP-008 | ⏳ Not started |
| 18 | Employee 360 | Employee Management | Tabbed profile (Profile/Job/Compensation/Attendance/Leave/Documents/Timeline) | `docs/product/17` FR-EMP-017 | ⏳ Not started |
| 19 | Employee Documents | Employee Management | Type-wise upload, expiry alerts, verification, virus scan | `docs/product/17` FR-EMP-007 | ⏳ Not started |
| 20 | Employment Information | Employee Management | Effective-dated employment/assignment/compensation | `docs/product/17` §4.1, FR-EMP-003–005 | ⏳ Not started |
| 21 | Reporting Structure | Employee Management | Manager chain, org chart, reassignment on manager change | `docs/product/17` FR-EMP-013, FR-ORG-013 | ⏳ Not started |
| 22 | Employee Timeline | Employee Management | Unified event feed per employee | `docs/product/17` §4.1, `docs/product/08` §5 | ⏳ Not started |
| 23 | Employee Import | Employee Management | Bulk Excel import, dry-run, all-or-nothing | `docs/product/17` FR-EMP-006 | ⏳ Not started |
| 24 | Transfer / Promotion / Confirmation | Employee Management | Lifecycle workflows on top of #20 | `docs/product/17` FR-EMP-010–012 | ⏳ Not started |
| 25 | Letters (non-offer) | Employee Management | Appointment, confirmation, promotion, transfer, increment, warning, experience, relieving, NOC, address proof, salary certificate (11 of the original 12 — **offer letter excluded**, see §4.1) | `docs/product/17` FR-EMP-016 | ⏳ Not started |
| 26 | Employee Exit & F&F | Employee Management | Resignation, clearance checklist, F&F settlement, exit docs, access revocation | `docs/product/17` §10 (FR-EXT-001–005, 008–010; **excludes** FR-EXT-006 KT/replacement-mapping detail and rehire-flag-to-ATS FR-EXT-012, which lean on Recruitment) | ⏳ Not started |
| 27 | Attendance capture | Attendance | Punch API (biometric/mobile/web/kiosk), offline sync, geofence, device mgmt | `docs/product/17` §5.2–5.3 | ⏳ Not started |
| 28 | Attendance processing | Attendance | Status-resolution engine, matrix UI, recompute-on-change | `docs/product/17` FR-ATT-006, 013, 019 | ⏳ Not started |
| 29 | Attendance Corrections | Attendance | Regularisation request/approval | `docs/product/17` FR-ATT-010 | ⏳ Not started |
| 30 | Overtime | Attendance | Eligibility, caps, multipliers, comp-off | `docs/product/17` FR-ATT-008–009 | ⏳ Not started |
| 31 | Attendance Reports | Attendance / Reports | Monthly summary, register, muster roll | `docs/product/17` FR-ATT-018, §12 | ⏳ Not started |
| 32 | Leave Types | Leave | Type master, seeded Indian types | `docs/product/17` FR-LEV-001–002 | ⏳ Not started |
| 33 | Leave Requests | Leave | Application, day-count preview, overlap prevention | `docs/product/17` FR-LEV-005–006 | ⏳ Not started |
| 34 | Leave Approval | Leave | Routed via #7, cancellation/withdrawal | `docs/product/17` FR-LEV-007–008 | ⏳ Not started |
| 35 | Leave Calendar | Leave | Team calendar, conflict view | `docs/product/17` FR-LEV-009 | ⏳ Not started |
| 36 | Leave Balance | Leave | Append-only ledger, statement, year-end processing | `docs/product/17` §6.1, FR-LEV-012–013 | ⏳ Not started |
| 37 | Salary Components | Payroll | Component master, formula builder | `docs/product/17` FR-PAY-001–002 | ⏳ Not started |
| 38 | Payroll Processing | Payroll | Pay run lifecycle, computation engine, LOP/arrears | `docs/product/17` §7.1, FR-PAY-007–010 | ⏳ Not started |
| 39 | Payslips | Payroll | PDF generation, publish to ESS | `docs/product/17` FR-PAY-017 | ⏳ Not started |
| 40 | Loans | Payroll | Request → disbursement → EMI → foreclosure | `docs/product/17` FR-PAY-012 | ⏳ Not started |
| 41 | Reimbursements | Payroll | Claim → approval → pay via payroll | `docs/product/17` FR-PAY-013 | ⏳ Not started |
| 42 | Bonus | Payroll | Off-cycle run, Bonus Act ceiling handling | `docs/product/17` FR-PAY-016, FR-PAY-019 | ⏳ Not started |
| 43 | Statutory Components | Payroll | PF/ESI/PT/TDS/LWF/gratuity master, employee statutory profile, TDS engine | `docs/product/17` FR-PAY-005–006, 011 | ⏳ Not started |
| 44 | Payroll Reports | Payroll / Reports | Register, salary sheet, statutory outputs, JV | `docs/product/17` FR-PAY-019–021 | ⏳ Not started |
| 45 | ESS Dashboard | Employee Self Service | Today's status, balances, quick actions | `docs/product/17` FR-ESS-001 | ⏳ Not started |
| 46 | ESS Profile | Employee Self Service | View/edit-with-approval | `docs/product/17` FR-ESS-006 | ⏳ Not started |
| 47 | ESS Attendance | Employee Self Service | Punch, calendar, regularisation request | `docs/product/17` FR-ESS-002, 004 | ⏳ Not started |
| 48 | ESS Leave | Employee Self Service | Apply/cancel, balance, team calendar | `docs/product/17` FR-ESS-003 | ⏳ Not started |
| 49 | ESS Payslips | Employee Self Service | Last 24 months, Form 16, tax proof submission | `docs/product/17` FR-ESS-005 | ⏳ Not started |
| 50 | ESS Documents | Employee Self Service | Upload, dependent/nominee mgmt | `docs/product/17` FR-ESS-006 | ⏳ Not started |
| 51 | ESS Announcements | Employee Self Service | Read-only display (thin slice — see §4.2) | `docs/product/17` FR-ESS-001 | ⏳ Not started |
| 52 | Employee Reports | Reports | Headcount, movement, directory export | `docs/product/17` FR-RPT-002 | ⏳ Not started |
| 53 | Attendance Reports | Reports | Register, late/early, OT register | `docs/product/17` FR-RPT-002 | ⏳ Not started |
| 54 | Leave Reports | Reports | Balance & ledger reports | `docs/product/17` FR-RPT-002 | ⏳ Not started |
| 55 | Payroll Reports | Reports | Statutory, cost-centre, compliance calendar | `docs/product/17` FR-RPT-002, 006 | ⏳ Not started |
| 56 | Executive Dashboard | Reports | Company Admin: headcount, cost, automation rate | `docs/product/17` FR-RPT-001 | ⏳ Not started |
| 57 | Company Settings | Settings | Branding, financial year, numbering series | `docs/product/17` FR-ORG-001, 011 | ⏳ Not started |
| 58 | Roles & Permissions (UI) | Settings | Role editor, permission matrix, access review | `docs/product/19` §1–4 | ⏳ Not started |
| 59 | Notification Settings | Settings | Per-category channel preferences, quiet hours | `docs/product/17` FR-NTF-004, 007 | ⏳ Not started |
| 60 | Email Settings | Settings | Sender domain, template preview | `docs/product/17` FR-NTF-002 | ⏳ Not started |
| 61 | Audit Logs (UI) | Settings | Viewer, per-entity/per-user query, export | `docs/product/17` FR-AUD-002 | ⏳ Not started |

**61 modules**, down from Phase 1's original ~75 (net of Recruitment's 18 items and Onboarding's candidate-linked half). This table is the definitive V1 module list — the Sprint Breakdown (§14) sequences exactly these rows and no others.

---

## 6. Module Dependencies

```
Platform Foundation (Auth · Multi-company · RBAC engine · Audit foundation)
  │  [DELIVERED]
  ▼
Company Setup + Organization
  (Legal Entity → Branch → Department → Designation/Grade → Employment Type → Holiday Calendar)
  │
  ├──▶ Shifts ───────────────────────────────────────────────┐
  ├──▶ Leave Policies ─────────────────────────────┐          │
  ├──▶ Payroll Policies ──────────────────┐        │          │
  │                                       │        │          │
  ▼                                       │        │          │
Employee Management                       │        │          │
  (Directory → 360 → Documents →          │        │          │
   Employment Info → Reporting Structure) │        │          │
  │                                       │        │          │
  ├──▶ Approval routing (core) ───────────┼────────┼──────────┼───▶ needed by every approval-bearing
  │                                       │        │          │     flow below (Leave, Regularisation,
  ├──▶ Notification engine ───────────────┼────────┼──────────┼───▶ Payroll sign-off, Profile change)
  │                                       │        │          │
  │                                       ▼        ▼          ▼
  │                                     Leave    Payroll    Attendance
  │                                   (Types→   (Components→ (Shift→Punch→
  │                                    Ledger→   Structures→  Status resolve→
  │                                    Apply)    Statutory→   Regularise→OT)
  │                                       │       Run engine)      │
  │                                       │           ▲            │
  │                                       └───────────┼────────────┘
  │                                        (LOP, attendance summary,
  │                                         leave-approved recompute
  │                                         all feed the pay run)
  │                                                   │
  ├──▶ Employee Exit & F&F  ─────────────────────────▶│ (F&F is a payroll computation)
  │                                                   │
  ▼                                                   ▼
Employee Self Service ◀────────────────── depends on Attendance, Leave, Payroll,
  (punch, apply, view payslip)             Documents, Notifications all being live
  │
  ▼
Reports ◀── depends on Employee, Attendance, Leave, Payroll data existing to report on

Settings — cross-cutting configuration surface over all of the above; grows incrementally
           with each module rather than shipping as one block
```

**Hard sequencing constraints** (cannot be reordered without breaking the dependency):
1. RBAC engine and multi-tenancy must exist before *any* business module — already satisfied.
2. Organization (branch → state → PT slab; department → cost centre) must exist before Employee Management, because employee creation requires a valid branch/department/designation.
3. Employee Management must exist before Attendance, Leave, or Payroll — all three key off `employee_id` and effective-dated assignment/compensation.
4. Approval routing (core) must exist before Leave Approval and Attendance Corrections ship, since both are approval-bearing by requirement (BR-02, BR-03).
5. Attendance **and** Leave must both be live before Payroll processing, because pay-days computation consumes the attendance summary and LOP from leave (`docs/product/17` FR-PAY-008, FR-LEV-014).
6. Payroll must exist before Employee Exit & F&F can compute a real settlement.
7. ESS is a read/write veneer over Attendance, Leave, Payroll and Documents — it cannot usefully ship ahead of them, only alongside or after.
8. Reports can begin against partial data (e.g., Employee Reports as soon as Employee Management ships) but the Executive Dashboard and Payroll Reports need Payroll live.

---

## 7. Recommended Development Order

High-level pass, elaborated into sprints in §14:

1. **Foundation** — already done.
2. **Organization Setup** — the configuration substrate everything else is keyed against.
3. **Employee Management** — the central entity every other module references.
4. **Approval routing (core) + Notification engine** — thin, foundational, needed before Leave/Attendance approvals exist; cheaper to build once, early, than to retrofit into three modules later.
5. **Attendance** (Shifts → capture → processing → corrections/OT) — highest complexity after Payroll; start it while Payroll's design is still being finalised so device-integration risk surfaces early (`docs/product/26` risk: biometric integration takes 3× estimate).
6. **Leave** — depends on Organization (policies) and Employee; feeds into and is fed by Attendance.
7. **Payroll** — the largest, highest-risk block; must come after Attendance and Leave are stable, since it consumes their output as input.
8. **Employee Exit & F&F** — thin slice, but depends on Payroll for the settlement calculation.
9. **Employee Self Service (+ mobile)** — a consumption layer over 2–8; sequenced late so it has real data to display.
10. **Reports & Executive Dashboard** — sequenced last among build work because it depends on every other module having real data flowing through it.
11. **Hardening → UAT (with parallel payroll runs) → Go-live.**

This order matches `docs/product/25` §3's original block sequencing exactly for every module that survives into V1 — the only structural changes are removing the Recruitment block entirely and moving what remains of Onboarding/Exit to immediately follow Payroll instead of following Recruitment.

---

## 8. Backend Development Order

Ordered by module dependency (§6), each following the layered architecture and module-boundary rules in `docs/product/07_Backend_Architecture.md` and `docs/architecture/02_Module_Standard.md`:

1. `core/` extensions as needed (already scaffolded: `auth`, `rbac`, `tenancy`, `audit`, `db`)
2. `modules/organization/` — company, legal entity, branch, department, designation, grade, employment type, holiday calendar, work location
3. `modules/employee/` — directory, 360 read model, documents, employment/assignment/compensation history, import
4. `modules/workflow/` — approval routing core (definitions, approver resolution, escalation) — no builder persistence layer needed yet, just the execution engine
5. `modules/notification/` — channel adapters, template resolution, event bus consumers
6. `modules/attendance/` — shift master → punch ingestion → status resolution service → regularisation/OT
7. `modules/leave/` — leave type/policy → ledger service → application service (calls into workflow + attendance recompute)
8. `modules/payroll/` — component/structure/statutory master → pay run engine → outputs (payslip, bank file, statutory file, JV)
9. `modules/exit/` — resignation → clearance → F&F (calls into payroll for settlement computation)
10. `modules/ess/` — thin composition layer; mostly re-exposes existing module services under an employee-scoped surface
11. `modules/reports/` — read-side, ideally against a replica per `docs/product/17` FR-RPT-008
12. `modules/settings/` — incremental; each module above registers its own settings surface as it ships rather than being one monolithic module

Each module ships with its own migrations, service/repository layers, RBAC permission registrations, and audit hooks per `docs/product/05_Development_Standards.md` — sequencing here is about *order*, not process, which is unchanged from Document 05/07.

---

## 9. Frontend Development Order

Mirrors the backend order (§8) with one adjustment: frontend work for a module starts once that module's API contract is stable, not once it's fully backend-complete, per the contractor engagement model in `docs/product/25` §5.3.

1. Company registration wizard + setup checklist (already partially covered by Auth screens)
2. Organization settings screens (branch, department, designation, grade, holiday calendar) — desktop-first, dense tables per `docs/product/24` D1
3. Employee directory, 360 profile, add-employee wizard, bulk import flow
4. Unified approval inbox (thin — one card type, expands as Leave/Attendance/Payroll approvals come online) + notification inbox/preferences
5. Shift setup, attendance matrix, regularisation, OT screens
6. Leave application, balance statement, team calendar, leave admin screens
7. Payroll: the largest frontend surface — pay run wizard, salary component/structure builder, statutory setup, payslip, tax screens (`docs/product/24` §4.4 gives the pay-run-wizard spec)
8. Exit & F&F screens (resignation, clearance, F&F statement)
9. Mobile app (React Native/Expo): punch → leave → approvals → payslip → directory, per `docs/product/24` §2.3's five-item bottom nav
10. Web ESS screens
11. Reports & dashboards, report viewer, compliance calendar
12. Settings screens for roles/permissions, notification/email settings, audit log viewer

Design tokens and the core component library (`docs/product/24` §5, `docs/design/01_Design_System.md`) are prerequisites for step 1 and are assumed already in progress per Sprint 1/Foundation.

---

## 10. Database Development Order

Schema build order follows the FK dependency graph already fully specified in `docs/product/08_Database_Architecture.md` — this section only fixes the *sequencing* of migrations against the module order above, not the schema itself:

1. Tenancy & identity tables (`company`, `user`, `user_company`, `role`/`permission`/`role_permission`/`user_role`, `session`/`refresh_token`) — done (`docs/product/08` §3)
2. Organization master (`legal_entity`, `branch`, `department`, `designation`, `grade`, `cost_centre`, `employment_type`, `holiday_calendar`/`holiday`, `week_off_pattern`, `number_series`, `custom_field_definition`) — `docs/product/08` §4
3. Employee domain (`employee` + effective-dated children: `employment`, `employee_assignment`, `employee_compensation`, `employee_statutory`, `employee_bank`, plus `employee_document`, `employee_dependent`/`education`/`experience`/`skill`, `employee_event`) — `docs/product/08` §5
4. Workflow core (`workflow_definition`, `approval_request`, `approval_step`, `approval_action` — **no** `workflow_version`/builder-authoring tables until V3) and Notification (`notification_template`, `notification_log` — partitioned per `docs/product/08` §1 rule 7)
5. Attendance (`shift`, `shift_roster`, `punch` [partitioned], `attendance_day` [partitioned], `regularisation_request`, `ot_request`, device tables)
6. Leave (`leave_type`, `leave_policy`, `leave_ledger`, `leave_application`, `comp_off_ledger`)
7. Payroll (`salary_component`, `salary_structure`, `statutory_master`, `pay_run`, `pay_run_input_snapshot`, `payslip`/`payslip_line` [partitioned], `loan`/`loan_schedule`)
8. Exit (`resignation`, `clearance_checklist`/`clearance_item`, `fnf_settlement` — new, minimal; not previously broken out as its own table group in Document 08, needs a short schema addendum when this sprint starts)
9. `audit_log` — already partitioned and live since B1; every module above writes to it, no new table needed

RLS policies, `EXCLUDE USING gist` effective-dating constraints and partitioning DDL are hand-authored per module migration exactly as `docs/product/08` §1.1 specifies — this roadmap changes nothing about *how* those are written, only confirms the order in which each module's tables come into existence.

---

## 11. API Development Order

Following `docs/product/09_API_Standards.md` §3's existing endpoint catalogue, built in this order (Recruitment's §3.6 catalogue is excluded from V1 entirely):

1. `/v1/auth/*` — done
2. `/v1/companies/current`, `/v1/legal-entities`, `/v1/branches`, `/v1/departments(/tree)`, `/v1/designations`, `/v1/grades`, `/v1/employment-types`, `/v1/holiday-calendars`, `/v1/holidays`, `/v1/week-off-patterns`, `/v1/custom-fields`, `/v1/number-series` (`docs/product/09` §3.1)
3. `/v1/employees*` full sub-tree (§3.2) — assignments, compensation, statutory, bank-accounts, documents, dependents/education/experience/skills, timeline, team/reporting-tree, confirm, import/export, letters (**excluding** the offer-letter template), directory, profile-change-requests
4. `/v1/approvals*` (a reduced slice of §3.7 — approve/reject/delegate, no workflow-definition authoring endpoints yet) and `/v1/notifications*`
5. `/v1/attendance*` full sub-tree (§3.3) — punch, bulk-sync, me/today, days matrix, recompute
6. `/v1/leave*` full sub-tree (§3.4)
7. `/v1/payroll*` full sub-tree (§3.5) — the largest single endpoint group
8. `/v1/exit*` (a new, small group: resignation, clearance, F&F — not previously broken out in §3.8's abbreviated listing, needs the same explicit treatment as §3.1–3.5 when this sprint starts)
9. `/v1/ess/*` composition endpoints per §3.8
10. `/v1/reports/*`, `/v1/dashboards/*` per §3.8
11. `/v1/settings/*` (roles, permissions, notification-settings, email-settings, audit-log query) — incremental, alongside each module above

OpenAPI contract-snapshot CI (flagged as a Sprint 2 follow-up in `docs/SPRINT0_FOUNDATION.md` §4) should be wired up **before** step 2 begins, so contract drift is caught from the first non-auth module onward rather than retrofitted later.

---

## 12. UI Design Order

Following `docs/product/24_UIUX_Screen_Inventory_and_Design_System.md`'s screen inventory (§3), minus §3.7 (Recruitment, 26 screens) in full and §3.8 (Onboarding & Exit, 18 screens) reduced to its exit-half only (~9 screens: Resignation form, Resignation approval, Exit list, Exit detail, Clearance checklist, Clearance item completion, Exit interview form, Exit document issue, Attrition analytics):

1. Design tokens + component library (§5) — prerequisite, in progress since Sprint 1
2. Authentication & platform screens (§3.1, 12 screens) — largely done alongside Sprint 2's auth build
3. Organization/Settings screens (part of §3.10's 19 screens: legal entity, branch w/ map, department tree, designation, grade, custom fields)
4. Employee Management (§3.3, 24 screens)
5. Approval inbox + notification screens (part of §3.9's 12 screens — inbox, bulk approve, notification inbox/preferences/templates; **excluding** workflow visual builder and simulator, which move to V3)
6. Attendance (§3.4, 22 screens) — the attendance matrix (`docs/product/24` §4.2) is one of the two signature screens the design brief calls out for disproportionate investment
7. Leave (§3.5, 16 screens)
8. Payroll (§3.6, 30 screens) — the payslip (`docs/product/24` §4.3) is the second signature screen; the pay-run wizard (§4.4) is the highest-stakes flow in the product
9. Exit-only screens (~9, from §3.8)
10. Mobile app screens — punch (§4.6), leave application (§4.7), manager approval inbox (§4.5), payslip, directory
11. Web ESS screens
12. Reports & remaining Settings screens (rest of §3.10)

**Signature screens (`docs/product/24` §1.2) get disproportionate design time regardless of build order:** the attendance calendar and the payslip breakdown. Schedule dedicated design passes for both, not just implementation time.

**Revised total: ≈159 screens** (185 original − 26 Recruitment − 9 onboarding-portal/task-pack screens moved to V2's Onboarding Automation, retaining the ~9 exit-side screens in V1; − 3 workflow-builder/simulator screens deferred to V3, offset by no new screens added since the exit group already existed).

---

## 13. Testing Strategy

`docs/product/15_Testing_Strategy.md` is adopted **wholesale and unchanged** for V1 — nothing about test levels, coverage targets (95% on payroll/leave/attendance/RBAC), the golden-dataset payroll approach (§3), or the four blocking security suites (§6) is stack- or scope-dependent. Two adjustments specific to this rescoping:

1. **E2E journey E3 is deferred.** `docs/product/15` §5's journey *"Candidate applies → screened → interviewed → offered → accepted → onboarded → becomes employee"* exercises Recruitment end to end and is out of scope for V1's 60-journey suite. It returns as part of V2's test plan. The remaining 11 journeys (E1, E2, E4–E12) are all still in scope and none of them depend on Recruitment existing.
2. **A new journey should be added for Employee Exit** if not already implicit in E7 (`docs/product/15` §5 already includes E7: "Employee resigns → manager accepts → clearance → F&F computed → documents issued → access revoked" — this journey is unchanged and directly validates §5 module #26 above).

The golden payroll dataset (`docs/product/15` §3) and the two-cycle parallel payroll run (§3.3, also required at UAT per §16 below) remain the single most important quality gate in the plan, unchanged by this rescoping — payroll's correctness bar does not shrink because Recruitment shrank the surrounding scope.

---

## 14. Sprint Breakdown

Each sprint below maps to a Document 25 build block (labelled for cross-reference) so existing artefacts stay traceable. Durations are illustrative planning estimates per `docs/product/25` §4.2's own caveat — **re-baseline after Sprint 5, using actual observed velocity**, not these numbers.

| Sprint | = Block | Weeks | Focus | Key deliverables | Demo-able outcome | Status |
|---|---|---|---|---|---|---|
| **1** | B0 | 1–6 | Foundation | ADRs, repo, CI/CD, dev/QA envs, DB schema v1, design tokens, seed data, AI-agent workflow tuned | Architecture walkthrough | ✅ **Complete** — `docs/SPRINT0_FOUNDATION.md` |
| **2** | B1 | 7–12 | Auth & tenancy | Registration, login, MFA, JWT/refresh, company switching, tenant context + RLS, cross-tenant test suite | Login, multi-company switch | ✅ **Complete** — `docs/SPRINT_B1_IDENTITY.md` |
| **3** | B2 | 13–19 | RBAC completion & Org setup | Full permission catalogue (as modules ship), roles, data-scope resolver, field masking; legal entity/branch/department/designation/grade/employment-type/holiday calendar | Set up a company end to end | ⏳ Next |
| **4** | B3 | 20–29 | Employee core, lifecycle & import | CRUD, effective-dated assignment/compensation, documents, custom fields, directory, org chart, audit log, transfer, promotion, confirmation, letters (non-offer), bulk import, 360° view | Bulk-load 500 employees | Not started |
| **5** | B4′ | 30–33 | Approval routing (core only) | Fixed approval-chain execution, approver resolution, SLA/escalation/delegation, approval inbox — **no visual builder** | Configure and run a leave-style approval end to end | Not started — *scope reduced from original B4* |
| **6** | B5 | 34–39 | Notification engine + Shifts | Channels (in-app/email/push), templates, event catalogue, preferences, delivery log; shift master, roster | Notifications firing on events | Not started |
| **7** | B6 | 40–51 | Attendance (capture + processing) | Punch API, mobile/web/kiosk punch, geofence, offline sync, device integration (ZKTeco/eSSL push), status resolution engine, matrix UI, regularisation, OT, exceptions, lock | Punch from a real device; a full month of attendance | Not started |
| **8** | B7 | 52–58 | Leave | Leave types, policies, ledger, application with day-count preview, accrual job, balance statement, team calendar, year-end | Apply → approve → balance updates | Not started |
| **9** | B8 | 59–75 | Payroll (setup + engine + outputs + tax) | Components, formula builder, structures, CTC builder, statutory master, pay-run lifecycle, computation engine, LOP/arrears, calculation trace, validation, variance gate, payslips + PDF, bank files, ECR/ESI/PT/24Q, JV, TDS engine, declarations, loans | Compute a real payroll end to end to bank file | Not started — longest single sprint, deliberately |
| **10** | B10′ | 76–79 | Employee Exit & F&F | Resignation, clearance checklist, F&F settlement, exit docs, access revocation | Offboard an employee end to end | Not started — *scope reduced: no pre-boarding portal/task-pack automation* |
| **11** | B11 | 80–84 | ESS & mobile completion | Employee dashboard, mobile app (punch, leave, approvals, payslip, directory), push, offline | Ship the mobile app to TestFlight/Play beta | Not started |
| **12** | B12 | 85–89 | Reports & dashboards | Standard reports, export pipeline, role dashboards, compliance calendar | Full V1 reporting suite | Not started |
| **13** | B13 | 90–94 | Hardening | Performance tuning, load testing, security fixes (with the security consultant), accessibility, defect burn-down, documentation | Load-test results, pentest fixes | Not started |
| **14** | UAT | 95–104 | Pilot | One or two pilot/design-partner customers, data migration, **two parallel payroll cycles**, training, defect fixing | Signed-off pilot | Not started |
| **15** | Go-live | 105–110 | Launch + hypercare | Production launch, monitoring, rapid fixes | Live customers | Not started |

**Total: ≈110 weeks (≈25 months) to a stable V1 go-live**, versus the original ≈123-week Phase 1 estimate — a 13-week reduction (§1).

**Not reflected as separate sprints, deliberately:** Settings screens/endpoints are not a standalone sprint — per §8/§9's incremental note, each module registers its own settings surface as it ships. A dedicated "Settings polish" pass can be folded into Sprint 13 (Hardening) if gaps remain.

---

## 15. Release Milestones

| # | Milestone | Target week | Cumulative V1 scope |
|---|---|---:|---:|
| M0 | Foundation complete | 6 | 5% |
| M1 | Auth, RBAC, org setup, employee management complete | 29 | 22% |
| M2 | Approval routing, notifications, attendance and leave complete | 58 | 48% |
| M3 | Payroll complete with statutory outputs | 75 | 65% |
| M4 | Employee Exit & F&F complete | 79 | 68% |
| M5 | Mobile app, ESS and reports complete — feature-complete V1 | 89 | 84% |
| M6 | Pilot/UAT signed off with two clean parallel payroll cycles | 104 | 96% |
| M7 | Production go-live + 30 days stabilisation | 110 | 100% |

Compare to `docs/product/25` §7's original M4 ("Recruitment, onboarding, exit complete," week 92, 72%) — that milestone is deleted; its Exit-only remainder is folded into this table's M4, arriving *earlier* (week 79 vs. week 92) because it no longer waits on Recruitment to finish first.

---

## 16. Go-Live Checklist

Adapted from `docs/product/15_Testing_Strategy.md` §10.3 (UAT exit criteria) and `docs/product/25` §6 (Definition of Done), with Recruitment-specific items removed:

**Product / UAT**
- [ ] All V1 UAT scenarios completed and signed off (adapted from `docs/product/15` §10.2, items 1–2, 3–6, 9–12; **item 8, "hire one real candidate end to end," is removed** — replaced with "add one real new joiner manually or by import")
- [ ] Two parallel payroll cycles matching 100% on net pay and every statutory deduction/contribution, for every employee
- [ ] Statutory files (PF ECR, ESI, PT, TDS 24Q) accepted by the actual government portals
- [ ] Zero open S1/S2 defects (`docs/product/15` §8)
- [ ] Performance targets met with the pilot's real data volume
- [ ] Users trained; training material delivered
- [ ] Support process agreed and tested
- [ ] Client/design-partner sign-off document executed

**Engineering**
- [ ] All V1 modules (§5's 61 rows) individually pass their own Definition of Done (`docs/product/25` §6)
- [ ] Cross-tenant isolation, permission matrix, data scope and field-masking suites (`docs/product/15` §6.1–6.4) green on every V1 endpoint
- [ ] 95% coverage maintained on payroll, leave, attendance, RBAC (`docs/product/15` §2)
- [ ] Load test targets met (`docs/product/23_Non_Functional_Requirements_and_Compliance.md`)
- [ ] Security pentest complete, findings remediated (`docs/product/25` §5.2)
- [ ] Recruitment feature flag confirmed **off** by default and the G8 acceptance walkthrough (§3) passes with it off
- [ ] Accessibility: zero critical axe violations on the V1 screen set

**Commercial / GTM readiness**
- [ ] Sales/marketing messaging updated to reflect "Core HR Operations" as the V1 pitch, with Recruitment positioned as a named, dated roadmap item rather than silently absent (see §17, competitive-positioning risk)
- [ ] Pricing/plan entitlements (`docs/product/17` FR-PLT-002) reflect the V1 module set only

---

## 17. Risks

Carried forward and adapted from `docs/product/26_Risk_Register_Open_Questions_and_Change_Control.md`, plus risks specific to this rescoping decision:

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Competitive/GTM positioning gap** — Mid-SME segment (`docs/product/02` §2) is explicitly documented as buying "Recruitment, Onboarding, Reports, Workflow" as part of their trigger; V1 lacks the first of those | Medium | Medium | Target Small-SME segment (Attendance/Leave/Payroll/ESS buyers) first for V1 launch; message Recruitment as a committed, dated V2 item in sales conversations, not a silent gap — this is a messaging problem, not a product one |
| **Onboarding/Exit boundary ambiguity** — the exact split between "manual employee onboarding" (V1) and "candidate-linked onboarding automation" (V2) made as a planning judgment call in §2, not explicit in the source instruction | Low | Medium | Confirm the §2/§5 boundary with product sign-off before Sprint 10 begins; it is cheap to adjust now and expensive to rework after the Exit module ships |
| Biometric device integration takes 3× the estimate | High | High | Unchanged from `docs/product/26` — acquire two real devices before Sprint 7; build the file-import fallback first |
| Statutory file formats rejected by government portals | High | High | Engage the compliance consultant ahead of Sprint 9; test with real ECR/24Q submissions in UAT |
| Payroll edge cases discovered late | High | High | Golden dataset before Sprint 9 (`docs/product/15` §3); parallel run in UAT; do not compress Sprint 9 under schedule pressure |
| Sole-developer bus factor / burnout | High | High | Unchanged from `docs/product/25` §9 — ADRs and runbooks written as-you-go, realistic pacing, Sprint 13 (Hardening) treated as real recovery time |
| AI-generated code passing review too easily on payroll/RBAC/security logic | Medium | High | Unchanged from `docs/product/25` §9 — line-by-line human review retained regardless of module priority changes |
| Scope creep re-introducing Recruitment work piecemeal ("just this one small ATS feature") | Medium | Medium | This document is the scope authority; any request to add Recruitment-adjacent functionality to V1 goes through the Change Control process (`docs/product/26` §5), not ad hoc | 
| Approval-routing scope cut (no visual builder) under-serves a customer's non-standard chain | Low | Low | The fixed chain (requester → manager → HR-if-threshold) covers `docs/product/02` BR-02/BR-03 and the documented default in `docs/product/20`; genuinely custom chains are a V3 Workflow Builder request, tracked, not silently worked around in V1 code |
| Part-time contractor availability/turnover | Medium | Medium | Unchanged from `docs/product/25` §9 |
| Design partners/pilot customers withdraw | Medium | High | Unchanged from `docs/product/25` §9 |

Full risk register with owners, triggers and scoring methodology: `docs/product/26`. This table only lists risks that are new or materially changed by the V1/V2 rescoping — it is not a replacement for Document 26.

---

## 18. Future Roadmap

### 18.1 Version 2 — Recruitment & Onboarding Automation

| Module | Items | Existing spec |
|---|---|---|
| Recruitment | Job Requisitions · Career Portal · Candidate Portal · Resume Parsing · AI Resume Screening · Candidate Ranking · Interview Scheduling · Interview Feedback · Offer Management | `docs/product/17` §8 (FR-REC-001–018) |
| Onboarding Automation | Pre-boarding portal, task-pack templates, auto-provisioning, buddy/check-in workflow, no-show handling | `docs/product/17` §9 (FR-ONB-001–010) |

No functional re-specification is needed to start V2 — `docs/product/17` §8–9 already contain full requirements and acceptance criteria at V1-grade detail; they simply need their priority tag corrected from "Phase 1" to "Phase 2" (see §18.3). The AI/resume-parsing architecture in `docs/product/12_AI_Architecture.md` and `docs/product/21_AI_and_Automation_Feature_Specification.md` is similarly ready to build against once V2 begins.

### 18.2 Version 3 — Extended Platform

Performance Management · Learning Management · Asset Management · Expense Management · Visitor Management · Helpdesk · Workflow Builder (visual configurator, building on V1's approval-routing core) · Advanced AI (attrition prediction, attendance anomaly detection, payroll validation) · Predictive Analytics — all specified at requirements level in `docs/product/18_SRS_Phase2_Phase3_Modules.md` §1–3, §6–10.

### 18.3 Documentation follow-up required (not performed in this task)

This roadmap is the authority for V1 sequencing starting now, but several source documents still describe Recruitment as Phase 1 in their body text and will read as inconsistent with this decision until corrected:

| Document | What needs updating |
|---|---|
| `docs/product/00_README_Document_Index.md` | No change needed — it's a map, not a scope statement |
| `docs/product/02_PRD.md` §5.1–5.2 | Move Recruitment (ATS) and Onboarding Automation from "Phase 1 (MVP)" to "Phase 2"; update the automation-definition table (§6) rows for offer letter / onboarding tasks accordingly |
| `docs/product/17_SRS_Phase1_Core_Modules.md` §8–9 | Re-tag FR-REC-* and FR-ONB-* priority from Phase 1 to Phase 2 (content stays, only the phase label changes) — or move the sections wholesale into `docs/product/18` |
| `docs/product/18_SRS_Phase2_Phase3_Modules.md` | Receives §8–9 from `docs/product/17` if moved wholesale |
| `docs/product/24_UIUX_Screen_Inventory_and_Design_System.md` §3.7 | Re-tag as Phase 2; adjust the "≈185 screens in Phase 1" framing to ≈159 |
| `docs/product/25_Project_Plan_Estimation_and_Team.md` §2–§3 | Superseded by this document for V1; should eventually be edited to point here rather than carry a conflicting standalone plan |
| `docs/design/02_Information_Architecture.md` | Recruitment nav section should move to a "V2" annotation |

These edits are explicitly **out of scope for this task** (planning only, per the brief) and are listed here as the recommended next documentation action, not performed.

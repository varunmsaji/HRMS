# HRMS audit and plan to stand out in the market — 18 Nov 2026

Read-only. No code changed. Based on the code layout, product docs and earlier audit reports. The app was not run, so verify anything marked "verify" before acting on it.

## 1. What exists today

| Area | Size and state |
|---|---|
| Backend | About 104k lines of FastAPI and Postgres across 12 modules, 147 migrations. Attendance (~40k lines) is the deepest, then organisation (17k), leave (11k), employee (10k), payroll (10k). |
| Web | About 85 pages: org masters, employees, onboarding, leave, attendance (policies, shifts, rosters, regularization, overtime, periods, geofences, face setup), payroll (pay runs, salary structures, statutory rates, payslips), settings, setup wizard, platform-admin console. |
| Mobile | Flutter. Parity audit says it mirrors almost all of web, including admin screens. In-app notifications exist, push does not (older gaps doc). |
| Engineering | Tenant isolation in the database (RLS), PII encryption, append-only leave ledger, effective-dated policies, 1,900+ API and 1,000+ web tests. |

**Strengths**
- Attendance and leave rules engine richer than most mid-market HRMS: shifts with versions, breaks, overtime, comp-off, rosters, geofences, regularization, policy resolution.
- Face attendance with liveness checks, four providers.
- Configuration is data, not code, so one codebase can serve different industries.

**Weaknesses**
- Powerful but hard to configure: 15+ policy and settings screens. Repeated settings UX audits are a symptom.
- No data-entry savings yet. The vision says "HR does exception handling", but there are no AI features (grep for LLM or AI-provider code found nothing).
- Payroll is India-only and incomplete: no F&F settlement, reimbursements, loans, off-cycle runs, PF/ESI returns, Form 16, old tax regime. Statutory rates are marked "verify before use".
- No recruitment, performance, or offboarding. No billing or trial enforcement (issue #14).
- Not pilot-ready: 7 blockers in the 11 Nov readiness audit, only test data so far, 17 owner policy decisions pending.
- 5 fixed roles, no custom-role editor (older gaps doc, verify). Navigation not permission-filtered.
- Mobile: no push, no offline, iOS unverified.

Note: `docs/product/STAFF_SPECTRUM_HRMS_FUNCTIONAL_GAPS.md` is partly stale (a notification module now exists). Refresh it before relying on it.

## 2. Where competitors are weak

Common complaints about Keka, greytHR, Zoho People, Darwinbox, BambooHR:
1. Setup takes weeks and needs a consultant.
2. HR cannot tell why someone got a result ("why was I marked absent?", "why is this payslip lower?").
3. Attendance, leave, overtime and payroll disagree, so HR reconciles in spreadsheets.
4. Employees navigate menus for routine things.
5. Per-module pricing with add-ons for mobile and face attendance.

You already have the hard part: a deterministic engine that knows the rules.

## 3. Recommended USP: "HR that explains itself and runs on exceptions"

Positioning: the only HRMS where every number explains itself, and HR only touches what is broken.

### A. "Explain this" on every outcome
Each attendance status, leave balance, overtime figure and payslip line gets a plain-language "why". Example: "Marked half-day because you punched out at 1:10 pm; the shift needs 4h30 for a full day (policy Retail Standard v3, assigned via Branch Mumbai)."
- Fits existing policy resolution, versioned policies and the append-only ledger. Competitors do not expose reasoning.
- How: engine returns the rule and version applied with each result; render on web and mobile.
- Effort: medium (data exposure plus UI).

### B. "Morning check" exception inbox for HR
One first screen listing only what needs a human: missing punches, pending approvals, expiring probations, leave clashes, payroll blockers, unverified statutory rates. Fix inline. Extends decision D1 from the 18 Nov attendance UX audit to the whole product.
- Metric: HR clears the day in under 5 minutes. Effort: medium.

### C. Payroll pre-flight and "what changed since last month"
Before a pay run, reconcile attendance, leave, overtime and encashment to each pay line. Flag deviations only (paid 30 days with 4 absences, overtime spike, new joiner without bank details). Month-on-month diff by employee.

### D. Setup in minutes, not weeks
- Industry templates (retail, manufacturing, clinic, IT services, security) preloading shifts, leave types, overtime rules, holidays, statutory defaults.
- Employee import wizard UI (API exists, no UI) with dry run and rollback.
- "Simulate before publish" for policy changes: "affects 34 employees, alters 12 days of past attendance" (see the historical-impact plan).
- Metric: a new 50-person company reaches first payroll in one day.

### E. Conversational employee surface (phase 2)
Chat-style assistant on mobile and web: "apply sick leave tomorrow", "why was I short today", "show last payslip". Calls the same audited APIs, never decides for HR, keeps a human fallback. WhatsApp-style punch/apply/approve fits Indian SMBs, but only after the core is trusted.

### F. Pricing
One price per employee with face attendance, mobile and geofencing included. Prerequisite: trial and billing (issue #14).

## 4. Phased plan

**Phase 0: Safe to pilot (2–3 weeks, no new features)**
1. Clear the 7 blockers from the 11 Nov readiness audit (clean prod database, scope-check fix done in PR #55, legal notices).
2. Decide the 17 pending owner decisions and C-01..C-20 in the policy decision map so the rules stop moving.
3. Commit or discard the uncommitted work on `test` (attendance remediation, stat tiles, held shift-creation fixes).
4. Role and navigation basics: permission-filtered menus, default role grants (verify).
5. Mobile: push notifications, iOS build.

**Phase 1: First visible USP (4–6 weeks)**
1. "Explain this" for attendance status, leave balance, payslip lines.
2. "Morning check" inbox.
3. Employee import UI with dry run.
4. Consolidate the 15+ settings screens into one guided policy builder with plain-English summary and affected-people preview.

**Phase 2: Trust in the money (6–8 weeks)**
1. Payroll pre-flight and month-on-month diff.
2. F&F settlement, reimbursements, loans and advances, off-cycle runs.
3. Old tax regime, declarations, Form 16 and 24Q, PF ECR and ESI filings.
4. Maker/checker separation on pay runs, configurable for single-admin tenants.
5. Second-person verification of statutory rates, all states' professional tax.

**Phase 3: Differentiators (8+ weeks)**
1. Industry templates and one-day onboarding.
2. Conversational assistant.
3. Exit and offboarding workflow (termination currently leaves employee status unchanged).
4. Basic performance goals and reviews, then recruitment, only if customers ask.
5. Offline punch on mobile with later sync.

## 5. What to avoid
- Breadth (recruitment, learning, engagement) before payroll and attendance are trusted.
- Marketing face attendance before anti-spoof thresholds are calibrated on real devices.
- AI that decides. Keep it explaining and drafting only.

## 6. Success measures
- Signup to first payroll: under one day for 50 people.
- HR minutes per day on attendance.
- Share of disputes answered by the "why" panel without HR.
- Payroll corrections after a run: under 0.5% of payslips.

## 7. Decisions needed from the owner
1. Primary market: India SMB only, or other countries too? This sets Phase 2 statutory depth.
2. Is Pillar E (chat, WhatsApp) worth the cost and third-party dependency?
3. Accept a feature freeze during Phase 0 until pilot blockers close?

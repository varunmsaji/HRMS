# Company admin UI/UX audit (web)

Audit date: 2026-11-26. Read-only, static code review. No code was changed.

**Scope.** The experience of the person who registers and runs a company (tenant): registration, first-run setup, company profile, settings hub, shell and navigation, legal entities and branches, pending-approval and suspended states, and how employees later sign in to that company.

**Method and limits.** I read the source for `register`, `app/setup`, `app/company`, `app/settings`, `app/branches`, the dashboard, the app shell, the company components, the profile validators and the API setup-checklist definition (all under `apps/web/src`, plus `apps/api/.../setup_checklist.py`). The dev server was not running, so **nothing was rendered**. Visual design, responsive layout, colour contrast, real-device behaviour and screen-reader output were **not** verified. The mobile app's admin screens and the platform super-admin console were not audited in depth. Severity: **High** = blocks or misleads a first-time admin or loses input; **Medium** = friction or confusion; **Low** = polish.

## What works well

- Registration form: fieldsets are disabled while submitting, 409/422/429 errors are handled with specific messages, and timezone options come from what the server accepts.
- `FormField` is accessible by design: label, `aria-describedby`, `aria-invalid`, `aria-required`, and `role="alert"` errors. There is a skip-to-content link.
- The company profile uses optimistic concurrency (`If-Match` and a "changed by someone else" recovery with Reload). "No changes to save" is handled.
- Settings hub: searchable, grouped by module, per-module setup progress, and "advanced" items hidden until needed.
- Branches page offers a one-step "quick setup" when no legal entity exists, so a new admin is not dead-ended.
- Read-only banner for companies awaiting approval or suspended; the API enforces it regardless.
- The state components (`LoadingState`, `ErrorState`, `EmptyState`, `PageHeader`) are used consistently.

## Findings

### A. First-run journey (register → setup)

| # | Sev | Finding | Evidence |
|---|---|---|---|
| A1 | High | **A new company is read-only until a platform admin approves it, and registration never says so.** The form ends with "Create workspace", then redirects to `/app/setup`. Setup, profile, branches and everything else cannot be saved while the company is `PENDING_APPROVAL`. The banner appears only after sign-in, with no expected wait, no contact, no "we will email you". | `register/page.tsx` (redirect); `settings.py:133` (new companies wait in `PENDING_APPROVAL`); `company-status-banner.tsx` |
| A2 | High | **Four overlapping "setup progress" trackers disagree.** (1) The dashboard banner and the "Registration" card on `/app/setup` count registration steps (profile only). (2) The checklist list counts 7 attendance-centred items (3 essential). (3) The welcome dialog counts 3 different steps: profile, legal entity, branches. (4) The checklist treats branches as *optional*, while the dialog treats them as a step. The admin sees "1 of 1", "0 of 3 essentials" and "1 of 3" in one session. | `setup/page.tsx`, `setup-checklist-card.tsx`, `welcome-setup-dialog.tsx`, `dashboard/page.tsx`, `setup_checklist.py` |
| A3 | High | **The setup checklist never mentions adding employees or inviting users**, the thing an HR admin must do before any shift, policy or leave rule matters. It also omits departments, designations and payroll. The first essential item is "Create a shift". | `setup_checklist.py` item codes: SHIFT, WORK_CALENDAR, ATTENDANCE_POLICY, then optional REGULARIZATION, OVERTIME, LEAVE, BRANCH |
| A4 | Med | **The `/app/setup` page is half-built.** `STEP_DESTINATIONS` has one entry ("Only one step exists in V1"). Its back link is "Access & setup", which is odd for a first-run page. Setup is not in the sidebar: it is reachable only through the dashboard banner or a Settings banner. | `setup/page.tsx`; `nav-items.ts` |
| A5 | Med | **The welcome dialog re-fetches on every dashboard visit once setup is complete.** It marks itself "seen" only when it actually opens. If every step is done, it returns early without marking, so 3 extra API calls (setup-progress, legal-entities, branches) run on every dashboard load for every admin, forever. | `welcome-setup-dialog.tsx` effect: `loaded.every(done)` returns before `markSeen` |
| A6 | Med | The dialog is remembered per browser (`localStorage`). "I'll do this later" hides it permanently, and another browser or device shows it again. It needs two permissions (`ORG.COMPANY.MANAGE` and `ORG.BRANCH.MANAGE`), so a company admin lacking one never sees it. | same file |
| A7 | Med | The dashboard blocks on both `/dashboards/company` **and** `/companies/current` (it needs the profile only for the company name, which the session already holds). One slow call delays the whole page. | `dashboard/page.tsx` |
| A8 | Low | Registration has no consent line for terms or privacy, no email-verification step, and no hint of what happens next. For an HR product that stores employee PII, that is expected by buyers. | `register/page.tsx` |

### B. Registration form

| # | Sev | Finding |
|---|---|---|
| B1 | Med | Country code and currency are free-text boxes ("IN", "INR") with maxLength 2/3. A typo such as "UK" or "RS" is only caught by regex shape, then the server. Timezone already shows the right pattern (locked "India-only for now"), so lock or select these too. |
| B2 | Med | "Industry" is free text placed in a field called `industryCode` (label "Industry" here, "Industry code" on the profile page). It should be a list. |
| B3 | Low | There is no password-strength or "show password" hint beyond helper text (the input component supports toggling). There is no focus move to the first error on submit. |
| B4 | Low | Single long page with 11 fields and no sense of progress. Splitting into two steps ("Company", "You") would reduce abandonment. |

### C. Company profile (`/app/company`)

| # | Sev | Finding | Evidence |
|---|---|---|---|
| C1 | High | **Server validation errors can be silently dropped on save.** The 422 handler maps only name, currency, timezone, business hours, working days and fiscal year. Contact (email, phone, website), address, locale (language, date format) and branding errors have no mapping, and nothing else is shown. The admin clicks Save and nothing visibly happens. | `company/page.tsx` `handleSave` 422 branch; client validator checks only name, fiscal month, working days, hours |
| C2 | High | **A 403 on save replaces the whole profile with "You do not have permission to view this company profile".** The user could view it a second ago. This is also what a pending-approval company hits, and the Edit button is not disabled in that state. | `company/page.tsx` (`status === 403` → `setError`) |
| C3 | Med | Free-text fields where a control belongs: country code, **language code ("en-IN")**, **date format ("DD/MM/YYYY")**, logo URL, primary colour (hex), business hours ("HH:mm"). A wrong date format can change how dates render across the app; there is no preview. Use selects, a colour picker with preview, time inputs and a logo upload (MinIO already exists). |
| C4 | Med | Client validation is thin: no check for email, website, postal code, colour, date-format or language values, so most mistakes cost a round trip (and see C1). Overnight business hours (end earlier than start) are rejected, which blocks night-shift companies. |
| C5 | Med | One 25-field form with a single Save at the bottom, no sticky save bar, no unsaved-changes warning on navigate-away, and no scroll to the first error. |
| C6 | Med | **View mode shows internals**: "Fiscal year start: 4" (should read April), status as raw enum ("TRIAL"), "Version: 3", country as "IN", empty values as "Not configured". |
| C7 | High | **The "Company code (for employee-ID sign-in)" is the thing employees need to log in, and it is the 5th item in the last section "Branding & Metadata", with no copy button or share text.** Employee-ID login requires it. | `company-profile-view.tsx`; `login/page.tsx` |
| C8 | Low | "Currency cannot be changed after trial." has no route to change it (no contact or request action). |

### D. Settings hub, navigation, shell

| # | Sev | Finding |
|---|---|---|
| D1 | Med | **Terminology collision.** "Company" means the tenant (registration, profile, "Company & structure"), the legal entity ("Add your company (legal entity)" in the welcome dialog; "Add your company" quick setup; "Unknown company" fallback on branches), and the sign-in "Company code". "Organisation" is also used (slug `organisation`, "your organisation"). Pick one term for the tenant and one for the legal entity. |
| D2 | Med | "Onboarding" means employee onboarding in the sidebar and `/onboarding/[token]`, but company setup is also called onboarding (`onboarded_at`, "keep onboarding moving"). Name company setup "Setup" everywhere. |
| D3 | Low | Company Profile is three clicks deep (Settings → Company & structure → Company Profile). Reasonable, but there is no shortcut from the top bar company name, which is a non-interactive label. |
| D4 | Low | The top bar makes an extra request for the company name that the session already has (`session.companies`); it shows "…" until it returns. |
| D5 | Low | Settings page description is a 25-word run-on; the search box and guide link share the header and crowd on narrow widths (unverified). |

### E. Branches and legal entities

| # | Sev | Finding |
|---|---|---|
| E1 | Med | A legal entity must exist before a branch, and the page explains this with a quick setup dialog. The dialog collects only a name; GSTIN, PAN, and address are asked later, so statutory data is easy to miss. |
| E2 | Low | The page description reads "Physical work locations under your companies." (plural, D1). Branch form uses `state_code` and `pincode` fields; I did not verify whether these are selects. |

### F. Pending, suspended, and error states

| # | Sev | Finding |
|---|---|---|
| F1 | High | The pending-approval banner has no ETA, no contact, no notification promise (see A1). The suspended banner says "Contact support" with no address or link anywhere in the web source. |
| F2 | Med | Loading states are a text spinner ("Loading profile…") rather than layout-shaped skeletons, so the page jumps when data arrives. The existing `docs/ui-performance` work did not cover these screens. |
| F3 | Low | Many list and form screens each call `describeApiError` independently; the wording for 403/423 differs from page to page (compare setup, profile and branches). |

### G. Accessibility and testing

- Positive: labels, descriptions and error wiring are consistent through `FormField`.
- Gaps (unverified in a browser): every field error is `role="alert"`, so a form with many errors announces them all at once; no focus management to the first error on register or profile; the working-day checkboxes use a bare `<input type="checkbox">` with no visible focus style; colour contrast of `text-foreground-disabled` "Not configured" values was not measured.
- Tests: component tests exist for register, login, welcome dialog, branches, legal entities, the dashboard and the settings guide. Browser (Playwright) tests cover only policy-followers and work-calendar. There is **no end-to-end test of register → setup → profile → branch**, the exact path a new customer takes.

## What to do, in order

**Do first (new-customer blockers, small changes)**
1. Tell the user about approval before and after registering: a line on the form, and a clear "Your workspace is created; an administrator will approve it" state with a contact. Disable Edit while the company is read-only (A1, C2, F1).
2. Fix the 422 handling on the profile so every server field error appears, plus a general message if none map (C1). Add client checks for email, website, hex colour and date format (C4). Make a 403 on save show "You can't edit this" without hiding the profile (C2).
3. Move the **Company code** to the top of the profile with a Copy button, and add it to the employee-invite and login help text (C7).
4. Unify setup progress into one list and one count. Make "Add employees / invite users" an essential step. Remove or merge the Registration card (A2, A3, A4).
5. Make the welcome dialog mark itself seen or stop fetching once everything is done (A5).

**Then (friction)**
6. Replace free text with controls: country, currency, language, date format (with a live example), time inputs, colour picker, logo upload (B1, C3).
7. Show readable values in view mode: month name, friendly status, country name; hide "Version" (C6).
8. Split the profile into collapsible sections with save-per-section or a sticky save bar, and an unsaved-changes guard (C5).
9. Decide the vocabulary: Company (tenant), Legal entity, Branch, Setup (D1, D2).
10. Stop blocking the dashboard on the profile request, and drop the top-bar extra request (A7, D4).

**Later**
11. Skeleton loading for these screens (F2); consent checkbox and email verification (A8); two-step registration (B4).
12. Add a Playwright test for register → setup → profile edit → add branch → sign in with employee ID.

## Not verified. Suggested follow-up

Run the app locally (Docker Postgres/Redis/MinIO, API, web) and walk the journey on desktop and a 375 px phone viewport with the keyboard only, with a screen reader pass on the registration and profile forms, to confirm layout, contrast and focus behaviour. Also audit the mobile admin screens and the platform console's company approval flow, which decides how fast new customers leave the pending state.

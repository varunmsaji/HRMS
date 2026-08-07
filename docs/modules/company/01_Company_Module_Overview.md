# Company Module — Overview

**Status:** Design — first business module of Version 1.
**Bounded context:** `Company` (tenant root aggregate).
**Physical package:** `apps/api/src/hrms/modules/organisation/` — see [§3 Boundaries](#3-boundaries) for why this domain does not get its own top-level package.
**Depends on:** Sprint 0 (foundation), Sprint B1 (`docs/SPRINT_B1_IDENTITY.md` — auth, JWT, RBAC engine, multi-tenancy, audit).
**Related implementation plan:** `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` (binding prior art — this document set narrows that sprint's `organisation` package down to the **Company sub-domain only**; Branch/Department/Designation/Grade/Employment Type/Holiday/Shift/Leave Policy/Payroll Policy/Number Series are separate sub-domains of the same package, documented elsewhere).

---

## 1. Purpose

Every row in this system — every branch, department, employee, shift, leave application, payslip — exists because it belongs to a Company. The Company module is what makes that sentence true at the database, API, and security layer simultaneously: it is the **tenant**, the **root aggregate**, and the **configuration source of truth** that every other module reads from but never writes to.

Concretely, the module exists to:

1. Let a new organisation **self-register** as a tenant and receive an immediately usable, authenticated admin session.
2. Hold the **company profile** — legal identity, contact details, branding — as the one canonical record every other module can join against.
3. Hold the **company-wide settings** that are not business-process configuration (that's Branches/Departments/etc.) but *platform behaviour*: timezone, currency, locale, date format, fiscal year, default working days, business hours.
4. Hold **company lifecycle state** — trial, active, suspended, terminated — and the **subscription/plan/feature-flag** data that gates which parts of the product a tenant can use.
5. Track **setup completion** as derived, honest state (not a client-side checklist) so onboarding never lies about what's actually configured.
6. Provide a **read-only aggregation surface** (the Company Dashboard) over counts owned by other modules, without absorbing their logic.

## 2. Responsibilities

### In scope

| Area | What it covers |
|---|---|
| Company Profile | Name, legal name, registration number, contact details (email, phone, website), industry, company size, registered address |
| Company Settings | Timezone, currency, locale, date format, fiscal year start month |
| Branding | Logo, theme/white-label JSON |
| Working Days & Business Hours | Company-wide default week-off pattern and business hours (the fallback every Branch/Shift inherits unless it overrides) |
| Company Status | Lifecycle state (`TRIAL` / `ACTIVE` / `SUSPENDED` / `TERMINATED`) and the transitions between them |
| Subscription Metadata | Plan assignment, subscription status, billing period, trial expiry |
| Feature Flags | Plan-derived and company-specific feature toggles |
| Registration | Self-service tenant creation: Company + first User + membership + seeded `COMPANY_ADMIN` role |
| Setup Progress | Server-derived tracking of onboarding-step completion across *all* modules, surfaced as one Company-owned resource |
| Company Dashboard | Read-only count aggregation across other modules' tables |

### Explicitly out of scope

These are **separate modules/sub-domains**, even though several are implemented in the same `organisation` Python package per the existing architecture. The Company module must never own their tables, business rules, or write paths:

- **Legal Entities** — statutory registration (GSTIN, PAN, CIN, PF/ESI codes) for one or more legal entities under a company. See [§6](#6-domain-ownership) for why GSTIN/PAN are *not* Company Profile fields.
- **Branches / Work Locations**
- **Departments**
- **Designations & Grades**
- **Employment Types**
- **Holiday Calendars & Shifts**
- **Employees** — and everything downstream: Attendance, Leave, Payroll, Recruitment, Onboarding, Exit.

If a future requirement seems to belong to Company but touches any of the above, treat that as a signal the requirement belongs to the *other* module, referencing Company by `company_id`, not the reverse.

## 3. Boundaries

**Why "Company module" and not "Company package."** `docs/architecture/01_Backend_Structure.md` §3 and `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Task 2.1.2 already fixed the physical layout: one `hrms/modules/organisation/` Python package holds every org-setup entity (Company, Legal Entity, Branch, Department, Designation, Grade, Employment Type, Holiday Calendar, Shift, Leave Policy config, Payroll Policy config, Number Series) because they share one bounded "org-setup" transaction boundary and are collectively under the "split only past 15 tables" threshold (`02_Module_Standard.md` §1). This document set does not reopen that decision — it does not create `modules/company/`.

What it does instead: draws the **domain boundary** inside that package. Company-owned files, tables, and service methods are enumerated precisely in [03_Database_Design.md](03_Database_Design.md) and [05_Backend_Architecture.md](05_Backend_Architecture.md) so that when Branch/Department/etc. are built (by this same package, later or in parallel), there is no ambiguity about which parts of `organisation/models.py`, `organisation/service.py`, etc. belong to Company vs. its sibling sub-domains.

**Aggregate boundary rule:** `Company` is the aggregate root. `CompanySetupProgress`, `Subscription`, and `CompanyFeatureFlag` are part of the Company aggregate (one row per company, lifecycle bound to the company). `LegalEntity`, `Branch`, `Department`, etc. are **separate aggregates** that hold a `company_id` foreign key — they reference Company, they are not contained by it. This matters operationally: a Company write transaction never needs to touch a Branch row, and vice versa.

**Module boundary rule (existing, restated):** per `02_Module_Standard.md` §2, other modules may import `organisation.service` and `organisation.schemas` — never `organisation.models` or `organisation.repository`. Every other module's only legitimate way to know a company's timezone, currency, or feature-flag state is a `CompanyService` method call.

## 4. Dependencies

**Upstream (what Company depends on):**
- `core/db`, `core/tenancy`, `core/errors`, `core/rbac`, `core/audit`, `core/auth` (password hashing, JWT issuance — reused, not duplicated, from `identity` module per Sprint 3 Task 2.1.3).
- `identity` module's token-issuance logic (registration ends in an authenticated session identical in shape to login).

**Downstream (what depends on Company):** every business module, without exception:

| Module | What it reads from Company |
|---|---|
| Organisation sub-domains (Branch, Department, Designation, Shift, Holiday, Leave Policy, Payroll Policy) | `company_id` FK; inherit default working days/business hours/timezone unless overridden |
| Employee | `company_id` FK; locale/date-format for display; number-series allocation scoped by company |
| Attendance | `timezone` (business-day boundary computation, ADR-0010); default working-days pattern |
| Leave | `timezone`; fiscal year (leave-year alignment); `currency` not used |
| Payroll | `currency`, `fiscal_year_start_month` (pay-cycle alignment), `timezone` (pay-period cutoffs) |
| Recruitment, Onboarding, Exit | `company_id` FK; branding (candidate-facing pages) |
| Notification | `timezone` (per-tenant scheduled sends), branding (email templates) |
| Reporting/AI | `company_id` FK; `currency`, `locale`, `date_format` for rendering |

Because of this fan-out, **Company's public service interface is one of the highest-blast-radius contracts in the system** — a breaking change to `CompanyService` ripples into every module listed above. Changes to its public methods require the same review rigor as a payroll or RBAC change (`docs/development/AI_Coding_Guidelines.md` §8).

## 5. Future Extensions

Flagged now, not built now — each is a genuine gap in the current source specs (confirmed absent from `docs/product/08_Database_Architecture.md`'s data dictionary), not an invented feature:

| Extension | Why deferred |
|---|---|
| Platform/Super-Admin cross-tenant console (manage subscriptions, impersonate, suspend tenants) | `PLATFORM.*` permission namespace and "Super Admin" role are documented (`docs/product/19` §3.6/§4) but no platform-role table or router exists yet — needs its own design pass, not silently folded into Company |
| Multiple legal entities per company (multi-GSTIN, multi-state registration) | `legal_entity` table already exists in schema; Company exposes only a "primary legal entity" read-through this sprint (§6) |
| Billing integration (invoices, payment methods, dunning) | `Subscription`/`Plan` here is metadata only — no payment-provider integration is in scope |
| Custom domains / white-label subdomains beyond the `subdomain` slug | Not specified anywhere in the source docs |
| Locale packs beyond date-format (number formatting, translated UI strings) | `locale` field reserved for this; i18n engine itself is out of V1 |
| Data residency enforcement (`data_region`) | Column exists (schema drift noted in §03), enforcement mechanism (routing to a regional DB) is an infra-layer concern, not this module's |
| Company-level SSO / SAML configuration | No mention in any source doc; would be a new sub-aggregate if built |

## 6. Domain Ownership

Resolving one explicit tension between this brief and the existing architecture: the brief lists **GSTIN and PAN** under "Company Profile." The existing, already-implemented schema (`docs/product/08_Database_Architecture.md` §4, `apps/api/scripts/sql/001_init_schema.sql`) puts statutory registration numbers (GSTIN, PAN, TAN, CIN, PF/ESI codes, registered address, signatory details) on a separate `legal_entity` table, explicitly to support companies with **multiple legal entities** (different GSTIN per state, a holding company with subsidiaries, etc.) — a real requirement for Indian enterprise payroll/compliance that a single-value Company field cannot express.

**Decision:** Company does not own GSTIN/PAN/CIN. It owns a generic `registration_number` (for the common single-entity case — sole proprietorships, single-GSTIN companies that never create a second legal entity) and, once the Legal Entity sub-domain exists, exposes the **primary legal entity's** statutory numbers as a read-through projection in the Company Profile API response (`GET /v1/companies/current` → `primary_legal_entity: {gstin, pan, cin} | null`). This satisfies "the module should support GSTIN/PAN" at the product-surface level without duplicating storage or reopening the existing multi-entity data model. See [02_Domain_Model.md §6](02_Domain_Model.md) and [04_API_Design.md](04_API_Design.md) for the exact contract.

Everything else the brief lists (Time Zone, Currency, Locale, Fiscal Year, Working Days, Business Hours, Status, Subscription Metadata, Feature Flags, Branding, Website/Email/Phone, Industry, Company Size, Address, Logo) is owned directly by Company with no such conflict — detailed field-by-field in [02_Domain_Model.md](02_Domain_Model.md) and [03_Database_Design.md](03_Database_Design.md).

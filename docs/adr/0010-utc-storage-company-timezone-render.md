# ADR-0010: UTC Storage, Company-Timezone Rendering, Company-Timezone Business-Day Boundaries

**Status:** Accepted

## Context

The platform serves tenants who may span timezones (Doc 03 A9), and attendance/payroll have hard
"business day" boundaries — when does a night-shift punch belong to "today" vs. "yesterday", and
when does the payroll period for March actually end? If timestamps are stored or reasoned about in
server-local time, or if business-day boundaries are computed against UTC midnight instead of the
company's actual midnight, attendance status resolution and payroll period cutoffs will be silently
wrong for any tenant not in the server's timezone — a category of bug that is very hard to notice
until a specific employee's attendance or pay is disputed.

## Decision

All timestamps are stored in **UTC** in the database, full stop. Every `company` record carries a
`timezone` column (Doc 04 §3.1, default `Asia/Kolkata`) which is the single source of truth for:

- Rendering any timestamp to a human in that company.
- Computing attendance-day and payroll-period **business-day boundaries** — never UTC's own
  midnight.

## Consequences

- **Positive:** storage is unambiguous and DST-safe; no "was this timestamp local or UTC" bugs at
  the data layer.
- **Positive:** attendance resolution and payroll period cutoffs are always correct relative to
  what the company actually experiences as "the end of the day," which is what employees and HR
  administrators intuitively expect and dispute against.
- **Negative:** every date-boundary computation (attendance day resolution, absent marking,
  accrual jobs, payroll period close) must explicitly resolve the company's timezone rather than
  using the server's or a hardcoded one — a class of bug (using `new Date()` boundaries without
  the company timezone) that must be caught in code review and, ideally, lint rules.
- **Negative:** scheduled jobs that are naturally timezone-bound (Doc 14 §5: "absent marking...
  02:00 company-local", "birthday greetings... 08:00 company-local") must be scheduled per-tenant
  relative to that tenant's timezone, not as one global cron fire — more scheduling complexity than
  a single-timezone product would need.

## Alternatives Considered

- **Store and compute everything in server/UTC time, convert only for display.** Rejected: this is
  the naive approach and it silently breaks business-day boundaries for any tenant not aligned with
  the server's operational assumptions — exactly the bug class this ADR exists to prevent for
  attendance and payroll specifically.
- **Store timestamps in each company's local time directly.** Rejected: ambiguous across DST
  transitions and impossible to compare/sort correctly across tenants in shared tables (e.g. a
  cross-tenant `punch` partition) — UTC storage with timezone-aware rendering is strictly safer.

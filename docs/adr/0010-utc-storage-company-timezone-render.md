# ADR-0010: UTC Storage, Company-Timezone Rendering, Company-Timezone Business-Day Boundaries

**Status:** Accepted, **rendering clause amended 2026-09-15** — see Amendment below.

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

## Amendment (2026-09-15) — rendering clause

`WD-06` (LOCKED, `../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` §140) supersedes this ADR's
rendering clause for attendance specifically: the timezone used to *compute* an attendance day is
`ShiftVersion.timezone > Branch.timezone > Company.timezone`, not `Company.timezone` alone. Literal
compliance with this ADR's original wording — "`company.timezone` is the single source of truth for
rendering" — would display a branch operating in a different zone from its company (e.g. a
`Asia/Dubai` branch under an `Asia/Kolkata` company) in a zone its figures were never computed in.
That is a second bug, not correctness.

**The rendering clause is amended to:** for attendance timestamps, the single source of truth for
rendering is **the timezone the figure was actually computed in** (the WD-06-resolved zone, recorded
per-row on `attendance_day.timezone`) — not the literal `company.timezone` column. Every rendered
attendance time must carry an explicit zone label; it must never fall back to the viewer's browser
timezone. `company.timezone` remains the source of truth for every **non-attendance** timestamp
(audit-log entries, `created_at`, notification times) and for business-day boundaries where no
more specific zone applies, per the original Decision above — this amendment narrows the rendering
clause only, and only for attendance.

For the current tenant base (all companies on `Asia/Kolkata`, no branch-level timezone override in
use) the two readings are identical and this amendment changes no visible behaviour today. It is
recorded now — decided as `CD-3` in
[`../audits/ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`](../audits/ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md)
§13.3 / §19 — so it is correct in advance of the day a second timezone is onboarded, rather than
amended under production pressure later.

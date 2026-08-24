# Attendance V1 — Business Rules Document Set (Client Review)

**Purpose:** Give HR, product owners, and client stakeholders a complete, non-technical picture of how the Workforce Attendance module behaves today, what can be configured, what is not yet built, and what decisions still need a business sign-off.

**Audience:** HR/Admin, client product owner, implementation consultants. No database, API, or code knowledge is assumed.

**Status:** Documentation only. Nothing in this document set changes how the system behaves. It describes the system **as it exists today** (slices W1–W9) and separates that clearly from things that are configurable-but-inactive, not-yet-built, or still awaiting a decision.

**Method:** Every document was checked against the live calculation engine, policy resolution logic, and workflow code (not just design documents), and against the existing technical business-rules set in `docs/business-rules/attendance/`. Where the code and older documentation disagreed, the code wins and the disagreement is called out.

---

## How every statement is labelled

Every rule in this document set carries exactly one tag:

| Tag | Meaning |
|---|---|
| **CURRENTLY WORKING** | Happens automatically today, not configurable |
| **CONFIGURABLE AND WORKING** | HR can change this setting, and the system actually behaves differently as a result |
| **STORED BUT NOT USED** | HR can enter/edit this setting today, but the system currently ignores it |
| **OPEN PRODUCT DECISION** | The current behaviour is a default, not a confirmed business rule — needs client sign-off |
| **FUTURE MODULE** | Owned by a module that doesn't exist yet (Leave, Payroll, Device, Workflow Engine) |
| **KNOWN LIMITATION** | Works, but with an edge case or simplification worth knowing about |

If something is not tagged, treat it as unverified and ask before relying on it.

---

## Documents in this set

| # | Document | What it's for |
|---|---|---|
| 1 | [`ATTENDANCE_V1_CLIENT_FLOW.md`](./ATTENDANCE_V1_CLIENT_FLOW.md) | The full attendance story end to end, in HR language, with diagrams |
| 2 | [`ATTENDANCE_V1_DAY_IN_THE_LIFE.md`](./ATTENDANCE_V1_DAY_IN_THE_LIFE.md) | A worked example across one employee's month — late arrival, an early departure, a missed punch, a leave day, a shift on a weekly off, and month-end lock |
| 3 | [`ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md`](./ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md) | "Which rule wins when two rules apply" — the override matrix |
| 4 | [`ATTENDANCE_V1_SCENARIO_CATALOG.md`](./ATTENDANCE_V1_SCENARIO_CATALOG.md) | 50+ realistic day-in-the-life scenarios, including Indian HR patterns |
| 5 | [`ATTENDANCE_V1_CONFIGURATION_CATALOG.md`](./ATTENDANCE_V1_CONFIGURATION_CATALOG.md) | Everything HR/Admin can configure, who can configure it, and what it actually affects |
| 6 | [`ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md`](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md) | Settings that look active but aren't, plus every open decision awaiting sign-off |
| 7 | [`ATTENDANCE_V1_CLIENT_SIGNOFF.md`](./ATTENDANCE_V1_CLIENT_SIGNOFF.md) | The actual review checklist — questions the client should answer |

## Recommended reading order

**For the client / product owner (business review):**
README → 1 (Client Flow) → 2 (Day in the Life) → 3 (Precedence) → 4 (Scenarios) → 6 (Gaps & Open Decisions) → 7 (Sign-off checklist)

**For HR configuration owners:**
README → 1 (Client Flow) → 4 (Configuration Catalog) → 5 (Gaps & Open Decisions)

**For anyone who just wants the decisions to sign off on:**
README → 6 (Sign-off checklist) — refer back to 1/2/3/5 for context on any question.

---

## What this module covers today (W1–W9)

Work calendars and holidays, weekly-off patterns, shifts and rosters, break rules, three families of policy (Attendance / Overtime / Regularization), punch capture, day-by-day attendance calculation, leave overlay (as a mirror of approved leave, not a full leave system), regularization (correction) requests, overtime detection and approval, and period close/lock ready for payroll handoff.

## What this module does **not** cover yet

Leave applications, balances, and accrual; payroll money calculations; biometric device connectors; a general-purpose approval-workflow engine; corrections after a period is locked; automatic shift rotation generation. These are called out throughout as **FUTURE MODULE**.

---

## Related technical material

For engineers and implementers, the underlying technical business-rules set remains at `docs/business-rules/attendance/` (rule-by-rule detail, code references, precedence tables in technical form) and the architecture/decision log at `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` and `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`. This client-facing set is a translation and reorganization of that material for business review — it does not replace it.

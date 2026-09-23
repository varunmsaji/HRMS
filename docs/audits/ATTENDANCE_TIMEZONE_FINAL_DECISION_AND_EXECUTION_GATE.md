# Attendance — India V1 Timezone: Final Decision & Execution Gate

**Created:** 2026-09-15
**Decisions selected:** 2026-09-15 — every `RED`/`CLIENT DECISION REQUIRED` item below has been
resolved in favour of this document's recommended answer, on the product owner's instruction to
convert recommendations into selected decisions. **`DEC-TZ-01`…`DEC-TZ-09` and `CD-1`…`CD-8` are now
`SELECTED`, not recommended.** See §0 (Final Decision Register) for the single authoritative list.
**Status:** **APPROVED — IMPLEMENTATION IN PROGRESS.** This document is the artefact engineering
implements against.
**Baseline commit:** `e33fcdb` · branch `main`
**Product scope:** India only · business timezone `Asia/Kolkata`
**Stage:** `AUDITS → DECISIONS → PLAN → SPEC → EXECUTION GATE → ` **`IMPLEMENTATION`**
**Implementation record:** [`ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md`](./ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md)

**Original preparation pass — code changed: NO · Schema: NO · Migrations: NO · Tests: NO · CI: NO ·
Configuration: NO · Data: NO.** Changes made under the implementation programme this document
authorises are recorded in the completion report above, not here.

---

## What this document is

Everything upstream of this document is investigation. This document is the **instrument that ends
the investigation**: it states, once, in one place —

1. what is already decided and needs no further sign-off (`GREEN`),
2. what engineering must agree internally before writing code (`YELLOW`),
3. what only the client can decide, in plain business language, with a recommended answer (`RED`),
4. what cannot be resolved from this repository at all (`BLOCKED`).

It does not re-run the investigation. Every claim below carries a citation to the document or code
location that established it. Where two upstream sources disagree, both are shown and the more
authoritative one is named — that happens exactly twice (§3 below, `SR-01`; §12, `OD-1`), and both are
resolved in favour of the **spec**, because the spec was produced by re-executing the code and the
documents it corrects were not.

**Re-verification for this gate.** Every code citation carried forward from the spec was independently
re-read from the working tree at `e33fcdb` while preparing this document (not merely copied): `match_breaks`
(`calculation.py:574-617`), `_interval_contains`/`_derive_cross_midnight` (`organisation/service.py:2055-2087`),
`create_punch` (`attendance/router.py:750-788`), `PunchCreate` (`attendance/schemas.py:1222-1240`), the three
Beat leave tasks and `celery_app.py`'s `beat_schedule` (`leave/tasks.py`, `celery_app.py:1-52`), `ShiftVersionCreate`/
`Update.timezone` (`organisation/schemas.py`, no validator — confirmed absent), `CompanyRegistrationRequest.timezone`
and `BranchCreate/Update.timezone` (IANA-validated, confirmed present), `_assert_timezone_change_allowed`
(`organisation/service.py:702-709`, confirmed still a documented no-op), `shift-version-form.tsx:66-71` and
`branch-form.tsx:93-97` (confirmed free-text `<Input>`, not a `<select>`), `register/page.tsx` (confirmed
`<select>` from `listTimezones()`), `.github/workflows/ci.yml` (confirmed one job, `DATABASE_URL` at `hrms`
not `hrms_app`, no `services:`, no `alembic`, no `TZ`, no web job), `AttendanceDay`'s docstring
(`attendance/models.py:472-484`), `_ensure_date_open` and the UTC-date period-lock check
(`attendance/service.py:1915-1929`, `:2347`), and the absence of `with_for_update` anywhere in `src/`
(confirmed by grep). **No discrepancy was found against the spec's claims in any of these locations.**

## Source of truth and its hierarchy

| Rank | Document | Role |
|---|---|---|
| **1 (highest)** | **This document, once approved** | The only artefact anyone should implement against |
| 2 | [`ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md`](./ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md) | The reconciliation this gate packages — code-verified 2026-09-15, `SR-01`…`SR-14` |
| 3 | [`ATTENDANCE_TIMEZONE_IMPLEMENTATION_PLAN.md`](./ATTENDANCE_TIMEZONE_IMPLEMENTATION_PLAN.md) | The phase plan the spec corrects in two places (§3, §12 below) |
| 4 | [`ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md`](./ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md) | Long-form `DEC-TZ-01…16` rationale; superseded on the break-fix approach (§3) |
| 5 | [`ATTENDANCE_TIMEZONE_AUDIT.md`](./ATTENDANCE_TIMEZONE_AUDIT.md) · [`ATTENDANCE_TIMEZONE_TEST_MATRIX.md`](./ATTENDANCE_TIMEZONE_TEST_MATRIX.md) | Original findings (`TZ-nn`) and the 68-scenario matrix |
| 6 | [`../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md`](../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md) | Ingestion findings `F-nn` |
| 7 | [`../adr/0010-utc-storage-company-timezone-render.md`](../adr/0010-utc-storage-company-timezone-render.md) (`DEC-010`, **LOCKED**) · [`../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`](../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md) (`WD-06` §140, `WD-11` §237, `WD-30` §890, all **LOCKED**) | The architectural decisions everything else must be consistent with |

**Two documented conflicts, both resolved in favour of the spec:**

| Conflict | Older source says | Spec says (and this gate adopts) | Why the spec wins |
|---|---|---|---|
| Cross-midnight break fix approach | Remediation §12.6: build UTC spans, roll the end forward ("Approach B") | Spec §14: wrap-aware time-of-day comparison ("Approach A") | Approach B is **CODE-PROVEN to regress** a working case (§3 below); the remediation doc's stated objection to Approach A does not match what `_derive_cross_midnight` actually does |
| Period-lock date basis (`OD-1`) | Plan §23.2 frames it as a free client choice and calls Option B "strictly safer" | Spec §9: derived by executing the shipped window functions — the divergence band is narrower than stated and the "safer" framing hides an asymmetric trade | The plan's claim is **not supported by execution**; the spec's is |

No other conflicts exist between the five upstream documents — everywhere else they agree, and this
gate simply carries the agreement forward without re-deriving it.

---

## India V1 scope — binding on this document

```text
Country:                        India
Primary timezone:               Asia/Kolkata
DST:                             Not applicable to V1
Employee-specific timezone:      Not supported in V1
Offline attendance:              Not supported unless separately approved
International timezone selection: Not supported in V1
```

Nothing in this document proposes multi-country timezone infrastructure. Nothing in it proposes
removing the existing IANA-timezone architecture (`ShiftVersion.timezone`, `Branch.timezone`,
`Company.timezone`, WD-06 precedence) — that architecture is what makes the engine provably
zone-independent (spec `PC-01`/`P-20`) and is kept for exactly that reason, at zero cost to an
India-only V1.

### The central principle, stated once

> **HRMS V1 operates in India. `Asia/Kolkata` is the canonical business timezone for company and
> attendance operations. User, browser, and device timezone must never determine an attendance
> result.**

This principle has three distinct layers, and the rest of this document is careful not to collapse
them into one:

| Layer | Rule | Why it is not the same as the other two |
|---|---|---|
| **Business invariant** | Indian HRMS business operations run on `Asia/Kolkata`. This is a product fact, not a configuration option, for V1 | This is what the client is approving — a statement about the business, not the software |
| **Technical capability** | The calculation engine stays timezone-**aware** and can correctly evaluate any valid IANA zone internally (`ShiftVersion`/`Branch`/`Company` columns, WD-06 precedence) | This is *not* weakened by the business invariant above — it is what lets the engine be proven zone-independent (§4.1 below) without deleting or hard-coding anything. Removing it would not make India V1 more correct; it would only make a future non-India tenant more expensive |
| **External user input** | An Indian HR user, admin, or anonymous registrant must never be able to enter an arbitrary or invalid timezone value | This is the actual attack surface (`NEW-01`, `NEW-04`, `SR-09`) — it is a validation-boundary problem, not an architecture problem, and is fixed at the boundary, not by weakening the engine |

**Consequence:** this document does **not** propose forcing `ShiftVersion.timezone` or
`Branch.timezone` to literally equal `Asia/Kolkata`. Doing so would break 15 existing test literals
and 22 live dev rows that carry `UTC` (§4.1 below), and would delete the very property that makes the
engine provably zone-independent. The business invariant is enforced at the one tier an external
party actually controls — registration and profile edit (§6) — and everywhere else it holds as a
**consequence** of WD-06 resolving to `Asia/Kolkata` by default, not as a schema-level lock.

---

# 0. FINAL DECISION REGISTER — ALL DECISIONS SELECTED

**This section supersedes the "recommended answer" framing everywhere else in this document.** Where
any later section says *"Recommended: X"*, X is now **`SELECTED`**. No section below leaves the
implementation free to choose between X and Y. The `DEC-TZ-XX` IDs used here are the client sign-off
IDs defined in the sign-off page that follows; the `CD-` aliases are the internal IDs used in §19 and
§21. **No ID has been renamed and no new ID has been created** — `CD-7`/`CD-8` were already added in
the preparation pass.

The four categories the product owner asked to be kept distinct:

| Category | Meaning | Items |
|---|---|---|
| **Business decisions** | Approved policy the client/product owner owns | `DEC-TZ-01`…`DEC-TZ-09` (= `CD-1`…`CD-8`) |
| **Engineering decisions** | Technical choices engineering may make alone | `ED-1`…`ED-16` (§20) — all resolved, none outstanding |
| **Deferred** | Intentionally **not** implemented in India V1 | `DEC-TZ-09` night-OT `WINDOW`/`BOTH`; effective-dated timezone config; punch rounding; ±2h pad width; employee-level timezone; offline/mobile; geofencing; biometric ingestion; DST business rules |
| **Rejected options** | Considered and deliberately not selected | Listed per decision below, under *Rejected* |

---

### `DEC-TZ-01` — Authoritative attendance clock · *(no `CD-` alias — restates an approved architecture decision)*

- **Question:** For an employee self-service punch, whose clock sets the official time — the device's or the server's?
- **Selected decision:** **The HRMS server's receipt time is authoritative.** The self-service path has no `punch_time` field at all; the device clock is never read, compared, or stored. HR on-behalf entry and regularization remain client-time-accepting, because both are, by definition, assertions about a time the server did not observe.
- **Reason:** A payroll-grade system cannot have a clock any user can set. Removing the field is a structural control, not a threshold — there is nothing left to forge.
- **Industry/safety rationale:** Centralized attendance systems universally server-stamp the official punch while keeping a separately-permissioned administrative correction path. Fraud resistance and auditability both rank above convenience (§Part 21 priority order).
- **Implementation requirement:** Phase 1 — `POST /attendance/punches/me` carries `{direction, reference?, idempotency_key?}` only; `punch_time = datetime.now(UTC)` at request receipt; `source` server-assigned.
- **Test requirement:** `punch_time` posted to `/me` → 422. `source` posted to either route → 422. Self-punch `punch_time` equals server receipt time, not any client value.
- **Client approval required:** No — reconfirmation of an already-approved architecture decision.
- **Status:** ✅ **SELECTED**
- **Rejected:** *(B)* accept client time within a bounded skew, storing both — rejected because it keeps a forgeable field alive to solve a problem the structural fix eliminates entirely. *(C)* keep current behaviour with detective alerting — rejected: this is the defect the programme exists to close.

### `DEC-TZ-02` = `CD-2` — India timezone principle and registration gate

- **Question:** Must a company created through public sign-up be on `Asia/Kolkata`, or may it pick any of ~600 IANA zones?
- **Selected decision:** **Restrict both `/register` and `PATCH /company/profile` to a settings-driven allow-list, defaulting to `["Asia/Kolkata"]`.** Enforced server-side; the frontend narrows its `<select>` to match the API-provided list, never to define it.
- **Reason:** `/register` is public and unauthenticated. Today an anonymous visitor can create a tenant whose every attendance calculation runs in `America/Los_Angeles`. Hiding the widget changes what one client sends; it does not change what the API accepts.
- **Industry/safety rationale:** Region-locked V1 launches hard-restrict the public entry point and expand the allow-list later as configuration, avoiding retrospective tenant clean-up.
- **Implementation requirement:** Phase 2 — `settings.allowed_company_timezones`; validator order is (1) IANA membership, (2) alias canonicalisation, (3) allow-list.
- **Test requirement:** Non-Indian zone at registration → 422 naming the allowed set. Same at profile update. `Asia/Calcutta` accepted and canonicalised. Existing companies unaffected.
- **Client approval required:** Yes — **granted**.
- **Status:** ✅ **SELECTED**
- **Rejected:** Leaving selection open to the world — the India invariant would then hold only by convention and could be broken by the next sign-up. Hard-coding the constant instead of a setting — makes expansion a code release rather than a config change.

### `DEC-TZ-03` = `CD-7` — Future-dated punches and clock-skew tolerance

- **Question:** Beyond the unconditional "never later than now" floor, is an additional tolerance needed?
- **Selected decision:** **No additional tolerance for V1.** A punch dated later than server receipt time is refused outright.
- **Reason:** An on-behalf punch is a deliberate human correction about the past, not a live device reading; a skew tolerance exists to absorb imprecise device clocks, which this workflow does not involve. The self-service path cannot express a future time at all after `DEC-TZ-01`.
- **Industry/safety rationale:** Part 5 — a future-dated punch must not be silently accepted. A visible false rejection is preferable to silent acceptance of an impossible timestamp.
- **Implementation requirement:** Phase 1 — typed `FuturePunchTimeError` → 422 on the on-behalf route. No configuration field, no magic number.
- **Test requirement:** On-behalf `punch_time` one second in the future → 422. Far-future (`2099-01-01Z`) → 422.
- **Client approval required:** Yes — **granted (no tolerance)**. Non-blocking either way.
- **Status:** ✅ **SELECTED**
- **Rejected:** A named N-minute grace window — no existing approved rule states a number, and inventing one would be exactly the speculative business rule Part 1 forbids.

### `DEC-TZ-04` = `CD-8` — Timezone changes after attendance exists

- **Question:** Block the change outright, or build effective-dated timezone configuration?
- **Selected decision:** **Block outright.** Once any computed `attendance_day` exists for the affected scope, the company/branch timezone cannot be edited through the ordinary settings path — 409, not a silent accept. A `TRIAL` company with **zero** computed attendance may still be corrected freely. A `CLOSED` period refuses the change **unconditionally**, checked *before* the `TRIAL` hatch.
- **Reason:** Smallest correct mechanism for a single-timezone product; reuses the existing `TRIAL`/zero-rows currency-lock precedent already in the codebase. Effective-dating is architecturally available (mirrors `ShiftVersion`) but is disproportionate scope for a scenario India V1 does not expect.
- **Industry/safety rationale:** Part 7 and Part 17 — historical attendance is payroll evidence and must never silently change because configuration was edited later. Where the system cannot recompute safely, **fail closed**.
- **Implementation requirement:** Phase 3 — `_assert_timezone_change_allowed` becomes `async` and real (`ED-11`); called from **both** `update_company_profile` and `update_branch`; branch scope walks `EmployeeAssignment` history, not the current roster (`ED-12`).
- **Test requirement:** Change refused from both paths with computed attendance in scope. `TRIAL`/zero-days permitted. `CLOSED` period refuses regardless of trial status. Historical rows byte-identical after an attempted change.
- **Client approval required:** Yes — **granted (block)**.
- **Status:** ✅ **SELECTED**
- **Rejected:** Effective-dated timezone versioning — **deferred**, not discarded; the `ShiftVersion` pattern exists to copy if a relocation use case ever appears. Hard-coding `Asia/Kolkata` and deleting the columns — rejected: breaks 22 live rows and 15 test literals and destroys the engine's provable zone-independence.

### `DEC-TZ-05` = `CD-1` ⭐ — Attendance date and period lock

- **Question:** May a punch ever be permanently refused because its payroll period closed, or must the physical fact always be recorded and reconciled?
- **Selected decision:** **Never permanently refuse at entry.** Accept the punch if **either** its local (IST) date **or** the previous local date is not `CLOSED`; refuse only when **both** are closed. Ships **together with** the orphan-punch report. The calculation step keeps its own separate, absolute refusal to write into a locked day.
- **Reason:** The two errors are not symmetric. A false rejection destroys a fact permanently — no orphan row exists to find, and regularization checks the same closed period and is also refused. A false acceptance is inert, visible, and recoverable.
- **Industry/safety rationale:** Part 21 — *"false rejection that is visible and correctable is preferable to silent acceptance that produces incorrect payroll"* — here the *rejection* is the silent unrecoverable one, so the same principle selects acceptance-plus-reconciliation. Only night-shift and early-shift employees in a ~5½-hour band are affected at all.
- **Implementation requirement:** Phase 4 item 4.3 — period-lock basis moves from the punch's **UTC** calendar date to the IST-date-or-previous-IST-date test. Must ship with the orphan report (Phase 8).
- **Test requirement:** The §10.2 boundary table frozen as tests: 00:30, 01:30, 03:00, 05:00, **05:29**, **05:30**, 06:00 IST. The §10.3 mirror case (04:30 IST early day shift) must now be **accepted**, where today it is falsely rejected.
- **Client approval required:** Yes — **granted**.
- **Status:** ✅ **SELECTED**
- **Rejected:** Keeping the UTC-date basis — permanently and silently loses genuine night/early-shift punches at month boundaries. Attendance-date-only basis — the attendance date is an asserted input not available at punch ingestion (§9.3), so it cannot be the ingestion test.

### `DEC-TZ-06` = `CD-3` — Amending the LOCKED `DEC-010` rendering clause

- **Question:** May `DEC-010`'s locked "render in company timezone" clause be amended to "render in the timezone the figure was computed in"?
- **Selected decision:** **Amend it.** For India V1 the two readings are identical, so there is no visible change today.
- **Reason:** Literal compliance would render a non-company-zone branch's figures in a zone they were not computed in — a second bug, not correctness. Amending now costs nothing; amending under production pressure later costs a lot.
- **Industry/safety rationale:** Part 12 — attendance timestamps render in the resolved business timezone, always labelled, never the viewer's browser zone.
- **Implementation requirement:** Phase 6 — update `docs/adr/0010-*.md`'s rendering clause to name the WD-06-resolved zone. The rendering **code** proceeds regardless.
- **Test requirement:** A fixed instant renders `09:05 IST` with the test runner's `TZ=America/New_York`. Every attendance time carries a zone label.
- **Client approval required:** Yes — **granted**.
- **Status:** ✅ **SELECTED**
- **Rejected:** Leaving `DEC-010` literal — forces engineering either to violate a locked decision or to knowingly ship an incorrect rendering rule.

### `DEC-TZ-07` = `CD-4` — Automatic attendance calculation schedule

- **Question:** Should attendance calculate automatically, at what time, and over how many trailing days?
- **Selected decision:** **Daily at 09:30 `Asia/Kolkata`, trailing 3 days**, plus a best-effort non-blocking calculation immediately after each punch insert.
- **Reason:** 09:30 IST is after the outer edge of a `22:00→06:00` shift's ±2h pad (08:00 IST) and comfortably before HR's morning review. The 3-day trailing window absorbs a multi-day outage and picks up late regularizations without a second manual step.
- **Industry/safety rationale:** Part 15 — the trigger must be explicit, idempotent, retry-safe and observable. `calculate()` is full-row replacement, so repeat and overlap are safe by construction.
- **Implementation requirement:** Phase 8 — `attendance/tasks.py` on the existing `leave/tasks.py` two-tier fan-out; one Beat entry; **must** call `business_today()` explicitly, never `datetime.now(UTC).date()`, with the reason documented in the task docstring so a future schedule move cannot reintroduce `SR-05`.
- **Test requirement:** Two consecutive runs produce identical rows. A punch alone creates an `attendance_day` with no human action. Locked days and `CLOSED` periods are skipped.
- **Client approval required:** Yes — **granted (09:30 IST, 3 days)**.
- **Status:** ✅ **SELECTED**
- **Rejected:** Leaving calculation manual — a payroll period cannot be finalized unless a human remembers to press a button for every employee. An earlier schedule — would sit inside the 00:00–05:29 IST skew band.

### `DEC-TZ-08` = `CD-5` — On-behalf punch backdating limit

- **Question:** Is "not in the future, not inside a `CLOSED` period" a sufficient backdating limit, or is a numeric cap required?
- **Selected decision:** **No additional numeric cap for V1.** Rely on the structural limit, plus the employee's own employment start date as a data-integrity floor.
- **Reason:** The payroll-period boundary is already the point past which a correction cannot affect a finalized figure. `AttendancePolicyVersion` has no backdating column; adding one is a migration and a default nobody has chosen.
- **Industry/safety rationale:** Part 6 — backdated attendance is controlled, auditable, and reason-bearing; the control is the approval/audit path, not an arbitrary day count.
- **Implementation requirement:** Phase 1 — `reference` (the reason) mandatory on the on-behalf route; full audit entry; `_ensure_date_open` reused unchanged.
- **Test requirement:** On-behalf punch into a `CLOSED` period → 422/409. Without a reason → 422. Predating employment start → 422.
- **Client approval required:** Yes — **granted (no cap)**.
- **Status:** ✅ **SELECTED**
- **Rejected:** A configurable `max_backdated_days` — legitimate, but new scope requiring its own migration and default; recorded as deferred, not refused.

### `DEC-TZ-09` = `CD-6` — Night overtime premium activation

- **Question:** Implement `night_ot_mode`'s inert `WINDOW`/`BOTH` modes, or withdraw them?
- **Selected decision:** **Defer — neither implement nor withdraw in this programme.** Document the fields as currently inert so HR is not misled meanwhile.
- **Reason:** This is a pay-policy decision about *which minutes earn a premium*, entirely independent of timezone correctness. The local-time computation feeding it is already correct; what is missing is the business rule that reads it.
- **Industry/safety rationale:** Part 22 — do not change payroll calculations inside a timezone remediation. Blending a proven-correct timezone change with an undecided pay policy would make Phase 4's recompute blast radius impossible to attribute.
- **Implementation requirement:** Documentation only. **`calculation.py:1237` must not be touched** while `match_breaks` is fixed in the same file.
- **Test requirement:** None — no behaviour changes.
- **Client approval required:** Yes — **granted (defer)**.
- **Status:** ✅ **SELECTED — DEFERRED**
- **Rejected:** Implementing `WINDOW`/`BOTH` here — out of scope. Withdrawing the enum values — a schema/UI change with its own migration, equally out of scope for a timezone release.

---

**Consequence for the phase plan:** §21's gating notes (*"Phase 4's period-lock item waits on CD-1"*,
etc.) are now **discharged** — `CD-1`…`CD-4` are answered above, so every phase item proceeds. The
remaining constraints are the `BLOCKED` facts in §24 (`B4`, `B5`, `B8`), which are **not decisions**
and cannot be selected here — they are production/legal facts that must be established before
production deployment, and they are carried into the completion report as explicit residual risk.

---

## CLIENT SIGN-OFF PAGE

**This section is self-contained.** It is written to be extracted and sent to the client/product
owner on its own — nothing below requires reading the engineering sections that follow. Every item
traces back to a specific section of this document if more detail is ever wanted, but no detail is
required to approve.

Nine items, in three groups — each is marked accordingly in its own "why we need your decision" line:

- **Gates a specific implementation phase** (`DEC-TZ-02`, `DEC-TZ-05`, `DEC-TZ-06`, `DEC-TZ-07` — the
  same four decisions this document calls `CD-1`…`CD-4` elsewhere): these need at least a provisional
  answer before the phase they gate can complete, though every *other* phase proceeds without them.
- **Genuinely open, but ships with a safe, stated default if left unanswered** (`DEC-TZ-03`,
  `DEC-TZ-04`, `DEC-TZ-08`): a signature closes the loop; silence is not a blocker.
- **A reconfirmation of a decision already made upstream, or a deferral with no current effect**
  (`DEC-TZ-01`, `DEC-TZ-09`): included so one signature covers the whole picture, not because either
  is newly in question.

> **Cross-reference note for engineering:** the internal decision IDs used elsewhere in this document
> (`CD-1`…`CD-8`, in §19's Client Decision Register and throughout the phase plan, §21) map onto these
> `DEC-TZ-XX` IDs as follows —
> `DEC-TZ-02`=`CD-2` · `DEC-TZ-03`=`CD-7` (new) · `DEC-TZ-04`=`CD-8` (new) · `DEC-TZ-05`=`CD-1` ·
> `DEC-TZ-06`=`CD-3` · `DEC-TZ-07`=`CD-4` · `DEC-TZ-08`=`CD-5` · `DEC-TZ-09`=`CD-6`.
> `DEC-TZ-01` (authoritative clock) has no `CD-` alias — it restates an architecture decision already
> approved upstream (`DEC-TZ-01` Option A in the original remediation register, an unrelated ID
> namespace from a prior document) and was never an open item in this gate's own `CD-` register.

---

### DEC-TZ-01 — Authoritative clock

**Business question.** When an employee taps "Punch In" on their phone or laptop, whose clock decides
the official time — the employee's device, or HRMS's own server?

**Why we need your decision.** Device clocks can be wrong, manually changed, or simply different from
each other; a system with no single authoritative clock cannot produce attendance figures anyone can
trust for payroll. *(This is a reconfirmation, not a new question — the underlying architecture
decision was already approved upstream as `DEC-TZ-01` Option A in the original remediation register;
it is restated here so this final gate carries one complete, signable record.)*

**Recommended industry/practical approach.** Centralized attendance systems universally treat the
server as the single source of truth for the *official* punch time, while still allowing a trained
administrator to enter a corrected time by hand when a device genuinely failed — the two are not the
same permission and must not be confused.

**Recommended answer.** The HRMS server's own clock is authoritative for every employee self-service
punch. The employee's device or browser clock is never read, stored, or compared for a self-service
punch. HR administrators retain the ability to enter a specific past time on an employee's behalf,
visibly and with a mandatory reason, for genuine corrections.

**If approved.** Every "Punch In"/"Punch Out" from the employee app or web portal is timestamped the
instant the server receives it — never a time the phone or browser reports. HR's "enter a missed
punch" workflow is unaffected and keeps working exactly as it does today, with the addition of a
mandatory reason field and an audit trail.

**If rejected.** The alternative is trusting a client-supplied time for ordinary punches, which is the
exact defect this whole programme exists to close (`F-01`/`F-02`/`F-03`) — an employee (or malware on
their device) could set their phone's clock back and log an earlier arrival. Not recommended under any
circumstance for a payroll-grade system.

**Client decision:** ☑ **APPROVED** ☐ REJECTED / CHANGE REQUIRED — *selected 2026-09-15, §0*

*(Full detail: §7. Engineering resolution: `ED-4`, §20.)*

---

### DEC-TZ-02 — India timezone principle and registration gate

**Business question.** Should HRMS enforce that every company created through the public sign-up page
is on Indian time (`Asia/Kolkata`), or should a new company be free to pick any of the world's ~600
timezones at sign-up?

**Why we need your decision.** Today, sign-up shows the entire world timezone list with no check
tying it to India — an anonymous visitor could, right now, create a company running attendance in
`America/Los_Angeles` on a product that is India-only for V1. This also determines whether an existing
admin may later change their own company to a non-Indian zone.

**Recommended industry/practical approach.** Region-locked V1 launches typically hard-restrict the
public entry point to the supported region and expand the allow-list later as a configuration change,
not a re-release — this avoids ever having to "clean up" incorrectly-configured tenants after the fact.

**Recommended answer.** Restrict both company sign-up and the company-profile timezone field to
`Asia/Kolkata` only, for V1. Expanding this later requires a configuration change, not new code.

**If approved.** Every company created through sign-up is automatically and permanently on Indian
time; an admin cannot switch a live company to a foreign timezone by mistake or otherwise. Nothing
about existing companies changes — all of them already resolve to `Asia/Kolkata` or its legacy alias.

**If rejected.** Company timezone selection stays open to the world. The India-only invariant this
programme is built around then holds only by convention, not enforcement, and can be silently broken
by the very next sign-up or the very next profile edit.

**Client decision:** ☑ **APPROVED** ☐ REJECTED / CHANGE REQUIRED — *selected 2026-09-15, §0*

*(Full detail: §6. Also tracked internally as `CD-2`. Engineering resolution: `ED-3`, §20.)*

---

### DEC-TZ-03 — Future-dated punches and clock-skew tolerance

**Business question.** If HR enters a punch on an employee's behalf, should the system simply refuse
any time that is later than right now (the unconditional floor), or should there be an additional,
specific tolerance — e.g., "up to 5 minutes ahead, to absorb minor clock differences between systems"?

**Why we need your decision.** No existing, approved rule in the system currently states a specific
tolerance value. The unconditional floor — a punch may never be timestamped later than the moment the
server receives the request — requires no number and ships regardless of this decision. A *specific*
allowed tolerance beyond that is a genuinely open, small, non-blocking question with no existing answer
to point to.

**Recommended industry/practical approach.** Ship the unconditional floor alone for V1 — an on-behalf
punch is a deliberate, human-entered historical correction, not a live device reading, so there is no
legitimate reason for one to be dated even slightly in the future; a skew tolerance exists mainly to
accommodate imprecise device clocks, which this workflow does not involve.

**Recommended answer — `CLIENT DECISION REQUIRED`, explicitly non-blocking.** No additional tolerance
for V1; a punch dated later than the current server time is refused outright, with no grace window.
**This does not block implementation** — it is the default V1 ships with unless a specific tolerance
is requested.

**If approved (or left silent).** Any attempt to enter a future-dated punch is refused immediately
with a clear error. This cannot realistically inconvenience a genuine correction, since on-behalf
punches are, by definition, about the past.

**If a tolerance is requested instead.** Engineering adds the specific number of minutes/hours you
specify as an additional allowance on top of the unconditional floor — a small, independent change,
not a blocker to anything else in this programme.

**Client decision:** ☑ **APPROVED — no tolerance, hard floor** ☐ SPECIFY A TOLERANCE: __________ minutes — *selected 2026-09-15, §0*

*(Full detail: §8.2's "far-future bound" row. Also tracked internally as `CD-7` (new, added to §19 in
this pass — distinct from `CD-5`/`DEC-TZ-08` below, which covers backdating into the *past*, not the
future). Engineering resolution: `ED-6`, §20.)*

---

### DEC-TZ-04 — Timezone changes after attendance already exists

**Business question.** If an HR administrator changes a company's or branch's timezone *after*
attendance has already been recorded and calculated under the old timezone, should the system
**block that change outright** (until it is proven safe), or should it **create a new configuration
that only applies going forward**, leaving the old one in effect for already-recorded days?

**Why we need your decision.** Changing a timezone after the fact can silently change how *already
finalized* attendance is interpreted the next time it is recalculated — the same hours, reinterpreted
against a different clock, can shift what looks like a late arrival, an early departure, or overtime.
This is a genuine business-behaviour choice, not merely an implementation detail, because it decides
what an HR administrator is allowed to do and when they are told "no."

**Recommended industry/practical approach.** For a single-timezone (India-only) product, the safest
and cheapest correct answer is to **block the change outright** once any attendance has been computed
under the current configuration, and require the (rare, essentially hypothetical, for an India-only
product) correction to go through a deliberate, audited, one-off data-repair procedure instead of an
ordinary settings edit. Building a full effective-dated ("apply only from a future date") mechanism for
a value that, in an India-only product, essentially never needs to change is disproportionate scope.

**Recommended answer.** **Block the change.** Once a company or branch has any computed attendance
day, its timezone cannot be edited through the ordinary profile/branch-settings screen — the request
is refused with a clear message, not silently accepted. A brand-new company or branch with **zero**
computed attendance (e.g., during initial trial setup) is unaffected and may still be corrected freely.

**If approved.** HR administrators can no longer accidentally (or deliberately, without engineering
involvement) change the effective timezone of historical attendance. A genuine timezone correction
for a live tenant becomes a deliberate, logged, assisted procedure — which is appropriate, because it
should be rare and should be reviewed, not a routine settings change.

**If rejected — the effective-dating alternative.** The system instead versions the timezone the same
way shift schedules are already versioned: a change takes effect only from a chosen future date, and
every already-computed day keeps using the timezone that was in effect for it. This is architecturally
consistent with how `ShiftVersion` already works, but it is materially more implementation and testing
effort for a scenario an India-only V1 is not expected to encounter, and is recommended only if the
client specifically anticipates needing mid-flight timezone corrections on live tenants.

**Client decision:** ☑ **APPROVED — block the change** ☐ REJECTED — build effective-dating instead — *selected 2026-09-15, §0*

*(Full detail: §12. Also tracked internally as `CD-8` (new, added to §19 in this pass). Engineering
resolution: `ED-11`/`ED-12`, §20.)*

---

### DEC-TZ-05 — Attendance date and period lock (night-shift punches near a payroll cutoff)

**Business question.** For a night-shift employee whose shift starts before midnight and ends after
it, if their punch happens to fall in the roughly 5½-hour window between midnight and dawn, right at a
month-end payroll cutoff — should the system ever **permanently refuse** that punch because the
period already closed, or should it **always record the physical fact of the punch** and let HR
reconcile it afterwards?

**Why we need your decision.** This affects **only** night-shift and very-early-shift employees, in a
narrow window around a payroll period boundary. Every ordinary day-shift employee is unaffected either
way — the two possible answers produce identical results for them. §10 of this document proves, by
walking through the exact clock times, that today's behaviour has an asymmetric flaw: it can
permanently lose a legitimate early-shift punch (an unrecoverable fact), while separately, harmlessly,
accepting a late-night punch that never actually changes a finalized figure.

**Recommended industry/practical approach.** Attendance systems generally treat "we don't have a
punch" as a worse outcome than "we have an extra punch to review," because the first is unrecoverable
and the second is a five-minute reconciliation task for HR.

**Recommended answer.** Never permanently refuse a punch at entry. Accept it if either its local date
or the previous local date is still open, and surface anything that turns out to belong to an
already-closed period in a dedicated report HR reviews — it never silently rewrites a finalized
figure, because the calculation step has its own, separate, absolute lock on closed periods.

**If approved.** A night-shift or early-shift employee's punch is never lost at a month boundary. A
small number of punches that land in the ambiguous window may appear in a review report even though
they will not affect any already-finalized number — HR simply confirms nothing is wrong.

**If rejected.** Some genuine punches from night-shift and early-shift employees will be **permanently
and silently lost** whenever they fall in this narrow window at a payroll cutoff, with no report and
no recovery path. Support would need a fully manual, ad-hoc process for these cases.

**Client decision:** ☑ **APPROVED** ☐ REJECTED / CHANGE REQUIRED — *selected 2026-09-15, §0*

*(Full detail: §10. Also tracked internally as `CD-1`. Engineering resolution: `ED-2`, §20.)*

---

### DEC-TZ-06 — Amending the locked "render in company timezone" rule

**Business question.** An existing, formally locked engineering decision says attendance times should
always be *displayed* in the company's timezone. May that rule be updated to say "displayed in
whichever timezone the figure was actually *calculated* in" instead?

**Why we need your decision.** For India V1 the two are identical — every company, branch, and shift
resolves to `Asia/Kolkata` — so this has **zero visible effect today**. It matters the day a company
ever has a branch in a different zone (not planned for V1, but the underlying architecture already
supports it): without this amendment, a branch's attendance would display in the *company's* zone
rather than the zone it was actually computed in, which is a display bug, not a feature. Because the
original rule is formally locked, engineering is not permitted to change its meaning without this
sign-off, even though the change is free today.

**Recommended industry/practical approach.** Amend the documentation now, while it costs nothing, so
the display rule is already correct if and when a second timezone is ever introduced, rather than
discovering the mismatch under production pressure later.

**Recommended answer.** Approve the amendment. No visible change for India V1.

**If approved.** The locked rule is updated to say "render in the timezone the figure was computed
in," which today always equals the company's timezone, so nothing on screen changes.

**If rejected.** Engineering ships the correct behaviour anyway for India V1 (since the two readings
are identical today) but cannot formally update the locked documentation, leaving a discrepancy between
what the rule says and what the system will need to do the day a second timezone exists.

**Client decision:** ☑ **APPROVED** ☐ REJECTED / CHANGE REQUIRED — *selected 2026-09-15, §0*

*(Full detail: §13.3. Also tracked internally as `CD-3`. No engineering blocker either way for V1.)*

---

### DEC-TZ-07 — Automatic attendance calculation schedule

**Business question.** Right now, an employee's attendance figures do not exist until a human manually
presses "Calculate." Should this happen automatically every day instead, and if so, roughly what time,
and how many trailing days should each run double-check for late corrections?

**Why we need your decision.** Without this, a payroll period cannot be finalized unless someone
remembers to manually calculate every employee's attendance first — there is currently no automatic
path from "punches recorded" to "attendance exists."

**Recommended industry/practical approach.** Run once daily, after the last shift of the previous
business day has fully closed out (including its allowed grace window), and re-check a small trailing
window of recent days so that late regularizations or corrections are automatically picked up without
a second manual step.

**Recommended answer.** Run daily at **09:30 India time**, re-checking the trailing **3 days**. This
is after every shift's punch window has closed for the previous day and comfortably before HR's typical
morning review.

**If approved.** Attendance figures exist every morning without anyone pressing a button, and a
payroll period can be finalized on schedule.

**If rejected / different numbers supplied.** Engineering implements whatever schedule and window you
specify instead — the mechanism itself does not depend on the specific numbers, only the numbers need
your sign-off.

**Client decision:** ☑ **APPROVED — 09:30 IST, 3-day window** ☐ SPECIFY: time ____ window ____ days — *selected 2026-09-15, §0*

*(Full detail: §16. Also tracked internally as `CD-4`. Engineering resolution: architecture in §16,
`ED-8` for the supporting lock.)*

---

### DEC-TZ-08 — On-behalf punch backdating limit

**Business question.** May an HR administrator enter a punch for any date in the *past*, as long as
that date's payroll period is still open — including one dated several months back — or should there
be a specific maximum number of days an on-behalf punch may be backdated?

**Why we need your decision.** This is the mirror question to `DEC-TZ-03` above (which covers dates in
the *future*): no existing, approved rule in the system currently states a specific backdating limit,
and no configuration field exists to hold one today. The structural limit alone — not in the future,
and not inside an already-closed payroll period — is already a real, tested, enforced control and
requires no new field.

**Recommended industry/practical approach.** Rely on the payroll-period boundary as the practical
backdating limit, since it is already the point past which a correction can no longer affect a
finalized figure anyway — a separate, shorter numeric cap mainly adds friction without closing any
additional risk for a small HR team correcting genuine missed punches.

**Recommended answer — `CLIENT DECISION REQUIRED`, explicitly non-blocking.** No additional numeric
cap for V1; rely on "not in the future, not inside a closed period." **This does not block
implementation** — it is the default V1 ships with unless a specific number of days is requested.

**If approved (or left silent).** HR may correct any past punch inside an open payroll period, however
old, with a mandatory reason and a full audit trail — matching today's practical flexibility, with a
real, tested safety boundary added on top.

**If a limit is requested instead.** Engineering adds a configurable "maximum backdating window" field
to the attendance policy, with your specified number of days as the default — additional scope
requiring its own database migration, scheduled as a later phase rather than folded into Phase 1.

**Client decision:** ☑ **APPROVED — no numeric limit for V1** ☐ SPECIFY A LIMIT: __________ days — *selected 2026-09-15, §0*

*(Full detail: §8.2's "far-past bound" row. Also tracked internally as `CD-5`. Engineering resolution:
`ED-6`, §20.)*

---

### DEC-TZ-09 — Night overtime premium activation

**Business question.** HRMS currently lets an administrator configure a "night overtime window" and a
mode (`SHIFT_FLAG`, `WINDOW`, or `BOTH`) — but two of those three modes are silently non-functional
today: configuring them has no effect on anyone's pay. Should this feature be built out to actually
work as configured, or should the non-functional options be removed from the settings screen so
nobody configures something that silently does nothing?

**Why we need your decision.** This is a pay-calculation policy question — *which* overtime minutes
earn a night premium — completely independent of the timezone work in this programme. It is listed
here only so it is not forgotten, not because this programme needs it answered to proceed.

**Recommended industry/practical approach.** Decide this as its own, separate initiative with its own
sign-off, once there is time to specify precisely which minutes should qualify — do not fold a
pay-policy decision into a timezone-correctness release.

**Recommended answer.** **Defer.** Do not implement or remove anything in this programme; add a note
to the internal rule documentation stating the two modes are currently inert, so support and HR are
not misled in the meantime.

**If approved (deferred).** Nothing changes for now; the inert modes remain visible but documented as
non-functional until a dedicated decision is made.

**If you want this addressed now instead.** Tell us, and it becomes a separate, explicitly-scoped
follow-on piece of work — it is deliberately kept **out of** this programme's phases so a pay-policy
decision is never made as a side effect of a timezone fix.

**Client decision:** ☑ **DEFER — no action needed now** ☐ ADDRESS NOW AS SEPARATE WORK — *selected 2026-09-15, §0*

*(Full detail: §15. Also tracked internally as `CD-6`. Blocks nothing in this programme either way.)*

---

**Summary for the client:** of the nine items above, **six restate a decision this document's
engineering analysis has already made with high confidence** (`DEC-TZ-01`, `DEC-TZ-02`, `DEC-TZ-04`,
`DEC-TZ-05`, `DEC-TZ-06`, `DEC-TZ-09`) and exist mainly so one signature closes the loop; **two are
genuinely open numeric questions that ship with a safe default if left unanswered** (`DEC-TZ-03`/
`DEC-TZ-08`); and **one (`DEC-TZ-07`) needs a specific schedule confirmed before the automatic
calculation phase can be built**, though every other phase proceeds without it.

---

# 1. SR-01 — CROSS-MIDNIGHT BREAK MATCHING: FINAL APPROACH

**Traces to:** `F-05` (audit) → remediation §12 (Approach B selected) → plan §10.4 (adopts Approach B)
→ spec §14 (`SR-01`: Approach B disproven by execution) → **this gate: Approach A is final.**

## 1.1 The code-level comparison

**Function under change:** `match_breaks` — [`apps/api/src/hrms/modules/attendance/calculation.py:574-617`](../../apps/api/src/hrms/modules/attendance/calculation.py#L574). Called from two sites, neither of which currently passes an `attendance_date` ([`:1119`](../../apps/api/src/hrms/modules/attendance/calculation.py#L1119), [`:1322`](../../apps/api/src/hrms/modules/attendance/calculation.py#L1322)).

**Existing precedents in the same codebase, both already wrap-aware:**

- `_derive_cross_midnight` — [`organisation/service.py:2069-2087`](../../apps/api/src/hrms/modules/organisation/service.py#L2069) — `is_cross_midnight = end_time < start_time`. This **is** a time-of-day inference; it is not avoided anywhere, it is computed once at publish and stored.
- `_interval_contains` — [`organisation/service.py:2055-2067`](../../apps/api/src/hrms/modules/organisation/service.py#L2055) — projects onto a 1440-minute clock anchored at the outer interval's start, explicitly to validate a break that wraps past midnight. **This already permits and validates a `01:00–02:00` break on a `22:00→06:00` shift as a legal, publishable configuration.**

**Six scenarios, executed against the shipped `match_breaks` and against both candidate fixes** (`Asia/Kolkata`, 2026-09-15 — full reproduction in spec §14.2):

| # | Configuration | Gap | **Today (unfixed)** | **Approach A**<br>wrap-aware time-of-day | **Approach B**<br>UTC span, roll end forward |
|---|---|---|---|---|---|
| 1 | Day break `13:00–14:00` | 13:15 | ✅ matched, paid | ✅ matched | ✅ matched |
| 2 | Night break `23:30–00:30` | 23:45 | ❌ unmatched | ✅ matched | ✅ matched |
| 3 | Night break `23:30–00:30` | 00:05 (D+1) | ❌ unmatched | ✅ matched | ✅ matched |
| 4 | **After-midnight break `01:00–02:00` on `22:00→06:00` shift** | 01:15 (D+1) | ✅ **matched, paid** | ✅ matched | 🔴 **REGRESSES — unmatched** |
| 5 | `FLEXIBLE_DURATION` window `23:00–01:00` | 23:30 | ❌ unmatched | ✅ matched | ✅ matched |
| 6 | Night break `23:30–00:30`, no over-match guard | 22:15 | ✅ correctly unmatched | ✅ unmatched | ✅ unmatched |

## 1.2 Scored comparison

| Approach | Existing scenarios preserved | New scenarios fixed | Regression risk | Complexity | Recommendation |
|---|---:|---:|---|---|---|
| **A — wrap-aware time-of-day comparison** | **2 / 2** (cases 1, 4) | **3 / 3** (cases 2, 3, 5) | **None** — the wrap branch is reachable only when `end < start`, so no currently-matching gap can start matching a different break (case 6 is the guard) | **Lowest** — ~6 lines, one function, **no signature change**, **no call-site change**, line 586 (`gap_start.astimezone(tz).time()`, the correct conversion order, `PC-15`) untouched | ✅ **SELECTED** |
| **B — UTC span from attendance date, roll end forward** | **1 / 2** (fails case 4) | 3 / 3 | 🔴 **Confirmed regression** on an ordinary, already-published, already-working night-shift configuration | Higher — signature change at both call sites, ~25 lines, rewrites a function that already works for cases 1 and 6 | ❌ **Rejected** |
| **C — do nothing / withdraw midnight-spanning breaks from the product** | 2 / 2 | 0 / 3 | None, but leaves a **certain, silent, always-against-the-employee** payroll defect live | Zero | ❌ Not considered further — `F-05` is an unambiguous CODE BUG (remediation §4.1), not a policy question |

## 1.3 Why the remediation document's objection to Approach A does not hold

Remediation §12.6 rejected Approach A because it *"infers the midnight cross from the column
values — the exact inference pattern `is_cross_midnight` exists to avoid."* **This is not what
`is_cross_midnight` avoids.** `_derive_cross_midnight` (§1.1 above) computes precisely that
inference — `end_time < start_time` — once, at publish, and stores the result so it need not be
re-inferred at calculation time for the *shift's own span*. It does not establish a rule against
ever comparing `start` and `end` by value; it establishes a rule against *re-deriving the shift's own
cross-midnight flag* at calculation time, which `match_breaks` never did and does not need to.

## 1.4 The exact invariant the implementation must preserve

```text
For a break window (start, end):

    if end is None or end == start:
        match only when gap_start_local == start                 (a point-in-time break, not a
                                                                     24-hour "always matches" window)
    elif start < end:
        match when start <= gap_start_local <= end                (ordinary same-day window,
                                                                     UNCHANGED from today)
    else:  # start > end — the window wraps past midnight
        match when gap_start_local >= start OR gap_start_local <= end

Apply identically to FIXED_WINDOW (start_time/end_time) and FLEXIBLE_DURATION (window_start/window_end).
Do not touch the UTC → local conversion that produces gap_start_local (line 586, PC-15).
Do not change match_breaks's signature or either call site.
```

**Decision status: `GREEN`.** No client input required — `F-05` is a code bug against the product's
own break-configuration contract (remediation §4.1), and the fix is now proven correct by execution
of all six governing scenarios, not merely argued.

---

# 2. SR-02 — PUNCH ENDPOINT DESIGN: FINAL API SHAPE

**Traces to:** `F-01`/`F-02` (audit) → plan §5.1 ("two punch endpoints") **contradicting** plan §7.1
(one endpoint, two behaviours) → spec §11.3 (`SR-02`: neither reading is implementable as a single
endpoint) → **this gate: two endpoints, final.**

## 2.1 The actual endpoint today

**VERIFIED**, [`attendance/router.py:752-788`](../../apps/api/src/hrms/modules/attendance/router.py#L752):

```python
@router.post("/attendance/punches", status_code=status.HTTP_201_CREATED)
async def create_punch(body: PunchCreate, ...):
    target_employee_id = body.employee_id or user.employee_id
    on_behalf = body.employee_id is not None and body.employee_id != user.employee_id   # :772
    required_permission = ATTENDANCE_PUNCH_ON_BEHALF if on_behalf else ATTENDANCE_PUNCH
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, required_permission)
```

One route, one schema (`PunchCreate`, `extra="forbid"`, every field optional). **The permission a
caller needs is decided by a value inside the body FastAPI has already had to fully parse and
validate before that decision can be made.** A two-schema design (`PunchCreateSelf` /
`PunchCreateOnBehalf`) cannot be bound to one route, because FastAPI must select a model before the
body's own contents — the very thing that would select it — are available.

## 2.2 Options evaluated

| | Option | Assessment |
|---|---|---|
| **A** | **Two separate routes** — `POST /attendance/punches/me` (self) and `POST /attendance/punches` (on-behalf) | Each binds exactly one schema with `extra="forbid"`. **The permission requirement becomes static** — `Depends(require_permission(ATTENDANCE_PUNCH))` on `/me`, `Depends(require_permission(ATTENDANCE_PUNCH_ON_BEHALF))` on the other — replacing the body-dependent `rbac.resolve_data_scope()` dispatch at `:772-779`. A caller can no longer be routed into the wrong authorization branch by any value they control in the body. **This is a genuine security-boundary improvement, not just a schema-parsing fix.** ✅ **SELECTED** |
| **B** | One endpoint, one union/discriminated schema, validated in the service after the act is determined | Keeps the URL, but `extra="forbid"` can no longer reject `punch_time` on a self-punch at the schema layer — a hand-written service-level check must do it instead, re-creating the exact "conditional validator on a body-decided branch" shape that caused `F-11` (forgeable `source`) in the first place |
| **C** | Keep one endpoint; unconditionally forbid `punch_time` | Removes the legitimate on-behalf correction workflow. **Forbidden outright** — HR must be able to enter a missed punch |

## 2.3 Selected design and its implications

| Dimension | Specification |
|---|---|
| **Design** | Two endpoints. `POST /attendance/punches/me` — self-service, `{direction, reference?, idempotency_key?}`, **no `punch_time` field, no `source` field, no `employee_id` field.** `POST /attendance/punches` — on-behalf, `{employee_id, direction, punch_time: AwareDatetime (required), reference (required — the reason), idempotency_key?}`, **no `source` field on either.** |
| **Authorization** | `/me` requires `ATTENDANCE.PUNCH`. `/attendance/punches` requires `ATTENDANCE.PUNCH_ON_BEHALF`. **Static per-route**, resolved at the dependency layer before the body is read — not derived from body content. If a caller with only `PUNCH` posts someone else's `employee_id` to the on-behalf route, it is a clean 403; if they post their own `employee_id` there, it is accepted (they hold both scopes trivially) but redundant — no ambiguity either way. |
| **Validation** | `punch_time` is **absent as a field** on `/me` (`extra="forbid"` → 422 if sent) and **required + `AwareDatetime`** on the on-behalf route. `source` is never a request field on either — it is server-assigned from which route was called (`WEB`/`MOBILE` for self, `ADMIN` for on-behalf), closing `F-11` in the same change. |
| **Migration** | **None to the database.** `punch.source`'s DB `CHECK` already permits all values that will ever be assigned (`WEB`, `MOBILE`, `ADMIN`, `DEVICE`, `IMPORT`, `API`, `REGULARIZATION` — VERIFIED via `pg_constraint`). This is a router/schema change only. |
| **Compatibility** | **Breaking for the shipped web client**, which always posts to one URL today. Must ship API and web **in the same release** — this is already `IR-1` in the plan and is unaffected by which of A/B/C is chosen. |
| **Tests required** | `H8` — `punch_time` posted to `/me` → 422. `H9` — `punch_time` absent on the on-behalf route → 422. `H6`/`H7` — a `source` field posted to either route is ignored/rejected (schema has no such field, so this becomes "unknown field → 422 under `extra=forbid`"). A caller with only `ATTENDANCE.PUNCH` posting to the on-behalf route → 403. Regularization's direct-insert punch path ([`service.py:4108-4122`](../../apps/api/src/hrms/modules/attendance/service.py#L4108)) is **unaffected** — it bypasses `PunchCreate` entirely today and continues to. |

**Decision status: `GREEN` (design) / `YELLOW` (route naming only).** The *shape* is not a client
decision — it is dictated by what FastAPI can do, and Option A is the only one that gives every
caller-controlled body field zero influence over which authorization branch runs. The **exact route
name** (`/attendance/punches/me` vs. an alternative) is `YELLOW` — an internal engineering
confirmation, not a business question (§19).

---

# 3. SR-05 — LEAVE JOB TIMEZONE / `as_of`: FINAL SCOPE

**Traces to:** spec §18.3 (`SR-05`) → this gate: **fix in this programme, in Phase 7, using the same
`business_today()` helper Phase 4 builds. Not a separate leave-module workstream.**

## 3.1 The defect, re-verified

`leave/tasks.py:36, 85, 110` — **VERIFIED, still current:**

```python
async def _accrue_company_async(company_id: UUID) -> int:
    ...
    return await LeaveAccrualService(session).run_for_company(company_id, as_of=datetime.now(UTC).date())
```

`celery_app.py:26-46` — **VERIFIED, still current:** `timezone=settings.app_timezone_default`
(`Asia/Kolkata`), `enable_utc=True`, and the three relevant crontabs:

```python
"leave-run-monthly-accrual":      crontab(minute=0,  hour=1)   # 01:00 IST, day_of_month=1
"leave-run-comp-off-expiry-sweep":crontab(minute=30, hour=1)   # 01:30 IST, daily
"leave-run-year-end-sweep":       crontab(minute=0,  hour=2)   # 02:00 IST, daily
"leave-run-comp-off-credit-sweep":crontab(minute=0)            # hourly, every hour incl. 00:00-05:00 IST
```

Celery Beat's `timezone=` setting controls **when the crontab fires** (IST wall-clock), not what
`datetime.now(UTC)` returns inside the task body once it does. The two are independent, and this is
the entire defect: the schedule is correctly India-local, the business date computed inside it is not.

## 3.2 Job-by-job trace

| Job | Schedule (IST) | Fires at (UTC instant, example 1 Oct) | Current `as_of` (`datetime.now(UTC).date()`) | Correct business date | Risk |
|---|---|---|---|---|---|
| `leave.run_monthly_accrual` | 01:00, 1st of month | `2026-09-30T19:30Z` | **2026-09-30** | **2026-10-01** | 🔴 **The monthly accrual scheduled for the 1st always runs one calendar day early**, and `_previous_month_bounds(as_of)` (`leave/service.py:1300-1305`) then accrues the *wrong* previous-month window on every single run |
| `leave.run_comp_off_expiry_sweep` | 01:30, daily | `2026-09-30T20:00Z` | previous day | today | 🟠 A comp-off entry whose `comp_off_expiry_date` is exactly "today" is not yet expired when the sweep runs, and expires one day later than configured |
| `leave.run_year_end_sweep` | 02:00, daily | `2026-09-30T20:30Z` | previous day | today | 🟠 `is_leave_year_start(setting, as_of=as_of, ...)` (`leave/service.py:1474`) gates on `as_of`; an employee whose leave year starts "today" is evaluated against yesterday's date and is skipped for a day |
| `leave.run_comp_off_credit_sweep` | hourly, every hour | 6 of 24 runs (00:00–05:00 IST) | previous day (for those 6 runs) | today | 🟡 Lower impact — the sweep is idempotent per `overtime_record_id` (`exists_with_reference`), so a wrong `as_of` this run is corrected by the 09:00 IST run reading the same, by-then-current, facts. The other 18 runs/day are unaffected |
| *(proposed)* `attendance.run_daily_calculation` | 09:30, daily *(Phase 8/`CD-4`)* | `2026-10-01T04:00Z` | would be **2026-10-01** | **2026-10-01** | ✅ **No skew** — 09:30 IST is above the 05:30 IST/UTC-date boundary. Must still call `business_today()`, not `datetime.now(UTC).date()`, so a future schedule change cannot silently reintroduce the bug |

**The monthly accrual is the severe case**, not because the skew is larger, but because it is the one
job the schedule *guarantees* fires in the wrong band every single month — 01:00 IST is always inside
the 00:00–05:29 IST skew window, on every run, forever, until fixed.

## 3.3 Scope decision

> **This is fixed inside the timezone remediation programme, not escalated as a separate leave-module
> defect.** Two reasons: (1) it is the *identical* root cause as `TZ-06` / `NEW-02` — a UTC-derived date
> substituting for a business date — so the fix is the same helper, `business_today(tz)`, applied at a
> third and fourth call site; building that helper and not applying it here would be inconsistent
> with the programme's own stated purpose. (2) It has a **quantifiable, monthly, product-wide payroll
> impact** — every tenant's accrual for every month runs against the wrong previous-month window —
> which makes it higher severity than most items already inside scope, not lower.

**No leave policy changes.** The fix is exclusively: replace `datetime.now(UTC).date()` with
`business_today(company_timezone)` at the four call sites above. `_previous_month_bounds`,
`is_leave_year_start`, `expire_company`'s expiry comparison, and `credit_company`'s idempotency key
are all **unchanged** — only the date fed into them moves from UTC-derived to IST-derived.

**Decision status: `GREEN`.** No business-rule ambiguity — this is a date-derivation bug with a
known-correct fix (`business_today()`, already required by Phase 4 for other call sites). No client
decision is needed to fix *when a job computes the right date*; `CD-4` (§19) still governs the
separate question of **attendance's own** job schedule and trailing window.

---

# 4. SR-09 / `NEW-01` — TIMEZONE VALIDATION POLICY: FINAL RULE

**Traces to:** `TZ-nn` (audit) → remediation `DEC-TZ-11` → spec §4 (`NEW-01`, `SR-09`) → **this gate:
Option B, final.**

## 4.1 The three candidate policies, evaluated for India V1

| # | Policy | Assessment |
|---|---|---|
| **1** | **Strictly allow only `Asia/Kolkata`** on every timezone field (`Company`, `Branch`, `ShiftVersion`) | **Rejected.** Breaks the existing test suite immediately — **VERIFIED, 15 test literals set `timezone="UTC"`** across `test_calculation.py` (×11), `test_attendance_day.py` (×2), `test_shift_roster.py` (×1), `test_regularization.py` (×1) — and **VERIFIED, 22 live dev rows** (11 `branch`, 11 `shift_version`) carry `UTC`. It also deletes the property (`PC-01`) that proves the calculation engine is zone-independent — the only reason international expansion would not require re-proving the engine from scratch |
| **2** | **Allow valid IANA zones; default India-created flows to `Asia/Kolkata`; gate only the *external* entry points (registration, profile edit) to an India allow-list** | ✅ **SELECTED.** Correctness is achieved at the one tier an external, unauthenticated party can set (`/register` — `NEW-04`, §6); `Branch`/`ShiftVersion` remain internal, admin-only, IANA-validated surfaces, because WD-06 (`Shift > Branch > Company`) means a correctly-gated company timezone makes every unset branch/shift resolve to `Asia/Kolkata` anyway |
| **3** | **No validation change; rely on convention** | **Rejected.** This is the status quo and it is the defect — `ShiftVersion.timezone` currently has **no validator at all** (`organisation/schemas.py:1243`, `:1280` — confirmed, `Field(default=None, max_length=64)` only), so a value like `"IST"` is accepted at create/update and fails only at calculation time, as `ZoneInfoNotFoundError` → an unhandled 500 |

## 4.2 Why this is an HR-user path, not only an API-only path (`SR-09`)

**VERIFIED, re-read:** `shift-version-form.tsx:66-71` and `branch-form.tsx:93-97` both render the
timezone field as a free-text `<Input placeholder="Asia/Kolkata">` with **no client-side validation** —
unlike `/register`, which uses a `<select>` populated from `listTimezones()`.

| Surface | Widget | Frontend validation | Backend validation (schema) | Outcome of typing `IST` |
|---|---|---|---|---|
| `/register` | `<select>` | n/a — cannot type | ✔ `organisation/schemas.py:111` | not reachable |
| Branch create / update | free-text `<Input>` | none | ✔ `schemas.py:694`/`:729` | clean **422** |
| **Shift version create / update** | free-text `<Input>` | none | **✘ none, confirmed** | **persisted → `ZoneInfoNotFoundError` → HTTP 500 at every subsequent calculate for every employee on that shift** |

`IST` is the abbreviation every Indian HR user would type for their own timezone. This raises the
finding from *"an API caller could"* to *"an HR administrator will."*

## 4.3 Final policy specification

| Layer | Rule | Enforcement point |
|---|---|---|
| **API validation** | `ShiftVersionCreate.timezone` and `ShiftVersionUpdate.timezone`: reject any value not in `zoneinfo.available_timezones()`, mirroring `BranchCreate.validate_timezone` verbatim. `NULL` **remains valid** — it is WD-06's "inherit from branch/company" signal (7 live rows depend on this) | `organisation/schemas.py` `ShiftVersionCreate` (`:1243`), `ShiftVersionUpdate` (`:1280`) |
| **Publish-time re-check (defence in depth)** | A draft may be created valid and patched to invalid before publish; re-validate inside `_validate_and_derive_for_publish` | `organisation/service.py:2282-2345` |
| **Engine fail-safe (not a validation layer)** | Wrap `ZoneInfo(tz_name)` construction so an unresolvable zone produces a typed `ConfigurationError` → a `CONFIG_ERROR` attendance day (the status already exists in the model), never a bare 500 | `calculation.py` / `attendance/service.py` |
| **Database constraint** | **None added.** A `CHECK` against `available_timezones()` cannot be expressed portably in a Postgres constraint without a lookup table that must itself be kept in sync with the Python `zoneinfo` database on every OS/tzdata upgrade — the schema-layer validator is the correct and sufficient boundary, matching the existing pattern for `Company`/`Branch` |
| **Frontend validation** | Replace the free-text `<Input>` on **both** `shift-version-form.tsx:66` and `branch-form.tsx:93` with the same `listTimezones()` select `/register` already uses. Usability, not the enforcement boundary — the schema validator is what actually protects the data |
| **Import validation** | `employee_import` does not set a shift timezone today (VERIFIED by grep — it imports employees only). **No change required now.** If a future bulk shift-import path is added, it must run through the same `ShiftVersionCreate` schema, not a parallel writer |
| **Migration of existing data** | **None required.** VERIFIED: every `shift_version.timezone` value in the dev database is `UTC` or `NULL`, both valid under the new validator. No row becomes invalid |
| **Error behaviour** | Create/update/publish with an invalid zone → `422` naming the offending value and the accepted format. A **pre-existing** row with an unresolvable zone reaching calculation → `CONFIG_ERROR` attendance day (`ED-10`), never a 500 |

## 4.4 Tests required

| # | Test | Tier |
|---|---|---|
| 1 | `POST /shifts/{id}/versions` with `timezone="IST"` → **422**, never 500 | integration |
| 2 | `PATCH …/versions/{vid}` with `timezone="IST"` → **422** | integration |
| 3 | `POST …/publish` on a draft whose timezone was made invalid → **422** | integration |
| 4 | `timezone=None` on create → accepted; WD-06 falls through to branch, then company | integration |
| 5 | `timezone="UTC"` → accepted *(regression guard for 15 existing test literals and 22 live rows)* | integration |
| 6 | `timezone="Asia/Calcutta"` → accepted *(alias guard, §5)* | integration |
| 7 | A pre-existing row with an unresolvable zone → `CONFIG_ERROR` day, **not** HTTP 500 | integration |
| 8 | End-to-end: an invalid zone can never reach `calculate()` in the first place | integration |

**Decision status: `GREEN`.** No client input required. `ED-1` (§20) settles the mechanism; the only
open item is registration-tier scope, which is `CD-2` (§19) because it is a genuine product-facing
gate, not a validation-layer question.

## 4.5 HR forms — full audit across every module

**Method.** `grep -i "timezone"` was run against every form/dialog component under `apps/web/src`,
module by module, to find every place an HR user (or an employee, for self-service screens) can
possibly type or select a timezone value. **Confirmed zero matches** in the roster, employee,
attendance (punch), regularization, leave-policy/leave-type, and overtime-policy modules — none of
these forms contain a timezone field at all, because none of these entities carry their own timezone;
all of them inherit whichever zone WD-06 resolves for the employee's company/branch/shift.

| Module | Screen(s) checked | Current input | Risk | Final V1 behaviour |
|---|---|---|---|---|
| **Company** | `register/page.tsx`, company profile edit | `<select>` from the full ~600-zone IANA list, no country gate | An anonymous sign-up, or an authenticated profile edit, can pick a non-Indian zone (`NEW-04`) | Filter the `<select>` to the server-provided allow-list (`DEC-TZ-02`/`CD-2`, §6). Backend enforces regardless of what the UI shows |
| **Branch** | `branch-form.tsx:93-97` | Free-text `<Input>`, but **backend already validates** IANA membership (`schemas.py:691-696`) | Low — a bad value is already caught server-side with a clean 422 | Replace the free-text input with the same select used at registration, for usability. **Not a correctness gap today** |
| **Shift version** | `shift-version-form.tsx:66-71` | Free-text `<Input>`, **confirmed zero backend validation** (`organisation/schemas.py:1243`, `:1280` — `max_length=64` only) | **High** — confirmed reachable by an ordinary HR admin typing `IST`, the single most likely value an Indian user would type for their own zone, currently producing an unhandled HTTP 500 at every subsequent calculation for every employee on that shift | Add the same IANA validator as Branch (§4.3); replace the free-text input with the same select. `NULL` remains valid — the "inherit from branch/company" signal |
| **Shift roster** | `roster-entry-dialog.tsx` | **No timezone field — confirmed by grep, zero occurrences** | None — a roster entry assigns a shift/date to an employee; the timezone is resolved later, from the assigned shift, not stored on the roster row | No change required |
| **Employee** | `employee-form.tsx` | **No timezone field — confirmed by grep, zero occurrences** | None — V1 has no employee-level timezone by product decision (India V1 scope, front matter) | No change required |
| **Attendance / punch** | `punch-entry-dialog.tsx` | **No timezone field** — the risk here is a *time* field seeded from the browser clock, a different defect (`F-02`, resolved in §7/§1) | N/A for timezone specifically | No change required for timezone; the time-field defect is addressed in Phase 1 |
| **Regularization** | `regularization-request-dialog.tsx`, `regularization-review-dialog.tsx` | **No timezone field — confirmed by grep, zero occurrences** | None — regularization asserts a punch time against the employee's own resolved shift/company zone | No change required |
| **Leave** | `leave-policy-form.tsx`, `leave-policy-version-form.tsx`, `leave-type-form.tsx`, `leave-combination-rule-form.tsx`, `statutory-leave-minimum-form.tsx` | **No timezone field — confirmed by grep, zero occurrences** (the string "timezone" appears in none of these files) | None — leave dates are calendar dates, not zone-relative instants, by design | No change required. **Separately**, the *jobs* that process leave dates have a UTC-derivation bug (`SR-05`, §3) — that is a scheduling defect, not a form/input defect, and is fixed in Phase 7 |
| **Overtime** | `overtime-policy-form.tsx`, `overtime-policy-version-form.tsx` | **No timezone field — confirmed by grep, zero occurrences.** (`night_window_start`/`_end` are plain time-of-day fields, not timezone fields, and are currently inert — §15) | None, for timezone specifically | No change required |

**The conclusion this audit supports:** the timezone-input attack surface in the entire product is
exactly **three** screens — company registration/profile, branch, and shift version — not the nine
modules a naive reading of "audit all HR forms" might suggest. **Two of the three are already
correctly validated server-side today** (company, branch); **the third (shift version) is the one
confirmed gap**, and it is the cheapest fix in this entire programme (§4.3, one validator copied
verbatim from an existing one).

**On silent abbreviation mapping:** per instruction, this document does **not** propose silently
converting arbitrary HR-typed abbreviations (`IST`, `Indian Standard Time`, etc.) into a valid zone.
The **only** normalisation applied anywhere is the single, explicit, already-justified
`Asia/Calcutta → Asia/Kolkata` alias (§5) — a real IANA legacy name a real browser can genuinely send,
not a guess at user intent. Every other invalid input is **rejected with a clear validation error**,
never guessed at.

**Decision status: `GREEN`.** The full-module sweep confirms no gap exists outside the three screens
already addressed in §4.3 and §6. No client decision required.

---

# 5. `Asia/Calcutta` DATA: FINAL TREATMENT

**Traces to:** `NEW-03` (spec §6) → this gate: **canonicalise on write; migrate the three affected rows
under the `TRIAL`/zero-attendance hatch.**

## 5.1 Inventory — read-only, not modified by this document

| Layer | Count | Detail |
|---|---|---|
| `company.timezone = 'Asia/Calcutta'` | **3** | `technobeala`, `Phase1 Test Co`, `Demo Staffing Co` — **all `TRIAL`, all 0 attendance days, all 0 punches** |
| `company.timezone` outside `{Asia/Kolkata, Asia/Calcutta}` | **0** | — |
| Any other table storing `Asia/Calcutta` | **0** | `branch`/`shift_version` in dev carry only `Asia/Kolkata`, `UTC`, or `NULL` |

## 5.2 Are calculations behaviourally equivalent?

**Yes, identically.** `ZoneInfo('Asia/Calcutta')` and `ZoneInfo('Asia/Kolkata')` encode the same
offset rule — India has held a stable `+05:30` with no DST since 1945 — so every computed attendance
figure is byte-identical under either name. The risk is **not arithmetic; it is string comparison.**
`zoneinfo` does **not** canonicalise: `ZoneInfo('Asia/Calcutta').key == 'Asia/Calcutta'`, confirmed by
execution. Any code that writes `tz == "Asia/Kolkata"` — an allow-list, an invariant check, a report
grouping — silently mishandles these three companies and any future one that arrives the same way.

**This will recur.** It is not dev residue to be cleaned up once — `timezones.ts:19-25`
(`resolveDefaultTimezone`) prefers `Asia/Kolkata` but falls back to `Asia/Calcutta` **only when the
browser's own ICU implementation does not list the canonical name**, which is a real, if shrinking,
population of real browsers on the real `/register` flow.

## 5.3 Final treatment

| Step | Action | Why |
|---|---|---|
| **1 — Fix the future** | Extend every existing `validate_timezone` validator (`Company`, `Branch`, and the two new `ShiftVersion` validators from §4) to canonicalise via an explicit two-entry alias map, applied **after** the `available_timezones()` check: `{"Asia/Calcutta": "Asia/Kolkata"}`. **Do not** attempt general IANA alias resolution — `zoneinfo` exposes no such table, and hand-rolling one for ~600 zones is unjustified liability for an India-only product |
| **2 — Make every comparison alias-safe** | Introduce a module-level `INDIA_TIMEZONES = frozenset({"Asia/Kolkata", "Asia/Calcutta"})` and require every India-invariant check or allow-list to test membership in it, never `== "Asia/Kolkata"`. This protects rows written **before** step 1 ships, in any environment not yet cleaned |
| **3 — Fix the past (`DH-2`)** | `UPDATE company SET timezone='Asia/Kolkata' WHERE timezone='Asia/Calcutta' AND NOT EXISTS (SELECT 1 FROM attendance_day WHERE company_id=company.id)` — a guarded, audited, one-off statement, **not an Alembic revision**, because it is conditional on a live query, not a schema change |

## 5.4 Migration required? Verification? Rollback?

| Question | Answer |
|---|---|
| Migration required | **No.** Application-level `UPDATE`, guarded by the zero-attendance predicate, executed once per environment, with the old value captured to `audit_log` |
| Verification query | `SELECT count(*) FROM company WHERE timezone = 'Asia/Calcutta'` → expect `0` after; re-run the full inventory query from §5.1 |
| Rollback | Restore the three rows' `timezone` from the `audit_log` `before` snapshot. **Trivial** — none of the three companies has any attendance data whose provenance the rename could disturb |
| Does it touch production data? | **NOT VERIFIABLE HERE.** The count, and whether any affected company has live attendance, is unknown outside this repository. `DH-1` (a read-only inventory against production) is a **hard precondition** — see `B4`, §24 |

**Decision status: `GREEN` for dev/staging (all rows zero-attendance, hatch applies cleanly).
`BLOCKED` for production until `DH-1` runs there** (§24).

---

# 6. PUBLIC REGISTRATION TIMEZONE: FINAL BEHAVIOUR

**Traces to:** `NEW-04` (spec §7) → this gate: **settings-driven allow-list, enforced server-side on
both entry points; frontend narrowed to match, never to define, the rule.**

## 6.1 Where the timezone travels today — re-verified

| Stage | Location | Behaviour |
|---|---|---|
| Displayed | `register/page.tsx:163-170` | `<select>` from `listTimezones()` |
| Sourced | `timezones.ts:5-15` | `Intl.supportedValuesOf("timeZone")` — the browser's entire ~600-zone IANA list |
| Defaulted | `register/page.tsx:39` | `resolveDefaultTimezone(timezones)` → `Asia/Kolkata`, falling back to `Asia/Calcutta` |
| Submitted | `POST /v1/auth/register` | Free choice from the list — **public, unauthenticated** |
| Validated | `organisation/schemas.py:100-113` | IANA membership only — **confirmed, no country gate** |
| Stored | `core/db/models/identity.py:45` | `Company.timezone`, `String(50)`, default `"Asia/Kolkata"` |
| Consumed | `calculation.py:294-298` | The **terminal** fallback of the WD-06 chain |

**The gap, concretely:** an anonymous visitor can, today, create a company whose every attendance
calculation runs in `America/Los_Angeles`, with no administrator ever involved, on a product that is
India-only in V1.

## 6.2 Why hiding the field is not sufficient

`CompanyRegistrationRequest.timezone` carries a **Python-side default**, not a server-enforced one —
omitting the field from the request produces `Asia/Kolkata` for the *shipped web client*, but
`POST /v1/auth/register` is public: any caller can post any valid IANA zone directly, regardless of
what the React form shows. Hiding a widget changes what one client sends; it does not change what the
API accepts. The India invariant must be a server-side rule or it is not a rule.

## 6.3 Final behaviour

```text
Backend enforcement (the actual gate):

  settings.allowed_company_timezones: list[str] = ["Asia/Kolkata"]

  CompanyRegistrationRequest.validate_timezone, in this ORDER:
    1. reject if not in available_timezones()                          (existing check, unchanged)
    2. canonicalise via the alias map                                  (§5 — Asia/Calcutta -> Asia/Kolkata,
                                                                          BEFORE the allow-list check)
    3. reject if the canonical value is not in settings.allowed_company_timezones
       -> 422, naming the allowed set

CompanyProfileUpdate.timezone (schemas.py:247, 256-261) — the SAME authenticated admin-edit path —
  gated by the SAME allow-list, in the SAME order. This is NOT covered by TZ-01's change-guard
  (that control answers "may it change at all", a different question from "to what value").
```

| Question | Answer |
|---|---|
| **Frontend behaviour** | Filter the `<select>` to `settings.allowed_company_timezones`, **fetched from the API**, not a second hard-coded TypeScript list — two independently maintained lists is how they drift. If exactly one zone is allowed, render static text, not a one-option dropdown |
| **Backend enforcement** | As above — the actual gate, on both `/register` and `PATCH /company/profile` |
| **Default** | `Asia/Kolkata`, unchanged |
| **Existing-account compatibility** | **No migration.** Every existing company already resolves to `Asia/Kolkata` or `Asia/Calcutta` (§5.1) — both pass the allow-list once canonicalised. No existing row is invalidated |
| **API / import compatibility** | `employee_import` does not touch company timezone (VERIFIED). No other write path to `Company.timezone` exists outside these two endpoints |
| **Why a settings list, not a hard-coded constant** | International expansion becomes a **configuration change**, not a code change and release — the brief explicitly requires not foreclosing this |

**Decision status: `RED` for scope (`CD-2`, §19) / `GREEN` for mechanism.** *Whether* to gate
registration to India-only is a product decision with a strong recommended answer; *how* to gate it
(server-side allow-list, ordered after alias canonicalisation) is not in dispute.

---

# 7. AUTHORITATIVE CLOCK: FINAL POLICY

**Traces to:** `DEC-TZ-01` (remediation) → spec §11 → this gate: **server-authoritative for every path
that can be made server-authoritative; distinguished explicitly where it cannot.**

## 7.1 The rule for ordinary employee self-service

```text
Employee taps "Punch In"
   -> POST /attendance/punches/me   { direction }        -- no time, no source, no employee_id
   -> Service: request_time = datetime.now(UTC)          -- THE trust anchor
              punch_time    = request_time                -- event time == request time, by construction
              source        = "WEB" | "MOBILE", server-assigned from the authenticated route
              created_at    = request_time
```

The client clock is **never read, never compared, never stored** on this path. This is `DEC-TZ-01`
Option A, and it is why a numeric skew tolerance (`DEC-TZ-02`) is moot for self-service specifically —
the control is structural, not a threshold.

## 7.2 The final matrix — every attendance source

| Attendance source | Authoritative timestamp | Client timestamp accepted? | Allowed clock override? |
|---|---|---|---|
| **Employee self-service** (`/attendance/punches/me`) | **Server** (`datetime.now(UTC)` at request receipt) | **No** — no `punch_time` field exists on this schema | **No** |
| **HR/admin on-behalf** (`/attendance/punches`) | **Client-supplied, validated** | **Yes — required.** This is the workflow's entire purpose: correcting a missed punch | **Yes**, bounded: not in the future, not inside a `CLOSED` period (`CD-5`, §19), `reference` (the reason) mandatory, fully audited |
| **Biometric device** | **Not yet built.** Contract fixed here for when it is: server-stamped at ingestion, `source="DEVICE"`, device identity authenticated separately from employee identity | N/A — endpoint does not exist | N/A |
| **CSV / bulk import** | **Not yet built** — `employee_import` imports employee master data only, never punches (VERIFIED by grep) | N/A — does not exist | N/A |
| **Third-party integration** | **Unknown** — no such caller exists in the repository today | **NOT VERIFIABLE HERE** — `B5`, §24, resolved by Phase-0 production access-log review | — |
| **Regularization** (`requested_punches[].requested_time`) | **Client-supplied, approval-gated** | **Yes** — this is an assertion of a historical fact under human review, not a live punch | Bounded to the padded window around the asserted `attendance_date`; **approval required before it becomes a `punch` row** |

## 7.3 What is not removed

Two legitimate administrative workflows are preserved by design, not as an exception squeezed in
after the fact: **on-behalf punch entry** (HR correcting a missed clock-in) and **regularization**
(an employee or HR asserting what should have happened, subject to approval). Both remain
client-time-accepting because both are, definitionally, about a time the server did not itself
observe. What changes is that **only these two paths** may supply a time — the self-service path
never could have needed to, and no longer can.

**Decision status: `GREEN`.** `DEC-TZ-01` Option A is already approved in the plan (`P-02`); only the
endpoint *shape* delivering it was open, and `ED-4` (§2, §20) settles that.

---

# 8. FUTURE TIMESTAMPS, CLOCK SKEW, AND FORGED SOURCE: FINAL POLICY

**Traces to:** `DEC-TZ-02`/`DEC-TZ-03` (remediation) → spec §11.2, §11.6 → this gate: **structural
controls resolve most of this; exactly one numeric threshold remains open.**

## 8.1 What structural change already closes

| Risk | Resolved by | How |
|---|---|---|
| **Forged `source`** (`F-11`) | Server-assigned `source`, §7 | The field is removed from every request schema; the value comes from which route was authenticated and called, never from the body. **VERIFIED to break zero existing tests** — no test in the repository sets `source` in a request body |
| **Future punch, self-service** | Structural — there is no `punch_time` field to forge on `/me` | `punch_time` is always `datetime.now(UTC)` at the server, so "future" is not expressible on this path at all |
| **Naive / non-ISO timestamp** | `AwareDatetime` + a `BeforeValidator` rejecting non-`str` input, on the on-behalf and regularization paths | **CODE-PROVEN gap in the plan's original design:** `AwareDatetime` alone rejects a naive string (`"2026-09-15T09:00:00"`) and a date-only string (`"2026-09-15"`), **but accepts an epoch integer** (`punch_time: 0` → `1970-01-01T00:00:00Z`) because Pydantic v2 treats an int as Unix-epoch seconds, and an epoch value **is** timezone-aware by that reading. The stated wire contract — "ISO-8601 with an explicit offset, no inference" — is not delivered by `AwareDatetime` alone; a string-type guard closes it |
| **Stale/offline timestamps** | Not applicable — confirmed no offline capability exists anywhere in `apps/` (no service worker, no IndexedDB, no queue, no `navigator.onLine` check — VERIFIED by exhaustive search) | A failed punch POST is lost, loudly, today; this is correct behaviour for a client with no queue and must not be "improved" into silent retry-queueing (spec §12.1) |

## 8.2 What remains a numeric threshold — and is not invented here

| Item | Where it applies | Status |
|---|---|---|
| **Far-future bound on on-behalf `punch_time`** | HR entering a punch dated in the future | **`CLIENT DECISION REQUIRED`** — no existing approved rule states a number. The **minimum** structural bound (not in the future relative to server time) is uncontroversial and ships regardless; a tighter bound (e.g., "not more than N days ahead," relevant mainly for pre-scheduled corrections, if the product ever supports them) has no existing rule to point to |
| **Far-past bound (backdating window) on on-behalf `punch_time`** | HR entering a very old punch | **Resolved for V1 without a new number** (`ED-6`, `CD-5`, §19) — bound to "not in the future, and not inside a `CLOSED` period." This reuses an already-existing, already-tested control (`_ensure_date_open`) and requires **no new configuration field**, because `AttendancePolicyVersion` has no backdating column today (`max_backdated_days` belongs to `RegularizationPolicyVersion`, a semantically different window) and adding one is a migration, contradicting the plan's stated no-migration position. If the client wants a tighter limit, that is a legitimate ask but is **out of V1 scope** as a schema change requiring its own default |
| **Employment-start floor** | Any punch predating the employee's own employment record | Not currently enforced at any layer (**VERIFIED:** `2099-01-01Z` and `1900-01-01Z` are both accepted today). **Resolved without a client decision** — the floor is simply the employee's employment start date, already loaded elsewhere in the calculation path; this is a data-integrity bound, not a policy choice |

**Decision status:** far-past bound and forged-source are `GREEN` (`ED-5`, `ED-6` settle the mechanism
with no open number). The far-future *tightening* beyond "not in the future" is explicitly marked
**`CLIENT DECISION REQUIRED`** but is **not a blocker** — V1 ships with the unconditional "not in the
future" bound, which needs no client input to be correct and safe.

---

# 9. ATTENDANCE DATE: THE FOUR CONCEPTS, DEFINED AND SEPARATED

**Traces to:** spec §10 → this gate: adopted verbatim, restated for the client-facing and QA audience.

## 9.1 Definitions — each grounded in code, none assumed identical to another

| Concept | Definition | Where it lives | Derived or asserted? |
|---|---|---|---|
| **Calendar date** | The date in some named timezone, of some instant. Two are relevant here: the **IST calendar date** and the **UTC calendar date** of the same instant — they are not always the same date | Not stored; computed from an instant + a zone | Derived |
| **Shift date** | The local date on which a shift *instance* begins. For a `22:00→06:00` shift starting 30 Sep, the instance runs 30 Sep 22:00 → 1 Oct 06:00 IST, and its shift date is **30 Sep** | `shift_version.start_time`, resolved for a date | Derived from the resolved shift |
| **Attendance date** | **Identical to the shift date, by definition.** `AttendanceDay.attendance_date` — *"the shift's start date for overnight shifts"* (`attendance/models.py:472-473`, FR-ATT-005 — re-read, confirmed unchanged) | `attendance_day.attendance_date` (`DATE`) | **An input asserted by the caller. Never derived from a punch instant** — see §9.2 |
| **Payroll period date** | The `[period_start, period_end]` range an `attendance_period` covers, compared against a single date | `attendance_period.period_start`/`_end` (`DATE`) | Asserted at period creation, independent of any individual attendance date |

## 9.2 Which module uses which date

| Module | Date it operates on | Evidence |
|---|---|---|
| **Attendance calculation** | **Attendance date** — the caller-supplied `target_date` in `AttendanceDayService.calculate()`, which **determines** the punch window (`punch_window_utc(attendance_date=…)`), never the reverse | `attendance/service.py:2483-2504`; `calculation.py:314-345` |
| **Leave** | **IST calendar date** (`business_today`, once Phase 7 lands) for job scheduling; leave-year and cycle dates are independent business-calendar concepts unrelated to shift dates | `leave/service.py:1300-1305, 1474` |
| **Overtime** | Piggybacks on the attendance date — `OvertimeRecord` is keyed to the same `attendance_day` it derives from | `attendance/service.py:3048-3049` |
| **Holiday** | Matched against the **shift/attendance date**, not the punch's calendar date — a night shift starting on a holiday is a holiday shift even though most of its hours fall the next calendar day | Consistent with WD-06/FR-ATT-005 |
| **Weekly off** | Same basis as holiday — the attendance/shift date | — |
| **Period lock** | **Currently the UTC calendar date of the punch instant** (`attendance/service.py:2347`) — **not** the attendance date, and this is precisely `OD-1`/`SR-13`, resolved in §10 | `attendance/service.py:1915-1929, 2347` |
| **Payroll** | The period date, which is compared against attendance dates when a period is finalized, but is itself an independently asserted range | `attendance_period` |

**These four are explicitly not interchangeable.** The single largest source of confusion in the
upstream plan (`OD-1`) was treating "attendance date" and "the UTC date of a punch" as the same
question; §9.3 states why they are not, and §10 shows the concrete consequence.

## 9.3 The consequence: attendance date is asserted, not computed from a punch

Because `attendance_date` is an input, not a derivation, **the correctness of every `attendance_day`
row depends entirely on the caller passing the right value.** There are exactly three callers:

| Caller | Date it asserts | Status |
|---|---|---|
| `POST /attendance/days/calculate` (from `employee-attendance-panel.tsx:78`) | **The browser's UTC date** (`todayIso()`) | ❌ **`NEW-02`** — wrong for the 5h30m of every day between 00:00–05:29 IST. Fixed in Phase 4 (§21) |
| `POST /attendance/days/{id}/recompute` | `row.attendance_date`, read off the existing row | ✅ correct by construction |
| **A scheduled job** *(does not exist yet — `F-14`)* | Will become the **dominant** asserter once Phase 8 builds it | Must derive dates from `business_today(IST)`, the same helper as everything else, or it repeats `NEW-02` at ten-times the scale |

**Decision status: `GREEN`.** No ambiguity remains once `attendance_date` is written down as "the
shift instance's start date in the WD-06-resolved timezone; an asserted input, never derived from a
punch instant" — the requirement in spec §10.5, carried forward here as binding.

---

# 10. `OD-1` — PERIOD LOCK vs. ATTENDANCE DATE: THE CLIENT-FACING QUESTION

**Traces to:** plan §23.2 (frames `OD-1` as a free choice) → spec §9 (derives the answer by execution;
narrows and partially inverts the plan's framing) → **this gate: the algorithm is settled; one
business question remains, and it is much smaller than the plan presented.**

## 10.1 The mechanism under test, in plain terms

Today, a punch is refused at ingestion only if the **UTC calendar date** of its timestamp falls inside
a `CLOSED` payroll period (`attendance/service.py:2347`, `_ensure_date_open`). This has nothing to do
with the shift, the attendance date, or which period the work *actually* belongs to — it is a UTC
string comparison, incidental to how timestamps happen to be stored.

Two properties bound the whole discussion and matter more than the algorithm choice:

1. **It only ever rejects `CLOSED`.** A date in an `OPEN` period, or covered by no period at all, is
   always accepted.
2. **`calculate()` is the unconditional backstop.** Even if a punch slips past this check, a **locked**
   `attendance_day` can never be rewritten — the punch becomes an inert, harmless orphan row, not a
   silent change to a finalized figure.

## 10.2 Walking the clock: a `22:00 → 06:00` night shift starting 30 Sep

Attendance date = **2026-09-30** (the shift's start date, §9). September is **CLOSED**; October is
**OPEN**. Every punch below occurs on the calendar date **1 October** in India local time.

| Local time (IST, 1 Oct) | UTC instant | Local (IST) date | UTC date | Attendance date | Period covering the attendance date | **Today's decision** (UTC-date basis) | **Correct decision** (attendance-date basis) |
|---|---|---|---|---|---|---|---|
| **00:30** | 2026-09-30T19:00Z | 1 Oct | **30 Sep** | 30 Sep | September — **CLOSED** | REJECTED ✅ | REJECTED |
| **01:30** | 2026-09-30T20:00Z | 1 Oct | **30 Sep** | 30 Sep | September — CLOSED | REJECTED ✅ | REJECTED |
| **03:00** | 2026-09-30T21:30Z | 1 Oct | **30 Sep** | 30 Sep | September — CLOSED | REJECTED ✅ | REJECTED |
| **05:00** | 2026-09-30T23:30Z | 1 Oct | **30 Sep** | 30 Sep | September — CLOSED | REJECTED ✅ | REJECTED |
| **05:29** | 2026-09-30T23:59Z | 1 Oct | **30 Sep** | 30 Sep | September — CLOSED | REJECTED ✅ | REJECTED |
| **05:30** | 2026-10-01T00:00Z | 1 Oct | **1 Oct** | 30 Sep | September — CLOSED | **ACCEPTED ❌** | REJECTED |
| **06:00** | 2026-10-01T00:30Z | 1 Oct | **1 Oct** | 30 Sep | September — CLOSED | **ACCEPTED ❌** | REJECTED |

**The entire defect is the step between 05:29 and 05:30** — the moment the UTC date rolls over. It has
no relationship to the shift, the work performed, or which period the attendance actually belongs to;
it is purely an artefact of comparing a UTC-derived date against an India-local business boundary.

## 10.3 The mirror case, so the trade is seen from both sides

An **early day shift** `06:00→14:00` on 1 Oct, padded window 04:00–16:00 IST, with a punch at
**04:30 IST on 1 Oct** → UTC instant `2026-09-30T23:00Z` → **UTC date 30 Sep (CLOSED)**. The
attendance date is **1 Oct (OPEN)**. Today's UTC-date basis **falsely rejects** this punch — the
opposite error from §10.2.

```text
For Asia/Kolkata (+05:30, no DST):
    UTC date == IST date - 1   if and only if   IST time < 05:30
    UTC date == IST date       otherwise

The two bases can disagree ONLY for a punch whose IST wall time is before 05:30 —
which requires a shift whose padded load window opens before 05:30 IST:
a night/cross-midnight shift, or a shift starting before roughly 07:30 IST.
```

## 10.4 What this means for the tenant base

> **For every ordinary day shift, there is no divergence and no decision to make.** A `09:00–18:00`
> shift's padded load window opens at 07:00 IST — above the 05:30 boundary — so the UTC basis and the
> IST basis produce byte-identical accept/reject decisions for the entire mainstream tenant
> population. `OD-1` is not a system-wide question; it is a **night-shift and early-shift** question.

## 10.5 Why the two error types are not equally bad

| Error type | What actually happens | Severity |
|---|---|---|
| **False rejection** (early-day-shift punch refused) | The employee's punch is refused **at the API**. The physical fact that they were at work is **never recorded anywhere** — no orphan row exists to find later, no report can surface it. The only remedy is a regularization request, which checks the same closed period and is **also refused** | **HIGH — an unrecoverable loss of a fact.** WD-11's entire design posture is that punches are append-only facts |
| **False acceptance** (late-night-shift punch accepted into a closed period) | The punch is stored, but `calculate()` unconditionally refuses to write into a locked day (§10.1 property 2) — so nothing about the finalized figures changes. It surfaces in the orphan-punch report and can be reconciled deliberately | **LOW — a visible, recoverable inconsistency, not a lost fact** |

## 10.6 The client-facing question — plain language, no engineering terms

> **May an employee's punch ever be permanently refused because the payroll period already closed —
> or should the system always record the physical fact of a punch and let HR reconcile it
> afterwards, rather than lose it?**
>
> This only matters for **night-shift and early-morning-shift employees**, in a roughly 5½-hour band
> around midnight/dawn. For every regular day-shift employee, the system already behaves identically
> under any answer.
>
> **Recommended answer: never permanently refuse; always record and reconcile.** Concretely: accept
> the punch if **either** the IST date of the punch **or** the previous IST date is not closed, and
> refuse only when **both** are closed. This eliminates the *unrecoverable* error (a lost fact) at the
> cost of some *recoverable* false acceptances, which the orphan-punch report (§16) makes visible and
> correctable. **This must ship together with that report** — accepting more punches into a
> closed-adjacent boundary without a way to see and reconcile them converts a loud failure into a
> quiet one.

**Decision status: `RED` — `CD-1` (§19).** The **algorithm** is not in dispute (derived by execution,
§10.2–10.5); what remains is the business question in the box above, and it blocks **only** the
period-lock basis change itself — every other part of Phase 4 (§21) proceeds regardless.

---

# 11. INDIA V1 RECOMMENDATION — SUMMARY OF THE FIVE PILLARS

Restated once, briefly, because §§1–10 establish each piece separately and the combination is the
actual target architecture:

```text
Asia/Kolkata canonical timezone       + server-authoritative timestamp for self-service
+ explicit, asserted attendance date  + immutable timezone config once attendance is computed
+ no browser timezone in any attendance calculation, storage, or business-date derivation
```

No international timezone complexity is introduced. The existing multi-zone architecture
(`ShiftVersion`/`Branch`/`Company` timezone columns, WD-06 precedence) is **kept, not built** — it
already exists, costs nothing extra to retain, and is what lets the engine be proven zone-independent
today (§4.1, Option 1's rejection) without which a future non-India tenant would require re-proving
the engine from scratch rather than simply lifting the registration gate (`CD-2`).

---

# 12. HISTORICAL INTEGRITY: THE MINIMUM MECHANISM

**Traces to:** spec §13 → this gate: adopted, with the two additions spec §13.5/`SR-11` and `SR-08`
raise made explicit and binding.

## 12.1 The invariant

> **Once an attendance day is finalized or locked, no subsequent configuration change can alter its
> historical result.**

## 12.2 How a historical result can actually change today — every mechanism, and its status

| # | Mechanism | Effective-dated? | Guarded today? | Verdict |
|---|---|---|---|---|
| 1 | A new punch or approved regularization on an **open** day | n/a | `_ensure_date_open` + `is_locked` | ✅ **Intended** — this is what recompute exists for |
| 2 | A **forward-dated** shift/policy/calendar version publish | ✔ | — | ✅ Safe — cannot reach a past date |
| 3 | A **backdated** version publish | ✔ | Nothing checks it against `CLOSED` periods (`SR-11`) | ⚠️ A documented, privileged act (`attendance/models.py:479-481`'s own docstring names it as the sole legitimate exception) — but currently unguarded against period boundaries |
| 4 | **A plain `Company.timezone` / `Branch.timezone` `UPDATE`** | **Not versioned at all** | **`_assert_timezone_change_allowed` is confirmed still a documented no-op** (`organisation/service.py:702-709`: `"""Documented no-op hook until Payroll/Attendance modules exist"""`); **`update_branch` never calls it at all** | 🔴 **The one real defect (`TZ-01`).** A plain `UPDATE` achieves silently what the model's own docstring says only a privileged backdated version publish should be able to do |
| 5 | Employee branch transfer | ✔ (`EmployeeAssignment` as-of) | — | ✅ Safe |
| 6 | Period close → `bulk_lock` → `calculate()` refuses | n/a | ✔ | ✅ Real, working protection |
| 7 | Torn configuration read under `READ COMMITTED` | — | none today | ⚠️ Closes for free as a side effect of fixing #4 |
| 8 | Concurrent recompute, last-writer-wins | — | **confirmed, no `with_for_update` anywhere in `src/`** | ⚠️ §14 |

**Only #4 is a defect requiring a fix.** #3 is a documented privileged act needing a narrower guard
(§12.4); #1 is the system working as designed.

## 12.3 Why "immutable once computed attendance exists" is the smallest correct mechanism

| Candidate mechanism | Verdict |
|---|---|
| **Hard-code `Asia/Kolkata`; delete the timezone columns** | **Rejected.** Forbidden by the brief's own instruction not to destroy existing timezone-aware architecture; deletes the zone-independence property the engine currently has; **VERIFIED cost: 22 live rows + 15 test literals carry non-IST values today**, all of which would need rewriting in the same change |
| **Keep the columns; make them immutable once computed attendance exists for the affected scope** | ✅ **Selected.** Same guarantee, zero architectural loss, reuses the existing `TRIAL`/zero-days currency-lock precedent (`organisation/service.py:654-656`), confirmed present and in active use for a materially identical guard |
| **Effective-date the timezone columns** (versioned, like `ShiftVersion`) | **Correctly deferred.** There is no relocation use case in a single-timezone India V1; the pattern already exists in the codebase (`ShiftVersion`) to copy if one ever appears |

## 12.4 The three specifications the plan left implicit

1. **`_assert_timezone_change_allowed` must become `async`** — it needs an existence query against
   computed attendance, which the current synchronous stub cannot perform. Its one call site
   (`organisation/service.py:659`) becomes `await`.
2. **The guard's scope is "any computed `attendance_day` exists for the affected scope," not "the
   company is live."** For a **branch** timezone change, the scope must walk `EmployeeAssignment`
   history, not just the current roster (`ED-12`) — an employee who has since transferred away still
   has historical days computed in that branch's old zone, and a current-roster-only check misses
   exactly the case the guard exists to catch.
3. **The `CLOSED`-period refusal is absolute and checked before the `TRIAL`/zero-days hatch, not
   after.** A `TRIAL` company with a `CLOSED` period is not a contradiction — it is a trial that
   completed a payroll cycle — and the hatch must not bypass that.

**`SR-11`, scoped narrowly:** add a `CLOSED`-period check to shift-version publish (reusing the
already-existing `_ensure_date_open`), in the same phase as the timezone validator, because both touch
`_validate_and_derive_for_publish`. **The general case — any backdated policy publish reaching a closed
period — is recorded as debt against the policy-versioning workstream, not absorbed into this
programme.**

**Decision status: `GREEN` for the mechanics (`ED-11`/`ED-12` settle *how*) / `RED` for explicit
sign-off on the underlying policy choice (`CD-8`/`DEC-TZ-04`, §19).** This document's engineering
recommendation — block the change outright rather than build effective-dated timezone configuration —
is presented as the default this programme ships with; it needs no further engineering design work
either way, only the client's confirmation that "block, don't version" is the right business trade for
an India-only product. It is **not treated as a phase-blocking `RED` item** in §24's gate, because
Phase 3 proceeds under the stated default and only needs revisiting if the client specifically rejects
it in favour of effective-dating.

---

# 13. UI TIMEZONE: SCREEN-BY-SCREEN FINAL RULE

**Traces to:** spec §15 → this gate: adopted verbatim.

## 13.1 The rule

> **No attendance timestamp ever renders in the viewer's browser timezone. Every attendance
> screen renders `Asia/Kolkata`, always labelled `IST`.**

**Root cause, re-verified:** `format.ts:14-25` — `formatClockTime`/`formatDateTime` call
`toLocaleTimeString(undefined, …)` / `toLocaleString(undefined, …)`; passing `undefined` as the
locale means **both** the locale **and** the timezone are taken from the browser. The file's own
header comment states these helpers are *"never used for calculation, only for rendering values the
backend already computed"* — and `todayIso()`, which **is** used for a calculation-path parameter
(§9.3, `NEW-02`), sits in the same file, contradicting its own stated contract.

## 13.2 Screen-by-screen implementation list

| Screen | File | Current | Required |
|---|---|---|---|
| Attendance day detail | `app/app/attendance/[id]/page.tsx` | Browser zone, 7 call sites | `Asia/Kolkata`; **dual-zone header** (day-detail page only) — the zone is already displayed as a subtitle and no formatter currently uses it |
| Regularization detail | `app/app/regularizations/[id]/page.tsx` | Browser zone, 6 call sites | `Asia/Kolkata`, labelled |
| Leave application detail | `app/app/leave-applications/[id]/page.tsx` | Browser zone, 4 call sites | `Asia/Kolkata`, labelled |
| Attendance period detail | `app/app/attendance-periods/[id]/page.tsx` | Browser zone, 3 call sites | `Asia/Kolkata`, labelled |
| Overtime detail | `app/app/overtime/[id]/page.tsx` | Browser zone, 2 call sites | `Asia/Kolkata`, labelled |
| Employee attendance panel | `components/attendance/employee-attendance-panel.tsx` | Browser zone; also `NEW-02` at `:78` | `Asia/Kolkata`, labelled; date bug fixed in the same phase |
| Leave balances | `app/app/leave-balances/page.tsx` | Browser zone, 1 call site | `Asia/Kolkata`, labelled |
| List pages (attendance/overtime/regularizations/rosters/leave-applications) | 5 files | UTC date via `todayIso()` | `businessToday(tz)` |
| Create-period dialog | `components/attendance-period/create-period-dialog.tsx` | UTC date, **persisted** to `period_start`/`_end` | IST date (`SR-05`†, distinct from the leave-job `SR-05` — same helper) |
| Policy resolution | `app/app/policy-resolution/page.tsx:27` | UTC date via a **duplicate** private `todayIso()` | Delete the duplicate; import the shared, fixed helper |
| Punch entry dialog | `components/attendance/punch-entry-dialog.tsx:33-37` | Browser clock seeds an **editable** time field | Self mode: no time field at all (§7). Admin mode: `IST`, labelled |

## 13.3 The one amendment to a LOCKED decision

`DEC-010` (**LOCKED**) names `company.timezone` as the rendering source of truth. `WD-06` (**also
LOCKED**) already supersedes that for *computation* with `ShiftVersion > Branch > Company`. Literal
compliance with `DEC-010` for *rendering* would therefore display a Dubai-branch day's figures in the
Kerala company's zone — a zone the figures were **not computed in** — which is a second bug, not
correctness. **For India V1 the two zones coincide, so the amendment costs nothing today and is
correct for the day a second zone exists.** Engineering may not make this amendment unilaterally
because `DEC-010` is locked — it is `CD-3` (§19).

**Decision status: `GREEN` for the rendering rule itself / `RED` for the `DEC-010` amendment (`CD-3`).**
Sections 15.1–15.5 of the underlying spec (formatter signature change, required `tz` parameter, test
list) proceed regardless of `CD-3`'s outcome, since India V1 resolves identically either way; only the
**documentation** of the locked decision needs the amendment recorded.

---

# 14. CROSS-MIDNIGHT ATTENDANCE: ENGINE CORRECTNESS BEYOND BREAKS

**Traces to:** spec §14, §16 → this gate: confirms the calculation engine's shift/punch handling is
already correct; the **only** defect is the break-matching function fixed in §1.

## 14.1 What was checked, and the verdict for each

| Scenario | Handling today | Verdict |
|---|---|---|
| `22:00 → 06:00` shift, full attendance | `is_cross_midnight` correctly derived and stored at publish (`_derive_cross_midnight`); window/span arithmetic in `calculation.py` correctly spans the date boundary | ✅ **Correct** |
| `23:00 → 07:00` shift | Same mechanism, same result | ✅ **Correct** |
| `00:00 → 08:00` shift | Not cross-midnight by `_derive_cross_midnight`'s definition (`end_time < start_time` is false when `start=00:00`) — correctly treated as an ordinary same-day shift | ✅ **Correct** |
| Break beginning **before** midnight (e.g., `23:30–00:30`) | **Broken today** (`F-05`) — unmatched, unpaid | ❌ **Fixed by §1, Approach A** |
| Break beginning **after** midnight (e.g., `01:00–02:00` on a night shift) | **Correct today**, and is the exact case that would **regress** under the plan's originally-approved fix (`SR-01`, §1) | ✅ Correct today; **must remain correct** — this is the regression guard |
| Multiple breaks in one shift | `match_breaks` iterates all configured breaks per gap and takes the first match; unaffected by the wrap-aware rewrite, which changes only the per-break containment test | ✅ Unaffected, no change needed |

## 14.2 Explicit scope boundary

**Not redesigned, not touched beyond `match_breaks`:** shift-span arithmetic, duty-block handling,
`is_cross_midnight` derivation, `apply_rounding` (has zero call sites — `F-04` — out of scope), and
`ATT-009` (a gap that *starts* outside a window and *ends* inside it is unmatched even on a day shift —
explicitly **not** bundled here, because fixing it would change computed results for **day** shifts,
widening the blast radius of what is otherwise a night-shift-only correction).

**Decision status: `GREEN`.** No further correction to the calculation engine is required or proposed
beyond the one function in §1.

---

# 15. NIGHT OT: SEPARATED FROM TIMEZONE, EXPLICITLY NOT TOUCHED

**Traces to:** spec §17 → this gate: adopted verbatim, restated for emphasis because it is the item
most likely to be accidentally bundled into this programme by a well-meaning contributor.

```text
Timezone determines local time.
Business policy determines whether that time qualifies as Night OT.
```

**What the code does today — re-verified:**

```python
# calculation.py:1237
is_night = shift.is_cross_midnight
```

```python
# attendance/service.py:3048-3049 — night_window_start/_end ARE loaded into
# OvertimePolicyInputs, and calculation.py NEVER READS THEM.
```

| Configuration | Documented intent | Actual behaviour |
|---|---|---|
| `night_ot_mode = "SHIFT_FLAG"` | Night OT iff the shift is flagged cross-midnight | ✅ Implemented |
| `night_ot_mode = "WINDOW"` | Night OT iff OT minutes fall inside `night_window_start`–`_end` | ❌ **Not implemented — behaves identically to `SHIFT_FLAG`** |
| `night_ot_mode = "BOTH"` | Either condition | ❌ **Collapses to `SHIFT_FLAG`** |

**Consequence:** a **day** shift running into the configured night window never earns the night
multiplier, even when an HR administrator has configured the window fields expecting it to. Two of a
three-valued, UI-selectable enum are silent no-ops. **This is a wrong-money defect, but it is a pay
policy defect, not a timezone defect** — the timezone/local-time computation feeding it is correct;
what is missing is the business rule that reads it.

**Instruction for this programme:** do not implement `WINDOW`/`BOTH`, do not withdraw the fields, do
not "tidy up" `calculation.py:1237` while fixing `match_breaks` in the same file. Touching
`detect_overtime`/`classify_ot_day` would blend a proven-correct timezone change with an undecided pay
policy in one diff, and make the Phase-4 recompute's blast radius impossible to attribute cleanly.

**One safe action, needing no approval:** document in `ATTENDANCE_MASTER_RULE_MATRIX.md` that
`night_window_start`/`_end` are currently inert, so an HR user configuring them today is not silently
misled while `CD-6` (§19) is pending.

**Decision status: `RED` — `CD-6` (§19), and it **blocks nothing** in this programme.**

---

# 16. CALCULATION TRIGGER: MINIMUM PRODUCTION-SAFE ARCHITECTURE

**Traces to:** spec §18 → this gate: adopted, with the `SR-05`/`SR-14` corrections folded in.

## 16.1 Current state — re-verified

```text
Punch created  ->  PunchService.record_punch inserts the punch, writes an audit entry, returns
                    -> ( N O T H I N G ) -- no calculation triggered, in-process or queued
Calculation reachable ONLY from:
   POST /attendance/days/calculate        (ATTENDANCE.VIEW_ALL)
   POST /attendance/days/{id}/recompute   (ATTENDANCE.RECOMPUTE)
Background jobs: celery_app.py beat_schedule has 4 entries, all leave.* — confirmed,
   no attendance.* task exists anywhere in src/
```

**An employee who punches in and out has no `attendance_day` row until a human with
`ATTENDANCE.VIEW_ALL` presses a button.** A period cannot be finalized without that row existing.
Payroll has no input at all until it does. (`F-14`/`PAY-001`, P0.)

## 16.2 Triggers, retry, failure recovery, idempotency — the minimum design

| Requirement | Design |
|---|---|
| **Immediate trigger** | After a successful punch insert, best-effort calculate for the resolved date. **Non-blocking, failure-tolerant** — a calculation failure must never fail the punch write; the punch is a fact, the calculation is a derivation, and losing the fact is unacceptable. **Idempotent by construction** — `calculate()` is full-row replacement (WD-10) |
| **Scheduled reconciliation** | New Beat entrypoint `attendance.run_daily_calculation`, on the **already-established** `leave/tasks.py` two-tier fan-out pattern (enumerate active companies → dispatch one per-company task), at **09:30 IST**, trailing a **3-day window** — both pending `CD-4` |
| **Retry** | Celery's own task retry semantics; no bespoke retry machinery. Each per-company task is independently retryable without blocking another tenant's run — the existing leave pattern already delivers this |
| **Failure recovery** | A failed calculation for one employee-date does not fail the batch; it is picked up again by the next trailing-window run (3-day window absorbs a multi-day outage) |
| **Idempotency** | `calculate()` fully replaces the row every time — running it twice for the same employee-date is safe by construction, which is what makes both the immediate hook and the scheduled sweep safe to overlap or repeat |
| **Duplicate Beat firing** | `OPS-006` — Celery Beat has no leader election; duplicate firing is possible by design. The job's idempotency makes this survivable, but it must be documented in the runbook, not discovered in an incident |

## 16.3 Why 09:30 IST, and the constraint that must be documented

09:30 IST is **after** the outer edge of a `22:00→06:00` shift's ±2h pad (08:00 IST) and **above**
the 05:30 IST/UTC-date skew boundary (`SR-05`, §3) — so `as_of=datetime.now(UTC).date()` would
happen to be correct at this specific hour, which is exactly why the job **must** call
`business_today()` explicitly and **document why**, so a future maintainer moving the schedule earlier
"to have results ready by 09:00" does not silently reintroduce `SR-05`'s defect at a new call site.

## 16.4 The fourth window shape (`SR-14`) — must not be misclassified as an orphan

`resolve_schedule_window` produces four load-window shapes, not the three the ±2h analysis assumes:
`FIXED`/`FLEXIBLE`/`SPLIT` all use a padded window, but when **no shift resolves** for an employee,
`calendar_day_window_utc` applies — the **full local civil day, with no pad at all**. The orphan-punch
report must apply this shape's own rule to unscheduled employees, not the ±2h logic that applies to
everyone else, or every punch from an employee with no resolved shift is misreported.

**Decision status: `GREEN` for the architecture and mechanism (endorses the plan). `RED` for the
schedule/window parameters (`CD-4`, §19) — the *mechanism* is not in dispute; the *numbers* (09:30,
3 days) are a recommendation requiring sign-off, not an invented default shipped silently.**

---

# 17. CONCURRENCY: REAL RACES ONLY

**Traces to:** spec §19 → this gate: adopted verbatim.

## 17.1 Verified state

| Property | Finding |
|---|---|
| Isolation level | `READ COMMITTED` (PostgreSQL default) — confirmed, no override anywhere in `core/db/session.py` |
| Row lock on `attendance_day` | **None** — confirmed, `with_for_update` appears nowhere in `src/` |
| `attendance_day` uniqueness | `UNIQUE (company_id, employee_id, attendance_date)` |
| Punch idempotency | Partial unique index on `idempotency_key`, **only when the client supplies one** — the web UI never does |
| Duplicate collapsing | `calculation.collapse_duplicate_punches`, default 60-second window — the load-bearing, test-proven dedup mechanism |

## 17.2 The four candidate races, evaluated against real trigger paths

| # | Race | Real today? | After the calculation-trigger phase (§16)? | Object to lock | Transaction boundary | Verdict |
|---|---|---|---|---|---|---|
| **1** | Simultaneous punches for one employee | **Not a correctness problem** — `punch` is append-only, no uniqueness on `(employee, time)`; both rows insert and `collapse_duplicate_punches` merges them at calculation time. **This is the designed behaviour** | unchanged | n/a | n/a | **No lock. Adding one would serialise the hottest write path in the module to solve a non-problem** |
| **2** | Double-clicked punch button | Same as #1, plus `idempotency_key` when supplied | unchanged | n/a | n/a | **No lock** — a UI-level submit guard is a UX nicety, not a data-integrity requirement |
| **3** | Concurrent recompute on one employee-date | **Latent today** (rare — two humans pressing Recompute) | 🔴 **Becomes real** — the nightly job and an interactive recompute collide by construction once §16 ships | `attendance_day` row for `(company_id, employee_id, attendance_date)` | Acquired **before** re-resolving configuration (`_build_calculation_input`), inside `calculate()` | **`SELECT … FOR UPDATE`, required, added when the scheduled job ships — not before** |
| **4** | Torn configuration read (a timezone `UPDATE` commits between two `SELECT`s inside one `_build_calculation_input`) | Latent, millisecond window, silent | unchanged | — | — | **Closes for free** as a side effect of §12's guard — if the timezone cannot change while computed attendance exists, the concurrent `UPDATE` this race depends on cannot occur |

## 17.3 The one lock, fully specified

```text
AttendanceDayService.calculate():
    SELECT ... FROM attendance_day
     WHERE company_id = :c AND employee_id = :e AND attendance_date = :d
       FOR UPDATE                                   <- acquired BEFORE _build_calculation_input
```

Four constraints, all binding:

1. **Acquire before reading configuration, not after** — taking it after `_build_calculation_input`
   serialises the write but not the read, leaving a version of race #4 open for any input the §12
   guard does not cover.
2. **Review lock ordering against `AttendanceDayRepository.bulk_lock`** (`repository.py:1222`), which
   period close uses to lock a whole date range. A range lock and a row lock taken in opposite orders
   is a classic deadlock — this is `IR-10` in the plan, made concrete.
3. **`FOR UPDATE` on a row that does not exist locks nothing.** The first calculation for an
   employee-date has no row yet; the `UNIQUE` constraint is the backstop there, and the insert path
   must treat `IntegrityError` as a retry signal, not an error.
4. **Do not raise the isolation level.** `REPEATABLE READ` would close race #4 generally but adds
   serialization-failure retries to a request-scoped, shared session for no benefit once §12's guard
   already closes it at zero cost.

**Do not add locking anywhere else.** Races #1 and #2 are handled by design; locking them would slow
the hottest write path in the module against a problem that does not exist.

**Decision status: `GREEN`.** `ED-8` settles the mechanism and its exact placement (with the
calculation-trigger phase, not before) — no business decision required.

---

# 18. CI GATE: THE MINIMUM REQUIRED MATRIX

**Traces to:** spec §20 → this gate: adopted, restated as a binary readiness matrix.

## 18.1 Current state — re-verified against `.github/workflows/ci.yml`

| Gate | Runs today? | Evidence |
|---|---|---|
| Backend lint / format / mypy / import boundaries | ✔ | 4 steps present |
| Backend **unit** tests | ✔ | Collected and pass without a database |
| Backend **integration + security** tests | ✘ **invoked but cannot pass** | No `services:` block; no skip guard in `tests/conftest.py`; `localhost:5433` does not exist on the runner |
| PostgreSQL / Redis provisioned | ✘ | No `services:` block, confirmed |
| Migrations applied | ✘ | No `alembic` step, confirmed |
| RLS roles provisioned | ✘ | `infra/docker/postgres/init/*.sql` is mounted only by `docker-compose`, never applied in CI |
| **Runs as the non-`BYPASSRLS` app role** | ✘ | `ci.yml` sets `DATABASE_URL=postgresql://hrms:...` — the schema **owner**. The app uses `hrms_app`, confirmed `NOSUPERUSER … NOBYPASSRLS` in `infra/docker/postgres/init/002_app_role.sql:19-20` |
| `TZ` pinned | ✘ | No `TZ` in the job env, confirmed |
| Frontend job | ✘ | One job only, confirmed |
| Frontend tests exist | ✔ | 45 `*.test.ts(x)` files, `"test": "vitest run"` in `apps/web/package.json` |
| Attendance / timezone rules gate merges | ✘ | Unit-only in effect |

## 18.2 The Required CI Matrix

```text
                         Runs in CI today?   Will run after Phase 0?   Required before merge?   Required before release?
Backend unit                    YES                  YES                      YES                       YES
Backend integration              NO                  YES                      YES                       YES
PostgreSQL                       NO                  YES (service)            YES                       YES
Attendance suite                 NO*                 YES                      YES                       YES
Timezone suite                   NO*                 YES                      YES                       YES
Leave suite                      NO*                 YES                      YES                       YES
Frontend (lint+vitest)           NO                  YES (new job)            YES                       YES
Type checking (mypy)             YES                 YES                      YES                       YES
Lint / import boundaries         YES                 YES                      YES                       YES

* — these tests exist in tests/integration and tests/security today but cannot execute in CI
    because there is no database. "Runs in CI today" is NO for all of them, not merely "slow."
```

**A test that exists in the repository but cannot execute in CI is not a gate.** Nothing in this
document treats §20's coverage claims as satisfied until every row above reads `YES` across all four
columns.

## 18.3 Why items 3 and 8 below are non-negotiable, not merely thorough

`hrms_app` is `NOBYPASSRLS`; `hrms` (the schema owner) is not subject to its own row-level-security
policies unless `FORCE ROW LEVEL SECURITY` is set on every table (confirmed not the case here).
**Provisioning PostgreSQL in CI while leaving `DATABASE_URL` pointed at `hrms` would make every
tenant-isolation test pass for the wrong reason — and pass green.** That is strictly worse than the
current state, because today the tests visibly cannot run at all; a green-for-the-wrong-reason suite
looks safe and is not.

## 18.4 The nine-item checklist

```text
[ ] 1  postgres:16-alpine + redis:7-alpine as services:, health-checked
[ ] 2  infra/docker/postgres/init/*.sql applied EXPLICITLY
         (a services: container does NOT run docker-entrypoint-initdb.d)
[ ] 3  DATABASE_URL points at hrms_app — the NOBYPASSRLS role — NOT hrms
[ ] 4  alembic upgrade head runs before the tests
[ ] 5  TZ: UTC in the job env
[ ] 6  a web job: npm ci -> npm run lint -> npm test
[ ] 7  BOTH jobs are REQUIRED STATUS CHECKS on main (a repo setting, not a file)
[ ] 8  a test that PROVES the gate works: a deliberate cross-tenant read is DENIED in CI
[ ] 9  the "Unit tests" step is renamed or split so the name matches what it actually runs
       (pyproject.toml:67 testpaths=["tests"] means pytest collects EVERYTHING, not just unit)
```

**Decision status: `GREEN`.** Purely engineering; `ED-13` settles the role question. No client
decision is needed to run tests honestly.

## 18.5 The four gate tiers — what must be true at each checkpoint

A test that exists but does not run at the checkpoint claiming it is not a gate at that checkpoint.
The four tiers below are cumulative — each includes everything in the tier before it.

| Tier | What must be true | Currently true? |
|---|---|---|
| **Required before coding begins** | Phase 0's baseline measurements are recorded (is CI red on `main`, is the check required, what the current per-file pass/fail split is) — nothing here is a gate, it is the number every later tier is measured against | ✔ achievable immediately — Phase 0 is read-only |
| **Required before merge** | The full nine-item checklist (§18.4) live on `main`, both jobs (`api`, `web`) set as **required status checks** — a PR that breaks lint, mypy, import boundaries, any backend unit/integration test, or any frontend test cannot merge | ✘ today — only lint/format/mypy/import-boundaries/unit tests are actually enforced; integration tests are invoked but cannot pass (no database), and there is no frontend job at all |
| **Required before staging** | Everything above, **plus** the golden-scenario diff (Phase 0.7) run and clean, **plus** the manual punch-integrity matrix executed at least once against the staging deploy | ✘ — depends on Phase 0-CI and the behavioural phases shipping first |
| **Required before production** | Everything above, **plus** Phase 10's full UAT sign-off (including the night-shift-week scenario), **plus** the 48-hour monitoring plan staffed, **plus** the rollback drill actually executed | ✘ — the final checkpoint, reached only at the end of Phase 10 |

**No item in this document is described as "a gate" unless it sits in the "required before merge" row
or later — a test that only ever runs locally, or that CI invokes but cannot pass, is described
throughout this document exactly as that, never as a gate.**

---

# 19. CLIENT DECISION REGISTER

**Only decisions that change business behaviour.** FastAPI architecture, database indexes, test
framework, locking implementation, and internal function structure are engineering calls (§20), not
listed here.

| ID | Business question | Recommended answer | Why | If approved | If rejected |
|---|---|---|---|---|---|
| **`CD-1`** ⭐ | May an employee's punch ever be permanently refused because a payroll period has already closed — or should the physical fact of the punch always be recorded and reconciled afterwards? *(only affects night-shift/early-shift employees, §10)* | **Never refuse; always record and reconcile** — accept when either the local date or the previous local date is still open, ship together with the orphan-punch report | The two possible errors are not symmetric: a false rejection destroys a fact permanently; a false acceptance is visible and recoverable (§10.5) | Implement Option B period-lock basis (§10.6), shipped with the orphan report | Accept that some genuine night/early-shift punches will be **permanently and silently lost** at month boundaries; a documented manual support path becomes necessary |
| **`CD-2`** | Should company registration accept only Indian timezones, and should an existing admin be blocked from changing their company to a non-Indian one? | **Yes to both** — a settings-driven allow-list of `["Asia/Kolkata"]`, enforced at `/register` **and** `PATCH /company/profile` | `/register` is public and unauthenticated; today it accepts any of ~600 IANA zones with no country gate (§6) | India invariant holds structurally, everywhere, permanently | The invariant holds only by convention, until the first anonymous registration or the first profile edit picks a different zone |
| **`CD-3`** | May `DEC-010`'s **LOCKED** rendering clause be amended to name the WD-06-resolved zone rather than the literal `company.timezone` column? | **Amend it** — for India V1 the two are identical, so the amendment costs nothing today and is correct the day a second zone exists | Literal compliance would render a branch-zone day's figures in the company's zone, a zone they were not computed in — a second bug, not correctness (§13.3) | Rendering stays correct as the architecture already allows | Engineering either violates a locked decision or knowingly ships an incorrect rendering rule — **not acceptable either way; cannot be deferred past the UI-timezone phase** |
| **`CD-4`** | When should attendance calculate automatically, and how many trailing days should each run re-check? | **09:30 IST daily, trailing 3 days** — after the outer edge of a night shift's pad, above the `SR-05` skew boundary, idempotent so a missed or repeated run costs nothing | Nothing computes attendance today (§16) — a period cannot be finalized and payroll has no input at all without this | Attendance exists without a human pressing a button; payroll work becomes verifiable | Without it, attendance depends entirely on manual action; a shorter trailing window risks missing late regularizations, a longer one only costs compute |
| **`CD-5`** | May an HR administrator enter an on-behalf punch for any past date inside an *open* period — including one months old — or must there be a tighter limit? | **No tighter limit for V1** — bound to "not in the future, not inside a `CLOSED` period," an already-existing, already-tested control | No configuration field for a tighter bound exists today (`AttendancePolicyVersion` has none; the similarly-named field on `RegularizationPolicyVersion` governs a different workflow) | No migration, no new default nobody has chosen, ships in Phase 1 | A tighter limit is legitimate but becomes a schema migration and a later phase — not something to smuggle into Phase 1 under an unexamined default |
| **`CD-6`** | Should `night_ot_mode`'s `WINDOW` and `BOTH` values be implemented as designed, or withdrawn from the product? | **Decide separately from this programme; implement neither here** — document the fields as currently inert in the rule matrix in the meantime | The fields are configurable, validated, and persisted, but read by nothing (§15) — a day shift running into the configured night window never earns the night premium today | HR is told plainly the setting does not yet do anything | HR continues configuring a setting that silently does nothing — worse than no setting at all |
| **`CD-7`** *(new)* | How far back may HR backdate an on-behalf punch — is "not in the future, not inside a closed period" a sufficient limit, or is a specific numeric cap required? | **No additional numeric cap for V1**, rely on the structural limit alone — **`CLIENT DECISION REQUIRED`, but explicitly non-blocking**: ships with this default unless a number is supplied | No approved rule states a number today; a numeric cap requires a new configuration field and a chosen default, which is new scope, not a bug fix (§8.2) | Phase 1 ships as designed, no migration | A specific number becomes a scoped follow-on phase with its own migration — does not delay Phase 1 |
| **`CD-8`** *(new)* | Should a company/branch timezone change be **blocked outright** once attendance exists, or should the system build **effective-dated** timezone configuration so a change applies only from a future date? | **Block outright** (reusing the existing `TRIAL`/zero-days exemption for brand-new tenants) — **presented for explicit sign-off; ships as the default recommendation unless rejected** | Blocking is the smallest correct mechanism for a single-timezone product; effective-dating is architecturally available (mirrors `ShiftVersion`) but disproportionate scope for a scenario V1 does not expect to encounter (§12.3) | Phase 3 ships as designed | Effective-dated timezone configuration becomes its own, larger scoped phase, deferred past this programme unless specifically requested |

## 19.1 Decisions the upstream plan escalated that this gate does **not**, and the one it demotes rather than drops

| Plan's item | Disposition |
|---|---|
| **Punch rounding (`DEC-TZ-06` in the original remediation register — distinct from this document's `DEC-TZ-XX` client sign-off IDs)** | **Reclassified in this pass, per explicit instruction, from "not escalated" to `CLIENT DECISION REQUIRED` — but still deliberately kept outside every phase in §21.** No approved policy exists for whether/how punch rounding should behave; the recommended answer, if asked, is "leave inert, revisit as its own workstream" — but that is a **recommendation**, not a standing rule, and is not presented as one. **Not added to the numbered `CD-`/`DEC-TZ-` registers above because it changes no behaviour in this programme's phases** — flagging it here, once, satisfies the instruction to name it explicitly rather than bury it, without inflating the register with a decision nothing in Phases 0–10 depends on |
| The ±2h punch pad width (`DEC-TZ-16`) | Premature — the pad's failure mode is currently **invisible** (an orphaned punch produces no error, no flag, no report). Ship the orphan report first, observe real data for a period, then ask |
| Third-party punch integrations | Not a decision — a fact to establish from production access logs (Phase 0), listed as blocker `B5` (§24), not a decision register item |

## 19.2 Dependency order

```text
CD-1  ->  blocks the period-lock basis change only; every other Phase-4 item proceeds
CD-2  ->  blocks the registration/profile allow-list phase
CD-3  ->  blocks amending DEC-010's documentation; the rendering CODE proceeds regardless (India V1 identical either way)
CD-4  ->  blocks the scheduled-calculation phase
CD-5  ->  blocks nothing if the recommendation is accepted; becomes a migration + later phase if rejected
CD-6  ->  blocks nothing; deferred with a trigger
CD-7  ->  blocks nothing; ships with the no-cap default unless a number is supplied
CD-8  ->  blocks nothing; ships with the block-outright default unless rejected

NOT blocking anything: punch rounding (reclassified above, still out of phase scope), ±2h pad width,
                       geofencing, DST policy, employee-level timezone, offline/mobile,
                       third-party integrations (a fact, not a decision)
```

> **Only four decisions gate any work: `CD-1`, `CD-2`, `CD-3`, `CD-4`.** `CD-7` and `CD-8` are new in
> this pass, presented for sign-off on the client-facing page (`DEC-TZ-03`, `DEC-TZ-04`), but both ship
> with a stated default and block nothing. The phases containing the majority of open P0 defects —
> timestamp authority, the India timezone invariant, cross-midnight breaks, and the CI gate — need
> **no client decision at all** and may begin the moment this document is approved.

---

# 20. ENGINEERING DECISION REGISTER

**Decisions engineering may make without client approval** — each changes *how*, never *what the
business gets*.

| ID | Decision | Resolution | Reason | Evidence |
|---|---|---|---|---|
| **`ED-1`** | `ShiftVersion.timezone` — India-lock or strict IANA? | **Strict IANA** at create, update, and publish (§4) | Zero breakage (15 test literals, 22 live rows carry non-IST values); preserves the engine's provable zone-independence; the India invariant belongs at registration, the only tier an external party sets | §4.1–4.3 |
| **`ED-2`** | How to fix `NEW-02` (`todayIso()` on the calculation path) | Make `date` optional server-side on `/attendance/days/calculate`, defaulting to `business_today(company_tz)`; the caller stops sending it | Backward compatible; fixes the defect class, not one instance; keeps the business date on the server, where the company timezone already lives | Spec §5.4 |
| **`ED-3`** | `Asia/Calcutta` handling | Canonicalise on write via a two-entry alias map, applied after the IANA check and before any allow-list; never compare `tz == "Asia/Kolkata"` — use an `INDIA_TIMEZONES` frozenset | Accepts what real browsers send; fixes the future, not only the past; no general alias table exists in `zoneinfo` to lean on | §5 |
| **`ED-4`** | One punch endpoint or two? | **Two** — `/attendance/punches/me` (self), `/attendance/punches` (on-behalf) | The discriminator is inside the body, so one endpoint cannot select between two schemas; two endpoints also make the permission static rather than caller-controlled — independently better RBAC hygiene | §2 |
| **`ED-5`** | Timestamp wire format | `AwareDatetime` + a `BeforeValidator` rejecting non-`str` input | `AwareDatetime` alone accepts an epoch integer (`0` → `1970-01-01T00:00:00Z`); the stated contract is "ISO-8601 with an explicit offset," which an epoch integer is not | §8.1 |
| **`ED-6`** | On-behalf backdating bound, absent configuration | Period-only bound for V1 — not future, not in a `CLOSED` period | Uses controls that already exist and are already tested; escalates the real question as `CD-5` rather than inventing a default | §8.2 |
| **`ED-7`** | Cross-midnight break fix approach | **Approach A** — wrap-aware time-of-day comparison | Approach B regresses a working case; Approach A passes all six scenarios, needs no signature change, matches two existing precedents | §1 |
| **`ED-8`** | Locking strategy | Exactly one `SELECT … FOR UPDATE` on `attendance_day`, in `calculate()`, acquired before configuration is read, added with the scheduled job (not before) | Races #1/#2 are handled by design; race #4 closes free with the timezone guard; adding a lock earlier locks against a collision that cannot happen yet | §17 |
| **`ED-9`** | Where validation lives | The Pydantic schema boundary, so every caller (web, future mobile, device, import) is bound identically. Service-layer checks only for rules needing DB state (period, employment start) | Matches the existing `validate_timezone` pattern already in the codebase | §4, §8 |
| **`ED-10`** | Error handling for an unresolvable timezone reaching the engine | Typed `ConfigurationError` → a `CONFIG_ERROR` attendance day, never a bare 500 | The status already exists in the model; degrades one employee-date instead of every calculate call, which matters once the scheduled job hits it repeatedly | §4.3 |
| **`ED-11`** | `_assert_timezone_change_allowed` signature | Make it `async`; its call site becomes `await` | It needs an existence query against computed attendance, which a synchronous stub cannot perform | §12.4 |
| **`ED-12`** | Branch-guard scope | Walk `EmployeeAssignment` history, not the current roster | An employee who has since transferred away still has historical days computed in the old zone; a current-roster check is leaky exactly where the guard exists to help | §12.4 |
| **`ED-13`** | CI database role | `hrms_app` (the `NOBYPASSRLS` role), never `hrms` — plus a test proving a cross-tenant read is denied in CI | Running RLS tests as the schema owner makes them pass for the wrong reason, and pass green | §18.3 |
| **`ED-14`** | `todayIso()` | Delete it, do not deprecate it; delete the duplicate at `policy-resolution/page.tsx:27` in the same commit | After the date-derivation fix, a surviving copy becomes the one instance of a defect everyone believes is fixed, with nothing to reveal it | §13.2 |
| **`ED-15`** | Test framework and tiers | Unchanged — pytest + `.venv` for the API, vitest for the web | No reason to change anything; the calculation engine's purity is what makes broad pure-function test coverage cheap | §22 |
| **`ED-16`** | `punch.request_time` column split | Deferred, conditional on a code comment plus a test asserting the application sets `created_at` and the DB default never wins | Under server-authoritative self-punch, `punch_time` and `created_at` are equal by construction; the test is what keeps the deferral safe | §7.1 |

---

# 21. FINAL IMPLEMENTATION PHASES

**Execution order — this governs, not the section numbering below:**

```text
Phase 0 (CI + baseline) -> Phase 1 (input/timestamp security) -> Phase 2 (India TZ invariant)
   -> Phase 3 (historical integrity) -> Phase 4 (attendance date / period lock)
   -> Phase 5 (cross-midnight breaks) -> Phase 6 (UI timezone) -> Phase 7 (leave job as_of)
   -> Phase 8 (calculation/reconciliation) -> Phase 9 (regression/integration testing)
   -> Phase 10 (staging/UAT) -> production

Phase 4's period-lock item (4.3) waits on CD-1. Phase 2's registration item waits on CD-2.
Phase 6's DEC-010 amendment waits on CD-3. Phase 8's schedule waits on CD-4.
Every other item in every phase proceeds the moment this document is approved.
```

`Phase 7` (leave `as_of`) is sequenced **after** Phase 4 deliberately, so it consumes the same
`shared/business_time.py` helper Phase 4 builds rather than inventing a second implementation. It
could ship earlier in isolation (it has no dependency on attendance-date logic), but doing so risks a
second, slightly different `business_today()` — the exact mistake `NEW-05` already found once.

---

## Phase 0 — CI and baseline · 1 day

**Objective.** Establish every number this programme will be measured against, and answer the two
questions the repository cannot.

**Findings addressed.** `TST-001`, `NEW-06`, `SR-10`, `SR-12`.

**Files/modules.** None changed. Read-only.

**Dependencies.** None — begin on approval of this document.

**Rules.**
- Tag the baseline commit as an immutable reference.
- Run the full backend suite locally against a real database; record pass/fail **per file**, not just
  a total — this is `IR-7`'s actual size, measured before Phase 0.6 turns it into a gate.
- Capture 10 golden attendance scenarios (day/night/cross-midnight/holiday/weekly-off/leave/half-day/
  OT/incomplete/config-error) as full `attendance_day` JSON, for before/after comparison in later phases.
- Run a **read-only** timezone inventory (`DH-1`) against **every** environment including production.
- Establish whether CI is currently red on `main` and whether the `api` check is a required status
  check — this determines whether Phase 0-CI is "add jobs" or "fix a suite nobody has honestly run."
- Check production access logs for non-web callers of `/attendance/punches` — resolves `B5`.

**Tests.** None added — this phase measures, it does not change behaviour.

**Acceptance.** Every baseline number recorded in the tracking issue. `git status` shows no change
under `apps/`, `alembic/`, `.github/`, or `infra/`.

**Rollback.** N/A — read-only.

---

## Phase 0-CI — CI gate · 2–3 days

**Objective.** Make a PR that breaks an attendance or timezone rule fail to merge.

**Findings addressed.** `TST-001`, `NEW-06`, `SR-10` (§18).

**Files/modules.** `.github/workflows/ci.yml`; repository branch-protection settings.

**Dependencies.** Phase 0's measurements (is CI currently red; is the check required).

**Rules.** The nine-item checklist in §18.4, in full — no partial credit. `DATABASE_URL` must point
at `hrms_app`, never `hrms` (`ED-13`).

**Tests.** A deliberate cross-tenant read that must be **denied** in CI — the test that proves the
role change actually took effect, not merely that the workflow file changed.

**Acceptance.** Every test collected by `pytest` and every `vitest` file runs and gates merges; a PR
containing a knowingly-broken attendance assertion cannot be merged.

**Rollback.** Revert the workflow; un-require the checks. **No product risk — nothing behavioural
changes.**

---

## Phase 1 — Input and timestamp security · 4–5 days

**Objective.** No client can set its own attendance timestamp or provenance on the self-service path.

**Findings addressed.** `F-01`, `F-02`, `F-03`, `F-11`, `TZ-02`, `SR-02`, `SR-03`, `SR-04`, `F-18`.

**Files/modules.** `attendance/schemas.py` (`PunchCreate`, `RegularizationPunchRequest.requested_time`) ·
`attendance/router.py` (`create_punch` → two endpoints) · `attendance/service.py` (`record_punch`) ·
`attendance/exceptions.py` · `apps/api/Dockerfile` · `punch-entry-dialog.tsx` ·
`employee-attendance-panel.tsx`.

**Dependencies.** Phase 0-CI. `ED-4`, `ED-5`, `ED-6`. `CD-5` only if its recommendation is rejected.

**Rules.** Two endpoints, one schema each, `extra="forbid"` (`ED-4`, §2). `AwareDatetime` + string-type
guard on every supplied instant (`ED-5`, §8). Self-service: `punch_time = request_time` unconditionally,
never client-supplied. On-behalf: required, aware, not future, not in a `CLOSED` period, `reference`
mandatory. `source` server-assigned unconditionally — the client-supplied validator is deleted, not
just ignored. Future/far-past bounds with typed errors. Write `punch.raw_payload` (`{user_agent,
client_ip, client_version}`) — **gated on PII retention sign-off (`B8`), not on this list**. `ENV
TZ=UTC` in the Dockerfile and CI.

**Tests.** The full ingestion matrix (`H1`–`H12`) plus the epoch-integer case (`SR-03`); the
server-timezone-independence module (`G1`–`G5`); component tests for both dialog modes; rewrite the
11 existing tests that post `punch_time` to the admin path, old assertions preserved as comments.

**Acceptance.** `punch_time` on the self endpoint → 422. `source` from any caller → 422. A naive or
epoch timestamp → 422. A far-future timestamp → 422. On-behalf without a reason → 422. Regularization
apply still writes `source="REGULARIZATION"` unaffected (it bypasses `PunchCreate` entirely, confirmed).

**Rollback.** Single revert. API and web ship together — no data migration, so rollback is clean.
Punches written during the window remain valid; they are simply server-stamped. If Phase 0's
production-log check found third-party callers, ship behind a feature flag accepting both request
shapes with a deprecation window instead of a same-day cutover.

---

## Phase 2 — India timezone invariant · 3 days

**Objective.** Timezone configuration cannot be invalid and cannot be non-Indian at the one tier an
external party can set.

**Findings addressed.** `NEW-01`, `SR-09`, `NEW-03`, `NEW-04`.

**Files/modules.** `organisation/schemas.py` (`ShiftVersionCreate`/`Update`, `CompanyRegistrationRequest`,
`CompanyProfileUpdate`) · `organisation/service.py` (`_validate_and_derive_for_publish`) ·
`core/config/settings.py` · `shift-version-form.tsx` · `branch-form.tsx` · `register/page.tsx` ·
the `DH-1` inventory script.

**Dependencies.** Phase 1. `DH-1` reviewed for the target environment. **`CD-2` for the registration
allow-list item specifically** — the `ShiftVersion`/`Branch` IANA validation is independent of `CD-2`
and does not wait on it.

**Rules.** IANA validator on both `ShiftVersion` schemas, mirroring `BranchCreate` verbatim, plus a
publish-time re-check (§4). Alias canonicalisation (`Asia/Calcutta` → `Asia/Kolkata`) on every
timezone-accepting validator, applied after the IANA check (§5, `ED-3`). `allowed_company_timezones`
setting, enforced on **both** `/register` and `PATCH /company/profile`, canonicalisation ordered
before the allow-list check (§6). Replace the free-text timezone `<Input>`s on the shift-version and
branch forms with the same select `/register` uses.

**Tests.** The eight `NEW-01` cases (§4.4) — including `timezone="UTC"` and `="Asia/Calcutta"` still
accepted, and `NULL` still falling through WD-06. Registration/profile allow-list rejection and
acceptance cases.

**Acceptance.** `ShiftVersion.timezone="IST"` → 422 at create, never a 500 at calculate. A non-Indian
timezone at registration or profile update → 422 naming the allowed set, once `CD-2` is approved.

**Rollback.** Revert the code — the guard is additive; reverting restores permissiveness and loses no
data.

---

## Phase 3 — Historical integrity · 2–3 days

**Objective.** Timezone configuration cannot change under computed attendance.

**Findings addressed.** `TZ-01`, `TZ-09`, `SR-08`, `SR-11`.

**Files/modules.** `organisation/service.py` (`_assert_timezone_change_allowed`, its call site,
`update_branch`, `_validate_and_derive_for_publish`) · `organisation/exceptions.py`.

**Dependencies.** Phase 2. `DH-1` reviewed and any non-IST production rows individually decided
(`DH-3`). `ED-1`, `ED-3`, `ED-11`, `ED-12`.

**Rules.** Implement `_assert_timezone_change_allowed` for real (it is confirmed still a documented
no-op) and make it `async` (`ED-11`). Call it from **both** `update_company_profile` and
`update_branch` — confirmed today only one call site exists and `update_branch` has none at all.
`CLOSED`-period refusal checked **before** the `TRIAL`/zero-days hatch, not after. Branch-scope guard
walks `EmployeeAssignment` history, not the current roster (`ED-12`). Add the `CLOSED`-period check to
shift-version publish, narrowly, alongside the Phase-2 timezone validator (`SR-11`).

**Tests.** A company or branch timezone change with computed attendance existing anywhere in scope →
409, from **both** paths. `TRIAL`/zero-days → permitted. Any affected period `CLOSED` → refused
unconditionally regardless of trial status. `TZ-09` closes as a side effect — assert no torn read is
observable.

**Acceptance.** No timezone `UPDATE` can silently reach a company/branch with existing computed
attendance. A backdated shift-version publish whose `effective_from` falls inside a `CLOSED` period is
refused.

**Rollback.** Revert the code. The guard is additive — reverting restores today's permissiveness.

---

## Phase 4 — Attendance date and period lock · 2–3 days

**Objective.** No business-date derivation uses the server OS date or the UTC date; the period-lock
basis matches the approved `CD-1` answer.

**Findings addressed.** `TZ-06`, `NEW-02`, `NEW-05`, `SR-06`, `SR-07`, `SR-13`, `OD-1`/`CD-1`.

**Files/modules.** `shared/business_time.py` (new) · `attendance/service.py:3502, 3547, 3558` ·
`attendance/router.py:865` · the session/bootstrap payload · `create-period-dialog.tsx` ·
`policy-resolution/page.tsx:27` · **8 web files, all `todayIso()` call sites**.

**Dependencies.** Phase 3. `ED-2`, `ED-14`. **Item 4.3 (the period-lock basis) additionally waits on
`CD-1`; every other item in this phase proceeds without it.**

**Rules.** `business_today(tz)` / `business_month_start(tz)` helpers. Replace every `date.today()` and
UTC month-start site in the attendance module. Make `/attendance/days/calculate`'s `date` query
parameter optional, defaulting server-side to `business_today(company_tz)` (`ED-2`). Ship the company
timezone in the session/bootstrap payload. Replace every `todayIso()` call with `businessToday(tz)`,
then **delete** `todayIso()` and its duplicate so neither can be reintroduced by autocomplete
(`ED-14`). Fix `create-period-dialog`'s persisted `period_start`/`_end` defaults (`SR-06`). **4.3:**
implement the period-lock basis per the approved `CD-1` answer.

**Tests.** Boundary tests including the 05:00/05:29/05:30 IST case frozen as a test, not a comment
(§10.2). Identical regularization/leave boundary behaviour under `TZ=UTC` and `TZ=Asia/Kolkata` on the
runner. `grep -r "todayIso" apps/web/src` returns nothing after this phase.

**Acceptance.** No `date.today()` and no `datetime.now(UTC).date()` remains in any business-date
derivation in the attendance module. `businessToday()` at 02:00 IST returns the IST date, not the UTC one.

**Rollback.** Per-site revert; each change is independent. Behaviour-preserving wherever the server TZ
already equals IST (the dev host), so blast radius in dev is zero.

---

## Phase 5 — Cross-midnight break fix · 1 day

**Objective.** A configured paid break is paid, whatever hour it spans — without regressing any break
that matches today.

**Findings addressed.** `F-05`, `SR-01`.

**Files/modules.** `attendance/calculation.py` — **`match_breaks` (`:574-617`) only.** No signature
change, no call-site change, line 586 untouched.

**Dependencies.** Phase 0-CI only. **No client decision (§1).** `ED-7`.

**Rules.** Approach A (§1.4): wrap-aware window comparison for both `FIXED_WINDOW` and
`FLEXIBLE_DURATION`, with `start == end` treated as a single point, never a 24-hour window.

**Tests.** The ten scenarios in §1 — test 4 (the `01:00–02:00`-on-`22:00→06:00` regression guard) is
**mandatory**. All ten are pure-function tests, no database.

**Acceptance.** All six §1.1 scenarios behave as the "Approach A" column states. Cases 1 and 4 are
**byte-identical to today** — the regression guards. The ten golden scenarios from Phase 0 are
unchanged except where a midnight-spanning break exists.

**Rollback.** One-function code revert is trivial. **The recompute is not** — `attendance_day` has no
history table. Snapshot every affected day's full JSON before recomputing, and recompute **open** days
only. The change is almost always in the employee's favour; the one exception (`is_excess` newly
firing on an over-long midnight break) must be named in the change notice.

---

## Phase 6 — UI timezone normalization · 2 days

**Objective.** No attendance time renders in the viewer's browser timezone.

**Findings addressed.** `TZ-07`, `F-09` (spec §15).

**Files/modules.** `web/src/lib/attendance/format.ts` · the 25 call sites across 7 files (§13.2) · the
day-detail page for dual-zone rendering.

**Dependencies.** Phase 4 (the company timezone must already be on the wire). **The `DEC-010`
amendment item specifically waits on `CD-3`; every other item in this phase proceeds regardless, since
India V1 resolves identically under either reading.**

**Rules.** `formatClockTime(iso, tz)` / `formatDateTime(iso, tz)` with `tz` **required**, not optional
with a default — an optional parameter is a call site nobody updates. Always render an `IST` label.
Dual-zone rendering on the day-detail page only; dense lists stay single-zone. Correct `format.ts`'s
header comment, which currently misleads by claiming these helpers are "never used for calculation"
while `todayIso()` sat in the same file.

**Tests.** A fixed instant renders `09:05 IST` with the test runner's `TZ` set to `America/New_York`.
Every attendance time carries a zone label. `grep` finds no `toLocaleTimeString(undefined` or
`toLocaleString(undefined` in attendance surfaces after this phase.

**Acceptance.** As above, verified by the vitest job added in Phase 0-CI (these tests were previously
blocked on that job not existing).

**Rollback.** Display-only; revert freely. No data, API, or computed value changes.

---

## Phase 7 — Leave job `as_of` correction · 0.5 day

**Objective.** No Beat-scheduled leave job computes its business date from `datetime.now(UTC).date()`.

**Findings addressed.** `SR-05` (§3).

**Files/modules.** `leave/tasks.py:36, 85, 110`.

**Dependencies.** Phase 4 (reuses `business_time.py`'s `business_today()` rather than inventing a
second helper). No client decision.

**Rules.** Replace `datetime.now(UTC).date()` with `business_today(company_tz)` at all three call
sites (`_accrue_company_async`, `_sweep_comp_off_expiry_async`, `_run_year_end_async`). Record the
<05:30 IST constraint in each task's docstring, so a future schedule change cannot silently
reintroduce the defect at a new time of day.

**Tests.** A test asserting the monthly accrual, run at its scheduled 01:00 IST on the 1st of a month,
computes `as_of` = the **1st**, not the last day of the previous month. Equivalent tests for the
expiry and year-end sweeps.

**Acceptance.** `grep -n "datetime.now(UTC).date()" src/hrms/modules/leave/tasks.py` returns nothing.
Monthly accrual for every tenant covers the correct previous-month window on every run.

**Rollback.** Per-site revert; each of the three call sites is independent. No migration, no schema
change — purely a substitution of one date expression for another.

---

## Phase 8 — Calculation and reconciliation reliability · 5 days

**Objective.** Attendance exists without anyone asking for it, and a period can be finalized.

**Findings addressed.** `F-14`, `PAY-001`, `SR-14`.

**Files/modules.** `attendance/tasks.py` (new) · `core/celery_app.py` (one Beat entry) ·
`attendance/service.py` (`record_punch` sync hook; `calculate` row lock) · `attendance/repository.py`
(orphan-punch query) · the operational runbook.

**Dependencies.** Phases 1–4, 7. **`CD-4`** (schedule + trailing window). `ED-8` (locking).

**Rules.** Best-effort synchronous calculate after a punch insert, wrapped so a calculation failure
**never** fails the punch write. New `attendance/tasks.py` on the `leave/tasks.py` fan-out pattern
verbatim, using `business_today()` from the first line. Beat entry at the `CD-4`-approved schedule,
trailing-window size per `CD-4`, skipping locked days and `CLOSED` periods. Exactly one `SELECT … FOR
UPDATE` on `attendance_day`, acquired before configuration is read, with a lock-ordering review
against `bulk_lock` (`ED-8`, §17). Orphan-punch report handling all four window shapes, so a
no-shift employee's punches are not misreported (`SR-14`).

**Tests.** The concurrency test set (`J1`–`J4`, §17.3) including the first-ever-calculation race. Job
idempotency across two consecutive runs. A punch outside the pad appears in the orphan report; one
inside does not; a punch for an employee with no resolved shift does not.

**Acceptance.** An employee who punches in and out has an `attendance_day` row without human
intervention. Two consecutive job runs produce identical rows. A period can be finalized.

**Rollback.** Disable the Beat entry — the largest, safest lever. The synchronous hook sits behind a
try/except and can be reverted independently. Run once manually on staging at production scale before
enabling the schedule (`IR-4`).

---

## Phase 9 — Regression and integration testing · concurrent with Phases 1–8

**Objective.** Every claim made in Phases 1–8 is proven, not merely implemented.

**Findings addressed.** All of the above, collectively.

**Files/modules.** `apps/api/tests/`, `apps/web/**/*.test.ts(x)`.

**Dependencies.** Phase 0-CI must exist before any of these tests can gate anything (§18.2's point:
"a test that cannot run in CI is not a gate"). Individual test additions are sequenced with the phase
that introduces the behaviour they cover, per §22 below.

**Rules.** No phase is considered complete without its listed tests passing **in CI**, not merely
locally. The 10 golden attendance scenarios from Phase 0 are replayed and diffed against baseline
after every behavioural phase (5, 7, 8 especially) to catch unintended drift.

**Tests.** The full inventory in §22.

**Acceptance.** All tests in §22 pass in CI. The golden-scenario diff shows changes **only** where a
phase's stated acceptance criteria predict a change.

**Rollback.** N/A — this phase is verification, not a behavioural change.

---

## Phase 10 — Staging and UAT · 2 days

**Objective.** Confirm the full stack behaves correctly under realistic conditions before production.

**Findings addressed.** All — this is the integration checkpoint.

**Dependencies.** Phases 0–9 complete.

**Rules.** Deploy the full stack. Replay the 10 golden scenarios and diff against baseline. Run the
punch-integrity matrix by hand: naive timestamp, epoch integer, future timestamp, far-past timestamp,
forged `source`, self-punch with a `punch_time` field, admin punch without a reason. Verify the
`CD-4`-scheduled job fires and is idempotent across two runs. Verify the timezone-change guard on a
real tenant, and that the `TRIAL` hatch still permits a genuine day-one correction. Verify `IST`
rendering from a browser with its OS set to `America/New_York`. **HR/UAT sign-off on a full night-shift
week including a midnight-spanning break** — the one scenario that exercises Phases 3, 4, and 5
together.

**Tests.** Manual UAT script above; the rollback drill (§23) is executed here, not merely documented.

**Acceptance.** Every item above passes; HR/UAT sign-off recorded.

**Rollback.** The staging environment is disposable — no production risk at this phase.

---

## Production rollout · 1 day + 48h monitoring

Off-hours deploy (after 22:00 IST, before 05:00 IST — outside every shift boundary and the scheduled
job). API and web deploy **together** — non-negotiable, since Phase 1 changes the punch endpoint
shape. Monitor for 48 hours: punch rejection rate by reason, punch volume vs. the prior week,
`attendance_day` creation rate, orphan-punch count, timezone-guard 409 rate, 500 rate on
`/attendance/*`. **The single most important signal is the punch rejection rate by reason** — if
Phase 0's production-log check missed an integration, this is where it surfaces, within minutes, as a
spike in 422s, before a payroll cycle absorbs the damage.

---

# 22. TEST PLAN

**Group by tier. Scenarios named below are the specific ones this programme's audits discovered; the
full 68-scenario matrix remains [`ATTENDANCE_TIMEZONE_TEST_MATRIX.md`](./ATTENDANCE_TIMEZONE_TEST_MATRIX.md).**

### Unit / pure-function (no database)
- The ten `match_breaks` scenarios (§1.4) — including the `SR-01` regression guard (case 4) and the
  day-shift regression guard (case 1).
- `business_today(tz)` / `business_month_start(tz)` at the 05:00/05:29/05:30 IST boundary.
- `AwareDatetime` + string guard: naive, date-only, epoch-int, epoch-string, valid-offset cases (`SR-03`).

### Integration (database required — blocked until the Phase-0-CI gate exists)
- The 12-case punch ingestion matrix (`H1`–`H12`) plus the epoch-integer case.
- The eight `NEW-01` cases (§4.4): invalid at create/update/publish, `UTC`/`Asia/Calcutta`/`NULL`
  accepted, pre-existing invalid row → `CONFIG_ERROR` not 500.
- The registration/profile allow-list acceptance and rejection cases (`CD-2`, once approved).
- The timezone-change guard: company/branch change refused with computed attendance in scope, from
  both paths; `TRIAL`/zero-days permitted; `CLOSED`-period refusal absolute.
- The period-lock boundary cases from §10.2's table, asserting whichever basis `CD-1` selects,
  **including the 05:29→05:30 IST case frozen as a test.**
- A test asserting the monthly leave accrual's `as_of` is the 1st of the month, not the 30th of the
  previous one, when run at its scheduled 01:00 IST time (`SR-05`).

### Database / RLS
- The server-timezone-independence module (`G1`–`G5`) parametrised across `TZ=UTC` and non-IST runner
  timezones.
- A deliberate cross-tenant read, asserted **denied** — the CI proof that `hrms_app` is actually in
  effect (`ED-13`).
- `SHOW default_transaction_isolation` matches what the code assumes — fails loudly if a deploy
  changes it.

### API contract
- Two-endpoint punch shape: `punch_time` on `/me` → 422; `punch_time` absent on the on-behalf route →
  422; a caller with only `ATTENDANCE.PUNCH` posting to the on-behalf route → 403.
- `/attendance/days/calculate` with `date` omitted → defaults to `business_today()`; explicit `date`
  still honoured.

### Frontend (vitest — blocked until the Phase-0-CI web job exists)
- A fixed instant renders `09:05 IST` with the runner's `TZ=America/New_York`.
- The `IST` label present on every attendance time.
- Self-punch dialog renders no time input; admin dialog requires a reason.
- A failed punch POST shows a non-dismissible error and persists nothing (`P-08`).
- `create-period-dialog` pre-fills the IST date at 02:00 IST (`SR-06`).
- `grep -r "todayIso" apps/web/src` returns nothing (`ED-14`).

### End-to-end / regression
- The ten golden attendance scenarios (Phase 0.7), diffed before/after each behavioural phase.
- A full night-shift week including a midnight-spanning break, exercised in staging (Phase 10).
- 23:30–00:30 break and 01:00–02:00-on-`22:00→06:00` break, both end-to-end through `calculate()`,
  not only through the pure `match_breaks` unit tests.

### Production / staging
- The manual punch-integrity matrix (Phase 10): naive, epoch, future, far-past, forged `source`,
  self-with-`punch_time`, admin-without-reason.
- 48-hour post-deploy monitoring: rejection rate by reason, `attendance_day` creation rate, orphan
  count, timezone-guard 409 rate.

**Decision status: `GREEN`.** The inventory is derived entirely from findings already established
upstream; no test in this list requires a business decision to write, only `CD-1`'s answer to know
which of two possible assertions the period-lock test makes.

---

# 23. ROLLBACK PLAN

| Phase | DB rollback required? | Migration rollback? | Feature flag? | Deploy rollback? | Data repair required? | Verification |
|---|---|---|---|---|---|---|
| 0-CI | No | No | No | Revert workflow file; un-require checks | No | Confirm `main` accepts a PR again under the old rules |
| 1 — Timestamp authority | No | No | **Only if Phase 0 found third-party callers** — accept both request shapes during a deprecation window | Single revert; API+web together | No — punches written during the window remain valid, simply server-stamped | Re-run the `H1`–`H12` matrix against the reverted code |
| 2 — India TZ invariant | No | No | No | Revert code | No — guard is additive | Confirm a previously-rejected `IST` value is again accepted (expected regression, proves rollback worked) |
| 3 — Historical integrity | No | No | No | Revert code | No | Confirm a timezone `UPDATE` with existing attendance again succeeds (expected regression) |
| 4 — Attendance date / period lock | No | No | No | Per-site revert; independent changes | No | Confirm `todayIso()`-equivalent UTC-date behaviour returns where reverted |
| 5 — Cross-midnight breaks | **No** (code) / **Yes** (computed results) | No | No | One-function revert | **Yes — this is the one irreversible data operation in the programme.** `attendance_day` has no history table; every affected day must be snapshotted **before** recompute | Diff the snapshot against the reverted recompute; confirm identical to pre-change values |
| 6 — UI timezone | No | No | No | Revert freely | No — display-only | Visual check only |
| 7 — Leave job `as_of` | No | No | No | Per-site revert | **Possibly** — if a monthly accrual already ran with a corrected `as_of` before rollback, the accrual itself is not undone by reverting the code; assess whether the corrected run should be kept regardless | Confirm the next scheduled run reproduces the pre-fix skew (expected regression) |
| 8 — Calculation/reconciliation | No | No | **Yes, implicitly — disabling the Beat entry is the rollback lever** | Disable Beat entry; sync hook behind independent try/except | No — `calculate()` is idempotent full-row replacement | Confirm no new `attendance_day` rows are created without manual action after disabling |
| 9 — Regression testing | N/A | N/A | N/A | N/A | N/A | N/A — verification only |
| 10 — Staging/UAT | N/A (disposable environment) | N/A | N/A | N/A | N/A | N/A |

**Feature flags are deliberately not used** for any phase whose change is purely corrective and
reversible through a normal deploy rollback (2, 3, 4, 6, 7) — per the instruction to avoid unnecessary
flags. The two exceptions (Phase 1's possible deprecation window, Phase 8's Beat-entry toggle) are
flags with a specific, named trigger, not defensive defaults.

**Phase 5 is the one phase requiring special handling on rollback**, because it is the only phase in
this programme that changes **computed, persisted** figures rather than code or configuration
behaviour. The pre-recompute snapshot (`B9`, §24) must exist and be tested **before** Phase 5 runs its
recompute, not discovered as a gap afterward.

---

# 24. FINAL GO / NO-GO GATE

## GREEN — Implement immediately

**No unresolved business ambiguity. May begin the moment this document is approved.**

| Item | Phase | Why it is green |
|---|---|---|
| **`NEW-01` — IANA validation on `ShiftVersion.timezone`** | 2 | `ED-1` settles it; zero breakage; the item an ordinary HR user is most likely to trigger by typing `IST` (`SR-09`) |
| **`F-05` — cross-midnight breaks, via Approach A** | 5 | Unambiguous defect; `ED-7` settles the approach; ten pure tests, no database, ~6 lines |
| **`TZ-02` — naive-timestamp rejection + `ENV TZ=UTC`** | 1 | Independent of every other decision; correct under all options |
| **`F-11` — server-assigned `source`** | 1 | Verified to break zero existing tests |
| **`F-01`/`F-02`/`F-03` — server-authoritative self-punch** | 1 | `DEC-TZ-01` Option A already approved; only the endpoint shape was open, and `ED-4` settles it |
| **`TZ-06` — `business_today()` at the four `date.today()` + two UTC-month sites** | 4 | `DEC-010` already requires it |
| **`SR-05` — `as_of` in the three Beat leave tasks** | 7 | Same helper, same fix pattern; a demonstrable monthly-accrual defect, re-verified current in this document |
| **`NEW-05` — delete the duplicate `todayIso()`** | 4 | `ED-14` |
| **`SR-06` — IST default in `create-period-dialog`** | 4 | Same fix, same phase |
| **`TZ-01` — the timezone-change guard, called from both paths** | 3 | `DEC-TZ-13` Option A approved; `ED-11`/`ED-12` settle the mechanics; **re-confirmed still a no-op stub in this document's own verification** |
| **`TZ-09` — torn configuration read** | 3 | Closes free as a side effect |
| **`F-18` — write `punch.raw_payload`** | 1 | Column exists; gated on PII sign-off (`B8`), not on a decision |
| **`TST-001`/`NEW-06`/`SR-10` — the CI gate** | 0-CI | Purely engineering; `ED-13` settles the role question |
| **The orphan-punch report** | 8 | Changes no computed value; needs no approval |
| **Documentation:** attendance-date definition (§9), `night_ot_mode` inertness (§15), the ±2h pad, the WD-30 basis | 0–4 | Documentation only |

## YELLOW — Requires explicit technical confirmation

**Engineering judgement calls stated as a recommendation that should be confirmed before code is
written, not discovered during review.**

| Item | The confirmation needed | Ref |
|---|---|---|
| **`SR-02`/`ED-4` — two punch endpoints** | Confirm the URL shape (`POST /attendance/punches/me`) is acceptable | §2 |
| **`SR-03`/`ED-5` — epoch-integer timestamps** | Confirm the contract is "ISO-8601 string with offset," not merely "tz-aware" | §8.1 |
| **`SR-01`/`ED-7` — Approach A over Approach B** | Confirm the override of both the plan and the remediation spec; the evidence is reproducible in one command | §1 |
| **`ED-2` — `/days/calculate?date=` becomes optional** | Confirm an API default is preferred to a client-computed date | §9.3 |
| **`ED-8` — one `FOR UPDATE`, added with the scheduled job** | Confirm the lock-ordering review against `bulk_lock` is scheduled as real work | §17.3 |
| **`ED-12` — branch-guard walks assignment history** | Confirm the query cost is acceptable on a large tenant | §12.4 |
| **`SR-11` — `CLOSED`-period check on shift-version publish** | Confirm this narrow control is in scope now, and the general case is recorded as debt elsewhere | §12.4 |
| **`SR-14` — the fourth window shape** | Confirm the orphan report excludes no-shift employees rather than flagging them | §16.4 |
| **Phase-5 recompute snapshot** | Confirm the pre-recompute snapshot mechanism exists and is tested **before** Phase 5, not after | §23 |

## RED — Requires client decision

**Business-policy decisions. Engineering may not make these.**

| ID | Decision | Blocks |
|---|---|---|
| **`CD-1`** ⭐ | May a punch ever be refused because a period closed, or must the fact always be recorded and reconciled? | Phase 4 item 4.3 only — everything else in Phase 4 proceeds |
| **`CD-2`** | India-only allow-list on registration and profile edit? | Phase 2's registration item |
| **`CD-3`** | May `DEC-010`'s locked rendering clause be amended? | Phase 6's documentation amendment — the code proceeds regardless |
| **`CD-4`** | Automatic calculation schedule and trailing-window size? | Phase 8 |
| **`CD-5`** | Tighter on-behalf backdating limit than "not future, not closed"? | Nothing if accepted; becomes a migration + later phase if rejected |
| **`CD-6`** | Implement or withdraw `night_ot_mode`'s `WINDOW`/`BOTH`? | Nothing — deferred with a documented trigger |
| **`CD-7`** *(new)* | Any additional future-dated-punch tolerance beyond the unconditional "not later than now" floor? | Nothing — ships with no tolerance unless a number is supplied |
| **`CD-8`** *(new)* | Block a company/branch timezone change outright once attendance exists, or build effective-dated timezone configuration? | Nothing — Phase 3 ships under the "block" default unless rejected |

**Deliberately not escalated as a numbered, phase-blocking register item:** the ±2h pad width,
third-party integrations (a Phase-0 fact, not a decision), DST policy, employee-level timezone,
offline/mobile, geofencing, biometric identity (§19.1). **Punch rounding is named explicitly, once, as
`CLIENT DECISION REQUIRED` in §19.1**, but is deliberately excluded from this numbered register because
nothing in Phases 0–10 depends on its answer.

## BLOCKED — Must be resolved before the first production code change

| # | Blocker | Owner | Why it blocks |
|---|---|---|---|
| **B1** | `SR-01` — the break-fix approach the approved plan would have shipped as a regression | Engineering — `ED-7` | Phase 5 cannot be written until settled — reproducible in one command |
| **B2** | `SR-02` — the punch-endpoint shape the approved design cannot implement as written | Engineering — `ED-4` | Phase 1 cannot be written |
| **B3** | `TST-001` + `SR-10` — the CI gate running as `hrms_app` | Engineering | Every integration test in this programme is worthless as a gate until CI runs it |
| **B4** | `DH-1` inventory against **production** | Ops / Engineering | **NOT VERIFIABLE HERE.** Phase 3's guard makes every timezone value permanent; landing it before production is inventoried freezes every misconfiguration forever, with no escape for a live tenant |
| **B5** | Are there third-party callers of `/attendance/punches`? | Ops | **NOT VERIFIABLE HERE.** Determines whether Phase 1 is a same-day cutover or needs a feature-flagged deprecation window |
| **B6** | Is CI currently red on `main`, and is the check required? | Engineering | Determines whether Phase 0-CI is "add jobs" or "fix a suite nobody has run honestly" |
| **B7** | `CD-1`…`CD-4` | **CLIENT** | Gates the specific phase items listed above — nothing else. `CD-5`…`CD-8` ship with a stated default and are **not** part of this blocker — they need a signature, not a delay |
| **B8** | PII retention sign-off for `punch.raw_payload` | Client / Legal | It captures IP and user-agent on every punch for every employee, indefinitely, until a retention period is set |
| **B9** | Pre-recompute snapshot mechanism, tested | Engineering | Phase 5's recompute is the one irreversible data operation in the programme |

### Minimum decisions required before coding begins

1. Approve this document as the artefact engineering implements against.
2. `ED-1`…`ED-16` (§20) — engineering internally confirms each `YELLOW` item, in writing, before the
   phase that depends on it starts.
3. Resolve `B1`/`B2` — already resolved in this document (§1, §2); no further input needed, only
   sign-off.

### Minimum decisions required before staging

4. `CD-1`, `CD-2`, `CD-3`, `CD-4` — at least a provisional answer, so Phases 2–8 can complete their
   `CD`-gated items rather than stalling mid-phase.
5. `B4` — the production timezone inventory, run and reviewed, with any `DH-3` per-row decisions made.
6. `B5` — the production access-log check for third-party punch callers.
7. `B8` — PII retention period for `raw_payload`, so Phase 1.6 is not blocked at the point of
   first write.
8. `CD-5`…`CD-8` recorded — not gating, but every checkbox on the client sign-off page (front matter)
   should carry an actual mark before staging, so no default is silently assumed into production.

### Minimum decisions required before production

9. `B6` resolved and Phase 0-CI's nine-item checklist fully green, both jobs required status checks.
10. `B9` — the pre-recompute snapshot mechanism exercised at least once on staging, verified restorable.
11. Phase 10's UAT sign-off, including the night-shift-week scenario.
12. The 48-hour production monitoring plan staffed and the rollback drill (Phase 10) actually executed,
    not merely documented.

---

## The closing statement

The reconciliation that produced the spec changed the plan in two places and confirmed it in
thirty-one; this gate adds no new correction to either the code or the plan — it packages what was
already found, adds the three items the spec's own findings (`SR-05`, `SR-09`, `SR-13`, `SR-14`)
required to be carried through to a decision rather than left as observations, and states plainly
which of the resulting items are ready, which need an internal nod, and which need the client.

**What stands unchanged is the plan's central judgement, reaffirmed by re-verification in this
document:** the calculation engine is sound. Every open P0 sits at a boundary — ingestion,
configuration mutability, scheduling, rendering, packaging — or is a missing test, never inside the
arithmetic that turns punches into paid minutes. Nothing in this document asks anyone to rebuild the
instrument. It asks for one function to be corrected, four boundaries to be closed, a schedule to be
added, and a test harness that makes all of it provable — in that order, starting with the harness.

**Recommendations in this document carry no authority.** They exist so each decision has a starting
point, not so it can be skipped. Nothing here may be implemented until this document is reviewed and
approved, and nothing gated on `CD-1`…`CD-8` or `B1`…`B9` may be implemented until those are recorded.

---

# 25. ENGINEERING SIGN-OFF CHECKLIST

**For the engineering lead to check off internally before Phase 0-CI begins.** Each item points back
to the section that already resolved it — this checklist confirms the resolution was read and
accepted, it does not re-open any of them.

```text
[ ] SR-01 resolved              — Approach A selected for cross-midnight breaks (§1); ED-7
[ ] SR-02 resolved               — two punch endpoints, not one (§2); ED-4
[ ] SR-05 resolved               — leave-job as_of fix scoped into Phase 7 (§3)
[ ] SR-09 resolved                — ShiftVersion free-text timezone input identified and fixed (§4.2, §4.5)
[ ] Asia/Calcutta migration strategy defined     — canonicalise-on-write + one-off DH-2 UPDATE (§5)
[ ] Registration timezone locked                  — server-side allow-list, ordered after alias
                                                     canonicalisation (§6) — pending CD-2 sign-off
[ ] Shift timezone validation defined             — strict IANA, ED-1 (§4.3)
[ ] Branch timezone validation defined            — already correct; confirmed unchanged (§4.5)
[ ] Historical configuration protection defined   — block-on-existing-attendance, ED-11/ED-12 (§12)
                                                     — pending CD-8 sign-off
[ ] UI timezone defined                           — Asia/Kolkata always, IST label, tz required
                                                     parameter (§13) — pending CD-6/DEC-TZ-06 for the
                                                     DEC-010 documentation amendment only
[ ] Period-lock behaviour defined                 — algorithm derived by execution (§10) — pending
                                                     CD-1/DEC-TZ-05 sign-off on the business trade
[ ] CI database services defined                  — postgres:16 + redis:7 as services:, hrms_app role
                                                     (§18, ED-13)
[ ] Integration tests gated                       — nine-item checklist + four-tier breakdown (§18.4,
                                                     §18.5); not yet true on main as of this document
[ ] Rollback defined                              — per-phase rollback plan complete (§23); Phase 5's
                                                     pre-recompute snapshot is the one irreversible-data
                                                     item and needs a tested mechanism before it runs (B9)
```

**Additional items this pass adds to the checklist, not present in the original engineering audit:**

```text
[ ] Leave-job as_of fix sequenced after Phase 4 (shares business_time.py rather than duplicating it) — §21
[ ] Far-future punch tolerance decision recorded — CD-7/DEC-TZ-03, non-blocking default (§8.2, §19)
[ ] Full HR-forms timezone-input sweep completed — nine modules checked, three screens carry a
    timezone field, two of three already validated (§4.5)
[ ] CI four-tier gate breakdown recorded — before-coding / before-merge / before-staging /
    before-production, so "gate" is never claimed for a check CI does not actually execute (§18.5)
```

---

# 26. FINAL STATUS

## READY FOR IMPLEMENTATION — recorded 2026-09-15

**Superseding the "NOT READY" verdict below**, which is retained for the record because §26's own
closing paragraph asks whoever closes items 1–3 to record the fact here rather than commission a new
review. All three are now closed:

| # | Blocker | Closure |
|---|---|---|
| 1 | Document unapproved | **Closed** — approved by the product owner as the artefact engineering implements against (front matter, §0) |
| 2 | `CD-1`…`CD-4` unanswered | **Closed** — all eight `CD-`/nine `DEC-TZ-` decisions selected in §0, each in favour of this document's recommended answer |
| 3 | `B4`/`B5`/`B6`/`B8` unresolved | **Partially closed.** `B6` closed by measurement (CI is green on `main` for the checks it runs; it runs no integration test, so no integration test is a gate today). **`B4`, `B5`, `B8` remain open and are NOT closable from this repository** — they are production and legal facts. They do not block implementation or staging; they **do** block production deployment and are carried as residual risk in the completion report |

**Consequence for the verdict:** implementation and staging are cleared. **Production is not**, and no
amount of code in this programme can clear it — see the completion report's *Remaining risks*.

---

## NOT READY FOR IMPLEMENTATION *(superseded — retained for the record)*

**As of this document's preparation date (2026-09-15), the programme is not yet clear to begin Phase
0-CI, for reasons that are exclusively `BLOCKED`/`RED` items already named in §24 — not new findings,
and not open-ended analysis.**

Precisely three things stand between this document and a `READY` status, all already fully specified
above, none requiring further audit:

| # | What is blocking | Where it is fully specified | Who closes it |
|---|---|---|---|
| 1 | **This document itself is unapproved.** Every recommendation in it is exactly that — a recommendation — until a human with authority to approve it does so | The document as a whole | Client / product owner + engineering lead, jointly |
| 2 | **`CD-1`, `CD-2`, `CD-3`, `CD-4` are unanswered.** These are the only four client decisions that gate any specific phase item (§19.2) | Client Sign-Off Page (front matter), `DEC-TZ-05`, `DEC-TZ-02`, `DEC-TZ-06`, `DEC-TZ-07` | Client / product owner |
| 3 | **`B4`/`B5`/`B6`/`B8` are unresolved facts**, none of them answerable from this repository — a production timezone inventory, a production access-log check, whether CI is currently red on `main`, and a PII retention period | §24's `BLOCKED` table | Ops, Engineering, and Legal respectively |

**What is explicitly NOT blocking, and must not be treated as if it were:**

- `CD-5`, `CD-6`, `CD-7`, `CD-8` — each ships with a stated, safe default; a signature closes the loop,
  it does not gate a start date.
- Every `YELLOW` item in §24 — these are internal confirmations, not open designs; none requires
  further investigation, only a reviewer's nod.
- Every `GREEN` item in §24 — fourteen items, spanning five of the eleven phases and five of the eight
  open P0 defects, may begin **today**, in parallel with the three items above being resolved.

**The moment items 1–3 above are closed, this section's verdict becomes:**

> ## READY FOR IMPLEMENTATION
>
> All required client decisions are approved (`CD-1`…`CD-4`, at minimum provisionally), all technical
> decisions are resolved (§20, §25), and no `BLOCKED` item affects Phase 0-CI or Phase 1. Engineering
> may begin Phase 0 immediately upon this verdict being recorded, without a further audit pass.

**This document does not update itself.** Whoever closes items 1–3 should record that fact directly
against this section (date, name, decision) rather than commissioning a new review — the analysis
underneath this verdict is complete and does not change based on how quickly the three items above are
resolved.

---

# 27. DISCIPLINE STATEMENT — WHY THIS IS THE LAST AUDIT PASS

Every issue surfaced while preparing this document — including the four items added in this pass
(`SR-05`'s scope, the full HR-forms sweep, the far-future tolerance question, and the
timezone-change-after-attendance framing) — was closed to one of exactly four labels before being
written down: `GREEN` (implement), `YELLOW` (engineering confirms), `RED` (client decides), or
`BLOCKED` (external fact required). **Nothing in this document is left in an unclassified,
"needs more investigation" state.**

Three things that were deliberately **not** turned into a reason to keep auditing:

1. **Punch rounding** (§15, §19.1) has no approved policy and a plausible client answer either way —
   it is named once, clearly, as `CLIENT DECISION REQUIRED`, and then explicitly excluded from every
   phase in §21, rather than becoming a fifth open-ended workstream bolted onto this one.
2. **The ±2h punch pad width** is acknowledged as a real open question whose *current* failure mode is
   invisible — the correct response is to ship the orphan-punch report (already in Phase 8) and observe
   real data, not to guess at a number now.
3. **Effective-dated timezone configuration** (the "reject" branch of `DEC-TZ-04`/`CD-8`) is fully
   specified as an *alternative*, not designed in detail, because it is not the recommended path and
   detailed design work on a rejected alternative would itself be exactly the kind of speculative
   architecture this document exists to avoid building.

**The next session's task is implementation, gated only by the items in §26.** It is not another
timezone audit. If a future session finds itself re-deriving `OD-1`'s scenario table, re-comparing
Approach A and B for `match_breaks`, or re-establishing whether `_assert_timezone_change_allowed` is a
stub, that is a sign the prior work was not read, not a sign the prior work was incomplete.

---

```text
Documents read:                 ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md (2276 lines),
                                 ATTENDANCE_TIMEZONE_IMPLEMENTATION_PLAN.md (1703 lines),
                                 ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md (1963 lines),
                                 ATTENDANCE_TIMEZONE_AUDIT.md (878 lines),
                                 ATTENDANCE_TIMEZONE_TEST_MATRIX.md (267 lines),
                                 ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md,
                                 ATTENDANCE_TIMEZONE_DECISION_REGISTER.md,
                                 0010-utc-storage-company-timezone-render.md,
                                 plus 20+ source files re-read directly against the working tree
                                 at e33fcdb to independently re-verify the spec's code claims.

Sources reconciled:             5 upstream documents; 2 explicit conflicts, both resolved in favour
                                 of the spec (§1 SR-01, §12/§10 OD-1).

Client decisions remaining:     8 — CD-1 through CD-8 (§19), presented for signature as DEC-TZ-01
                                 through DEC-TZ-09 on the Client Sign-Off Page (front matter). Only
                                 CD-1, CD-2, CD-3, CD-4 gate any implementation work; CD-5, CD-6, CD-7,
                                 CD-8 each ship with a stated safe default and block nothing.

Engineering decisions remaining: 0 outstanding — all 16 (ED-1..ED-16, §20) have a stated resolution;
                                 9 are marked YELLOW pending internal confirmation, not further design
                                 work. §25 packages these into a checked-off-once engineering sign-off
                                 list.

Blocked items:                  9 — B1..B9 (§24). B1, B2 are resolved in this document and need only
                                 sign-off. B3, B6 are CI/process facts to establish. B4, B5 are
                                 production facts not verifiable from this repository. B7 restates
                                 CD-1..CD-4. B8 is a legal/retention sign-off. B9 is a tested-snapshot
                                 precondition for the one irreversible operation in the programme.

GREEN implementation items:     14 items spanning 5 of 11 phases and 5 of 8 open P0 defects (§24) —
                                 may begin the moment this document is approved, independent of every
                                 CD/B item above.

Implementation phases:          11 — Phase 0 (baseline) -> Phase 0-CI -> Phase 1 (timestamp authority)
                                 -> Phase 2 (India TZ invariant) -> Phase 3 (historical integrity)
                                 -> Phase 4 (attendance date / period lock) -> Phase 5 (cross-midnight
                                 breaks) -> Phase 6 (UI timezone) -> Phase 7 (leave job as_of)
                                 -> Phase 8 (calculation/reconciliation) -> Phase 9 (regression testing,
                                 concurrent throughout) -> Phase 10 (staging/UAT) -> production.

Estimated effort:               ~27-30 engineering-days across Phases 0-8 (sum of the plan's
                                 per-phase estimates, carried forward unchanged by the spec's
                                 reconciliation) + 2 days staging + 1 day + 48h monitored rollout.
                                 Does not include time waiting on CD-1..CD-4 or B4/B5/B8, which are
                                 external and not engineering-bound.

Production readiness:           NOT READY FOR IMPLEMENTATION as of this document's preparation date
                                 (§26) — blocked on exactly three things: (1) formal approval of this
                                 document, (2) CD-1..CD-4, (3) B4/B5/B6/B8. Phases 0, 0-CI, 1, and 5
                                 (5 of 11 phases, 5 of 8 open P0s) require none of the above and may
                                 begin today. The verdict flips to READY FOR IMPLEMENTATION the moment
                                 those three items are closed — no further audit pass is required (§27).
```

---

*Prepared 2026-09-15 against the working tree at `e33fcdb`, branch `main`. **No application code,
database schema, migration, test, CI configuration, or database row was modified in the preparation of
this document.** Every code citation carried forward from the spec was independently re-read from the
working tree while preparing this gate, not merely copied. Production data and production deployment
configuration are **NOT VERIFIABLE HERE** — no production environment is reachable from this
repository, which is why `B4`, `B5`, and `B8` are blockers rather than assumptions.*

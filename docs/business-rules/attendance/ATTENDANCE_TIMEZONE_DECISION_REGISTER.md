# Attendance — Time & Timezone Decision Register

**Created:** 2026-09-15
**Companion to:** [`ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md`](./ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md)
**Status:** **All 14 decisions RESOLVED, 2026-09-15** — 8 `SELECTED` / 5 `DEFERRED` / 1 `SUPERSEDED`
(`DEC-TZ-10`, whose recommendation the execution gate overrode by execution — see its entry).
**The authoritative artefact is** [`../../audits/ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md` §0](../../audits/ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md)
**— this register is the long-form rationale and now records each outcome inline.** Where the two
differ, the gate wins; the single instance is `DEC-TZ-10`, flagged explicitly in place.
**Signing surface:** [`../../audits/ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md` §17](../../audits/ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md#17-final-client-decision-register) — the consolidated client decision register, which supersedes this document as the thing to be approved and adds **`DEC-TZ-15`** (offline/mobile attendance policy) and **`DEC-TZ-16`** (punch load window). This register remains the long-form rationale for `DEC-TZ-01`…`DEC-TZ-14`.

Every entry below is a question the code currently answers *by default*, not by decision. The audit found no document in the repository that states the intended behaviour for any of them. Recommended answers are the auditor's opinion and carry no authority; they exist so the decision has a starting point, not so it can be skipped.

This register records **policy questions only**. Defects with an unambiguous correct answer (F-05 cross-midnight breaks, F-07 naive timestamps) appear here only where the fix requires a product choice.

---

## Summary

| ID | Question | Priority | Status | Blocks |
|---|---|---|---|---|
| DEC-TZ-01 | Is the client's clock allowed to be the authoritative attendance clock? | **P0 — BLOCKER** | **SELECTED** | Payroll; DEC-02/03/04 |
| DEC-TZ-02 | What clock-skew tolerance is acceptable? | **P0** | **SELECTED** (moot) | Punch validation |
| DEC-TZ-03 | May a punch be dated in the future? | **P0** | **SELECTED** | Punch validation |
| DEC-TZ-04 | How should a timestamp without an offset be interpreted? | **P0** | **SELECTED** | Dev/prod parity |
| DEC-TZ-05 | May an employee assert an arbitrary `source`? | P1 | **SELECTED** | Audit provenance |
| DEC-TZ-06 | Should punch rounding work, or be removed? | P1 | DEFERRED | Policy credibility |
| DEC-TZ-07 | Should night-OT use the configured window or the shift flag? | P1 | DEFERRED | OT rates |
| DEC-TZ-08 | Which timezone should the UI display attendance times in? | P1 | **SELECTED** | Multi-location rollout |
| DEC-TZ-09 | Does an employee need a timezone independent of their branch? | P2 | DEFERRED | Remote/travel policy |
| DEC-TZ-10 | Which date basis governs the period lock? | P2 | **SUPERSEDED** | Month-boundary integrity |
| DEC-TZ-11 | How should ambiguous/nonexistent local times resolve? | P3 | DEFERRED | DST-zone rollout |
| DEC-TZ-12 | When should attendance be calculated? | P2 | **SELECTED** | Operations |
| DEC-TZ-13 | May a company or branch timezone be changed once attendance exists? | P1 | **SELECTED** | Tenant config safety |
| DEC-TZ-14 | Should a DST transition change a shift's scheduled minutes, and therefore OT? | P1 | DEFERRED | DST-zone rollout |

---

## DEC-TZ-01 — Is the client's clock allowed to be the authoritative attendance clock?

**Question.** When an employee records a punch, should the attendance timestamp be the instant the *server* received the request, or a value the *client* supplies?

**Current implementation.** The client's. `service.py:2353` — `"punch_time": body.punch_time or now`. The server computes `datetime.now(UTC)` sixteen lines earlier but uses it only for `punch.created_at`; the two are never compared. `punch-entry-dialog.tsx:94` always sends `punch_time`, seeded from the browser clock and exposed as an editable `<input type="datetime-local">`. The server-time fallback is dead in every shipped flow.

**Why a decision is needed.** This is a genuine specification gap, not a deviation. The architecture is explicit about UTC storage and IANA business-day boundaries (ADR-0010; `WORKFORCE_ATTENDANCE_ARCHITECTURE.md:249`) and both are correctly implemented — but it says nothing about which clock is authoritative. Nothing in `WORKFORCE_ATTENDANCE_DECISION_LOG.md` or `docs/business-rules/attendance/` addresses it. Meanwhile the current default means any user holding the baseline `ATTENDANCE.PUNCH` permission controls their own `late_minutes`, `worked_minutes`, `ot_minutes_detected`, `paid_day_fraction`, and `lop_fraction` — the documented payroll inputs.

Note also that the same dialog serves two genuinely different acts: an employee marking their own arrival (where a server stamp is the obvious answer) and an administrator entering a correction for last Tuesday (where a supplied time is the whole point). The decision may need to distinguish them.

**Recommended answer.** **Server-generated for self-service punches; client-supplied permitted only for on-behalf/admin entry, which is already a separately permissioned act (`ATTENDANCE.PUNCH_ON_BEHALF`).** The mechanism already exists — `default_source` distinguishes the two paths at `router.py:783`.

**Alternatives.**
- *(A)* Server time always; admin corrections go exclusively through regularization, which has an approval chain.
- *(B)* Accept client time within a bounded skew (see DEC-TZ-02), store both, flag divergence for review.
- *(C)* Keep current behaviour, accepted as a documented business risk with compensating detective controls (e.g. an alert when `|punch_time − created_at|` exceeds a threshold).

**Impact.** Self-service punch UX (the time field would become read-only); the punch API contract; every downstream attendance figure; payroll trustworthiness.

**Priority.** **P0 — BLOCKER.** Determines the shape of DEC-TZ-02, 03 and 04.

**Status.** ✅ **SELECTED — server-authoritative for self-service.** Implemented as gate `DEC-TZ-01`: the self-service route has no `punch_time` field at all; on-behalf and regularization remain client-time-accepting and separately permissioned. Alternative (A) (admin corrections only via regularization) rejected — it removes a legitimate HR workflow; (B) bounded-skew and (C) detect-only rejected — both keep a forgeable field alive.

---

## DEC-TZ-02 — What clock-skew tolerance is acceptable?

**Question.** If client-supplied times are permitted at all, how far may `punch_time` diverge from the server's receipt time before the punch is rejected or flagged?

**Current implementation.** Unbounded in both directions. The only backstop is the period-lock check on the UTC date of `punch_time` (`service.py:2347`), which rejects a punch only if it lands inside an explicitly `CLOSED` period.

**Why a decision is needed.** Legitimate skew is real — unsynchronised devices, a dialog left open, network latency. An unbounded window is indistinguishable from fabrication. A threshold is needed to separate the two, and it is a business tolerance rather than a technical constant.

**Recommended answer.** **±120 seconds**, rejecting outside it. Generous enough for ordinary drift and a stale-but-reasonable form, tight enough that meaningful manipulation is impossible. `punch.created_at` already records the comparison point, so no schema change is needed.

**Alternatives.** ±30s (strict; risks false rejections on drifting devices) · ±5 min (lenient) · ±15 min (very lenient; a 15-minute lateness window is material) · accept-but-flag rather than reject.

**Impact.** Punch rejection rate; support load from users with drifting clocks; error-message design.

**Priority.** P0 (conditional on DEC-TZ-01 permitting client time).

**Status.** ✅ **SELECTED — moot for self-service; no tolerance elsewhere.** Superseded in substance by `DEC-TZ-01`: with no client timestamp on the self-service path there is no skew to tolerate, so the recommended ±120s threshold is **not implemented**. For the on-behalf path the bound is structural (`not in the future`), per gate `DEC-TZ-03`. Recorded as an engineering safety control, not a business attendance rule.

---

## DEC-TZ-03 — May a punch be dated in the future?

**Question.** Should the API accept a `punch_time` later than the server's current time?

**Current implementation.** Yes, without limit. *(Verified: `PunchCreate` accepts `2099-01-01T00:00:00Z`.)* No validator exists in the web form, the Pydantic schema, the service, or the database.

**Why a decision is needed.** There is no legitimate reason to record a punch that has not happened. The asymmetry is telling: regularization **does** reject future dates (`service.py:3502`, with a deliberate `EARLY_DEPARTURE_APPROVAL` carve-out documented as WD-32 decision 5), which suggests the punch path's omission is an oversight rather than a choice — but that should be confirmed, not assumed.

**Recommended answer.** **Reject any `punch_time` beyond the DEC-TZ-02 tolerance.** Mirror the regularization precedent, including an explicit carve-out only if a forward-dated punch use case is identified.

**Alternatives.** Allow a small forward window only (same as skew tolerance) · allow future punches for admin/on-behalf callers only · accept-but-flag.

**Impact.** Punch API contract; data quality (future-dated punches are inert orphans today — stored but never loaded by any calculation window, per audit §9).

**Priority.** P0.

**Status.** ✅ **SELECTED — no.** A punch dated later than server receipt time is refused outright, with no grace window (gate `DEC-TZ-03`). Not expressible at all on the self-service path.

---

## DEC-TZ-04 — How should a timestamp without a UTC offset be interpreted?

**Question.** A client sends `"2026-09-15T09:00:00"` with no offset. Is that UTC, the company timezone, the employee's work-location timezone — or invalid input?

**Current implementation.** None of these deliberately. *(Verified:* Pydantic yields a **naive** datetime; asyncpg then resolves it against the **Python process's OS timezone** — on the dev host, naive `09:00` stores as `03:30Z` (interpreted as IST), while `09:00Z` stores as `09:00Z`.*)* The API container sets no `TZ` and so defaults to UTC, while the dev host is `Asia/Kolkata`. **The same request therefore stores instants 5h30m apart in dev and production.**

**Why a decision is needed.** This is a silent, environment-dependent data-corruption path. It will not surface in testing — both environments behave self-consistently — and will only appear when data crosses between them or when a third-party client omits the offset. The current behaviour is an accident of the deployment environment, not a design.

**Recommended answer.** **Reject naive timestamps outright** — require an explicit offset (`Z` or `±HH:MM`) via an `AwareDatetime` annotation on `PunchCreate.punch_time`. Explicit beats inferred for a payroll input. **Independently, pin `TZ=UTC` in `apps/api/Dockerfile` and CI** so the two environments agree regardless of which answer is chosen.

**Alternatives.** Interpret naive as UTC (predictable, but silently wrong for a client that meant local) · interpret naive as the resolved attendance timezone (most "helpful", most surprising, and requires shift resolution the ingestion path deliberately does not do) · keep current behaviour (not recommended under any reading).

**Impact.** API contract for third-party/device integrations; dev-prod parity; the Dockerfile.

**Priority.** P0.

**Status.** ✅ **SELECTED — reject naive timestamps outright.** `AwareDatetime` plus a `BeforeValidator` rejecting non-`str` input (`ED-5`), because `AwareDatetime` alone accepts an epoch integer. `TZ=UTC` pinned in `apps/api/Dockerfile` and CI independently. Alternatives (interpret-as-UTC, interpret-as-local) rejected: inference is not acceptable for a payroll input.

---

## DEC-TZ-05 — May an employee assert an arbitrary punch `source`?

**Question.** Should an ordinary employee be able to set `source` to `DEVICE`, `IMPORT`, `ADMIN`, or `REGULARIZATION` on their own web punch?

**Current implementation.** Yes. *(Verified: all seven values are accepted by `PunchCreate`.)* `service.py:2355` — `"source": body.source or default_source`; the router's `default_source` (`WEB` for self, `ADMIN` for on-behalf) is only a fallback, overridden whenever the client supplies a value. The DB CHECK permits all seven.

**Why a decision is needed.** `source` is the provenance field an investigator would rely on to distinguish a biometric reading from a manual entry. If an employee can label a hand-typed web punch as `DEVICE`, that distinction is unreliable exactly when it matters.

**Recommended answer.** **Server-assign `source` from the authenticated context.** `REGULARIZATION` should be settable only by the regularization apply path (`service.py:4116`); `DEVICE`/`IMPORT`/`API` only by callers holding the corresponding integration permission.

**Alternatives.** Restrict by permission but still allow explicit override for integrations · keep `source` client-settable and add a separate server-assigned `ingestion_channel` column · accept as-is.

**Impact.** Punch API contract; audit and investigation reliability; future device integrations (W10).

**Priority.** P1.

**Status.** ✅ **SELECTED — no.** `source` is removed from every request schema and server-assigned from the authenticated route (`WEB`/`MOBILE` self, `ADMIN` on-behalf). Closes `F-11` structurally rather than by validation.

---

## DEC-TZ-06 — Should punch rounding work, or be removed?

**Question.** `AttendancePolicyVersion.punch_rounding` / `rounding_minutes` are configurable, validated, and exposed in the policy UI — but `apply_rounding` (`calculation.py:637`) is never called. Should rounding be wired in, or the configuration withdrawn?

**Current implementation.** Configurable and completely inert. A repository-wide grep finds only the function definition and one docstring mention. No test covers it.

**Why a decision is needed.** Silent no-op configuration is worse than absent configuration: an HR user who sets 15-minute rounding will believe it is applied. Fixing it *changes computed attendance* for every tenant that has configured a value, so it cannot be treated as a routine bug fix — it needs a deliberate decision and, if enabled, a communicated recompute.

**Recommended answer.** **Wire it in**, applying to a *copy* of the punch instant for evaluation only — which is exactly what the function's own docstring already specifies ("the raw punch timestamp is never mutated (WD-11)"). Audit which tenants have non-`NONE` values first; recompute affected open periods deliberately, not silently.

**Alternatives.** Remove the fields and their UI (honest, but discards designed functionality) · leave inert and document the limitation (not recommended — the UI actively misleads) · wire in behind a per-tenant opt-in flag.

**Impact.** Computed attendance for every tenant with rounding configured; historical recompute; policy UI.

**Priority.** P1.

**Status.** ⏸️ **DEFERRED — explicitly out of scope for this programme.** Punch rounding has no approved policy and `apply_rounding` has zero call sites (`F-04`). Named once as `CLIENT DECISION REQUIRED` in gate §19.1 and deliberately excluded from every phase. Not implemented, not withdrawn.

---

## DEC-TZ-07 — Should night-OT classification use the configured window or the shift flag?

**Question.** `OvertimePolicyVersion.night_window_start` / `night_window_end` are configurable and loaded into the engine, but `calculation.py:1237` sets `is_night = shift.is_cross_midnight` and never reads the window. Which should govern?

**Current implementation.** The shift flag. `night_ot_mode="WINDOW"` therefore behaves identically to `"BOTH"`, and a day shift extending into the configured night window is never classified `NIGHT` for rate lookup.

**Why a decision is needed.** Night OT typically attracts a premium rate. The configuration implies overtime hours falling inside the window earn it; the implementation grants it only to shifts flagged cross-midnight. Which is correct is a compensation-policy question, and the two give different pay.

**Recommended answer.** **Honour `night_ot_mode` as designed** — `SHIFT_FLAG` uses the flag, `WINDOW` uses the configured window, `BOTH` uses either. The three-valued enum already encodes the intent; only the engine's implementation is missing.

**Alternatives.** Remove the window fields and keep `SHIFT_FLAG` only · keep current behaviour and document `WINDOW` as unimplemented (not recommended — the mode is selectable in the UI).

**Impact.** OT rate classification; payroll cost; the OT policy UI.

**Priority.** P1.

**Status.** ⏸️ **DEFERRED — neither implemented nor withdrawn** (gate `DEC-TZ-09`/`CD-6`). A pay-policy decision, not a timezone decision. `calculation.py:1237` is explicitly not touched. The inertness of `WINDOW`/`BOTH` is documented so HR is not misled meanwhile.

---

## DEC-TZ-08 — Which timezone should the UI display attendance times in?

**Question.** When an HR user in one timezone reviews an employee's attendance in another, which zone should the displayed times use?

**Current implementation.** The **viewer's browser timezone**. `format.ts:16,21` pass `undefined` as locale to `toLocaleTimeString`/`toLocaleString`, taking both locale and zone from the browser. The API returns `attendance_day.timezone` and the day-detail page even prints it as a subtitle (`attendance/[id]/page.tsx:110`), but no formatter consumes it. No timezone label accompanies any rendered time.

**Why a decision is needed.** Today every user is presumed to be in one zone, so nothing is visibly wrong. The moment a second location or a remote reviewer exists, displayed times and the `late_minutes` shown beside them will have been computed in different zones — with no indication to the reader. The data needed to fix this is already on the wire.

**Recommended answer.** **Display in `attendance_day.timezone` with an explicit label** (e.g. `09:05 IST`). The attendance day *has* a timezone and it is already returned; showing a time in a different zone from the one its own late/early figures were computed in is misleading regardless of who is looking.

**Alternatives.** Viewer's zone with an explicit label and a converted-from note · a user preference toggle · show both.

**Impact.** All attendance display surfaces; multi-location rollout readiness.

**Priority.** P1 (rises to P0 at the moment a second timezone goes live).

**Status.** ✅ **SELECTED — display in the resolved attendance timezone with an explicit `IST` label.** Implemented as gate `DEC-TZ-06`/`CD-3`, including the `DEC-010` amendment naming the WD-06-resolved zone rather than the literal `company.timezone` column. Viewer-zone and user-preference alternatives rejected: a figure must render in the zone it was computed in.

---

## DEC-TZ-09 — Does an employee need a timezone independent of their branch?

**Question.** A Kerala-based employee works remotely from Dubai for a month. Which timezone governs their attendance?

**Current implementation.** The branch's. Precedence is `ShiftVersion.timezone > Branch.timezone > Company.timezone` (`calculation.py:294-298`, matching documented policy WD-06). **There is no employee-level timezone column anywhere in the schema.** Behaviour in the brief's scenarios:

- *Office employee (Kerala)* — Branch timezone applies. Correct.
- *Transfers office* — `EmployeeAssignment` is resolved as-of the date, so the new branch's timezone applies from its `effective_from`. Historical days keep the old zone. Correct.
- *Remote employee* — Branch timezone applies regardless of physical location. **Possibly wrong, depending on policy.**
- *Temporary travel* — Branch timezone applies; the traveller's local wall-clock times are judged against the home zone's schedule. **Possibly wrong.**
- *Missing timezone* — Cannot occur. `Company.timezone` is NOT NULL with a default, so resolution never fails. A sensible fail-safe.
- *Rostered onto a differently-zoned shift* — `ShiftVersion.timezone` silently re-anchors the whole day. A faithful consequence of WD-06, but an undocumented sharp edge.

**Why a decision is needed.** The scenarios differ in what the business intends, not in what the code does. If a travelling employee is expected to work home-office hours, current behaviour is correct and no change is needed. If they are expected to work local hours, there is no mechanism to express that. Adding an employee-level timezone would also require extending WD-06's locked precedence chain — an architecture change, not a config change.

**Recommended answer.** **Keep the current chain for V1** and document explicitly that attendance is judged in the work-location's timezone regardless of physical presence. Revisit only when a real remote-work or multi-timezone requirement is confirmed; do not pre-build it.

**Alternatives.** Add `Employee.timezone` between Shift and Branch in the precedence chain · add a temporary per-date timezone override (effectively a roster-level timezone) · require a branch transfer for extended remote work.

**Impact.** WD-06's locked precedence; the employee schema; remote-work policy.

**Priority.** P2 (P0 if a multi-timezone client is onboarded).

**Status.** ⏸️ **DEFERRED — no employee-level timezone in India V1.** Product scope decision, restated in the gate's India V1 scope block. Nothing implemented.

---

## DEC-TZ-10 — Which date basis governs the period lock?

**Question.** When checking whether a punch falls in a closed period, should the check use the **UTC** date of `punch_time` or the **local attendance date**?

**Current implementation.** The UTC date, for punches (`service.py:2347`). Every other caller of `_ensure_date_open` passes a local `attendance_date`. The code documents this as a deliberate approximation (WD-30, `service.py:2338-2346`): the local attendance date is not knowable before shift resolution, which itself depends on the date. The stated backstop — `calculate()` refuses a locked day outright, so a boundary-straddling punch is at worst an inert orphan — holds.

**Why a decision is needed.** For an `Asia/Kolkata` tenant, any `punch_time` between `18:30Z` and `24:00Z` has a UTC date one day behind its local date. A punch at 23:00 IST on the first day of a newly-opened period is lock-checked against the previous date, which may still be closed. The failure is *closed* (safe direction), but it produces a confusing rejection at exactly the month boundary where attention is highest.

**Recommended answer.** **Accept the current approximation and document it in client-facing material.** The reasoning is sound, the failure direction is safe, and resolving it properly would require shift resolution during ingestion — a significant architectural change for a narrow edge case. Confirm the client accepts an occasional month-boundary rejection.

**Alternatives.** Resolve the attendance date during ingestion (correct, expensive) · widen the lock check by ±1 day (fails closed more often) · check both the UTC and company-local dates and require both to be open.

**Impact.** Month-boundary punch acceptance; period-close operational procedure.

**Priority.** P2.

**Status.** 🔄 **SUPERSEDED — recommendation NOT selected.** This entry recommended accepting the current UTC-date approximation. The execution gate re-derived the behaviour by executing the shipped window functions (§10) and found the approximation **asymmetric**: it can permanently and unrecoverably lose a genuine early-shift punch. **Selected instead (gate `DEC-TZ-05`/`CD-1`): accept when either the local (IST) date or the previous local date is open; refuse only when both are closed**, shipped together with the orphan-punch report. This is closest to this entry's own fourth alternative, inverted from `require both open` to `require either open`. The gate document outranks this register (gate §'Source of truth and its hierarchy').

---

## DEC-TZ-11 — How should ambiguous and nonexistent local times resolve?

**Question.** In a DST-observing zone, some local wall-clock times occur twice and others never occur. How should a shift time or requested punch time falling in those windows be resolved?

**Current implementation.** Silently, via `ZoneInfo`'s default `fold=0`. *(Verified: `America/New_York` `2026-03-08 02:30` — which does not exist — yields `07:30Z`, i.e. `03:30 EDT`; `2026-11-01 01:30`, which occurs twice, yields `05:30Z`, the first occurrence.)* Deterministic and defensible, but no warning is raised and no policy is recorded.

**Why a decision is needed.** Only if DST-observing locations are actually supported. **DST itself is handled correctly** — *(verified: `Europe/London` `22:00→06:00` spans 9 hours across the autumn transition and 7 hours across the spring one, both the true elapsed times)* — so this is about the two narrow transition windows, not about DST generally. A shift scheduled to start at 02:30 on a spring-forward date would silently start an hour later than configured.

**Recommended answer.** **Document `fold=0` as the policy** (first occurrence for ambiguous; shift forward for nonexistent) and **warn at shift-publish time** if a shift's start or end falls in a transition window for its configured zone. Do not change the resolution behaviour — it is already the conventional choice.

**Alternatives.** Reject nonexistent times at publish time · `fold=1` for ambiguous (second occurrence, i.e. the longer elapsed day) · explicit per-shift configuration.

**Impact.** Only tenants in DST-observing zones. Currently none — all defaults are `Asia/Kolkata`, which has no DST.

**Priority.** P3 (rises to P1 before any DST-zone client is onboarded).

**Status.** ⏸️ **DEFERRED — documented, not implemented.** `fold=0` recorded as the policy. No DST business logic is added for India V1, which has no DST; the underlying engine's existing DST handling is left untouched and uncorrupted (gate Part 11 constraint).

---

## DEC-TZ-12 — When should attendance be calculated?

**Question.** `attendance_day` rows exist only where `POST /attendance/days/calculate` or `/recompute` was explicitly called. `core/celery_app.py` defines four beat entries, all `leave.*`; **no attendance task exists**. When should attendance actually be computed?

**Current implementation.** On demand only. Nothing computes attendance automatically. An employee who punches in and out has no `attendance_day` row until something asks for one.

**Why a decision is needed.** Not a timezone question, but it governs *when* everything in this register actually executes — and the answer is timezone-dependent. A nightly job must run after the last shift ends **in the latest timezone the tenant operates in**, and cross-midnight shifts are not complete until the following morning. A job scheduled at "01:00" is ambiguous until DEC-TZ-08/09 settle whose midnight that is.

**Recommended answer.** **A scheduled per-tenant recompute of the trailing N days** (N ≈ 3, to absorb late punches, approved regularizations, and cross-midnight completion), scheduled in each tenant's own attendance timezone. Keep the on-demand endpoints for interactive use.

**Alternatives.** Compute synchronously on each punch (expensive; a day is incomplete until the last punch anyway) · compute lazily on read (unpredictable latency; hides missing data) · compute only at period finalization (too late for employees to see or dispute their own attendance).

**Impact.** Background job architecture; data freshness; when employees can see their own attendance.

**Priority.** P2 (P0 before production — without this, attendance is effectively invisible until someone asks for it).

**Status.** ✅ **SELECTED — daily at 09:30 `Asia/Kolkata`, trailing 3 days**, plus a best-effort non-blocking calculation after each punch insert. Implemented as gate `DEC-TZ-07`/`CD-4`. The job must call `business_today()` explicitly, never `datetime.now(UTC).date()`.

---

## DEC-TZ-13 — May a company or branch timezone be changed once attendance exists?

**Question.** Once attendance days have been computed, may `Company.timezone` or `Branch.timezone` still be edited — and if so, what happens to attendance already calculated in the old zone?

**Current implementation.** Unrestricted. `OrganisationService._assert_timezone_change_allowed` (`organisation/service.py:702-709`) is an explicit empty no-op whose docstring defers the guard *"until Payroll/Attendance modules exist (Domain Model §5.5)"* — a precondition that has since been met. `update_branch` never calls the hook at all, so `Branch.timezone` (the middle link of the WD-06 chain) is entirely unguarded. `attendance_day` records the timezone it was computed in, but `recompute` re-resolves it by date rather than reusing the stored value, so any historical day later recomputed silently adopts the new zone — changing `late_minutes` and `worked_minutes` on already-reviewed attendance.

**Why a decision is needed.** The hook exists precisely because someone anticipated this and chose to defer it. Deciding *what* the guard should enforce is a business question: a genuine correction (the branch was configured wrong on day one) and a genuine relocation (the office moved) want opposite treatments — the first wants a recompute, the second wants history preserved in the old zone.

**Recommended answer.** **Refuse a timezone change while any attendance period is open with computed days**, and require an explicit, acknowledged recompute otherwise. Call the guard from `update_branch` as well as `update_company`. If a distinction between correction and relocation is wanted, an effective-dated branch timezone would be the clean expression of it — but that is a schema change and should not be assumed.

**Alternatives.** Allow the change but pin each `attendance_day` to its stored `timezone` on recompute (preserves history; diverges from the recompute-re-resolves-everything principle in WD-11) · allow freely with a prominent warning · forbid entirely once any punch exists.

**Impact.** Company and branch settings UI; historical attendance stability; the WD-11 reproducibility posture.

**Priority.** P1.

**Status.** ✅ **SELECTED — no, blocked outright once computed attendance exists** for the affected scope, with the existing `TRIAL`/zero-rows hatch preserved and a `CLOSED`-period refusal that is absolute and checked first. Implemented as gate `DEC-TZ-04`/`CD-8`. Effective-dated timezone configuration is deferred, not discarded.

---

## DEC-TZ-14 — Should a DST transition change a shift's scheduled minutes, and therefore OT?

**Question.** A `22:00–06:00` shift is 8 hours by the clock. On a fall-back night it occupies 9 real hours; on a spring-forward night, 7. Should `scheduled_minutes` follow real elapsed time — and with it OT eligibility, which is computed as `worked − scheduled`?

**Current implementation.** Real elapsed time, and the arithmetic is correct. *(Verified by executing the shipped code: `Europe/London` and `America/New_York` both give 540 minutes on the fall-back night and 420 on the spring-forward night; `Asia/Kolkata` gives 480 as a control.)* Two consequences follow, neither of them documented:

- An employee who works the **full wall-clock shift** on a fall-back night is credited 540 worked minutes against 540 scheduled — **zero OT for nine real hours**.
- An employee who works **eight real hours** that night (leaving at 05:00 local) is flagged **60 minutes early departure**.
- On a spring-forward night, a full wall-clock shift is 420 real minutes and earns a **full day's credit for seven real hours**.

**Why a decision is needed.** Each of those is defensible, and they are mutually consistent — the shift is defined in wall-clock terms, so working it costs whatever real time that takes. But they are consequences nobody chose. An employee working nine real hours and receiving no overtime is the kind of outcome that surfaces as a grievance rather than a bug report, and in some jurisdictions the answer is a legal question rather than a policy one.

**Recommended answer.** **Keep the current behaviour** — wall-clock shift definitions with real-elapsed scheduling is the conventional interpretation and is internally consistent — and **document it explicitly** before onboarding any DST-observing tenant, so payroll and HR can answer the question when it is asked. Revisit only if a jurisdiction's law requires otherwise.

**Alternatives.** Cap `scheduled_minutes` at the nominal wall-clock duration so the extra hour becomes OT · treat the transition hour as a separate paid-but-not-scheduled allowance · make the choice a per-tenant policy flag.

**Impact.** OT cost on two nights a year per DST tenant; early-departure flags on one of them; payroll explainability.

**Priority.** P1 before any DST-zone client; not applicable to India.

**Status.** ⏸️ **DEFERRED — current behaviour kept and documented.** Wall-clock shift definitions with real-elapsed scheduling. No DST business rule is added for India V1. Revisit before onboarding any DST-observing tenant.

---

## Decision dependency order

```
DEC-TZ-01  (authoritative clock)      ← BLOCKER, decide first
    ├── DEC-TZ-02  (skew tolerance)
    ├── DEC-TZ-03  (future timestamps)
    └── DEC-TZ-04  (naive timestamps)      ← also fix TZ=UTC in Dockerfile regardless

DEC-TZ-05  (source forgery)           ── independent
DEC-TZ-06  (rounding)                 ── independent, changes computed attendance
DEC-TZ-07  (night OT window)          ── independent, changes OT rates
DEC-TZ-08  (display timezone)         ── independent
    └── DEC-TZ-09  (employee timezone)     ← only if multi-timezone is real
DEC-TZ-10  (period lock basis)        ── independent, likely "accept as documented"
DEC-TZ-11  (DST edge times)           ── only if a DST zone is onboarded
DEC-TZ-12  (calculation schedule)     ── depends on DEC-TZ-08/09 for "whose midnight"
DEC-TZ-13  (timezone change guard)    ── independent; hook already exists, unimplemented
DEC-TZ-14  (DST scheduled minutes)    ── only if a DST zone is onboarded; pairs with DEC-TZ-11
```

---

*No application code was modified in producing this register. Behaviour described as "verified" was reproduced by executing the shipped code read-only; all other statements are direct source citations. Recommended answers are the auditor's opinion, offered as a starting point for the decision — not as the decision.*

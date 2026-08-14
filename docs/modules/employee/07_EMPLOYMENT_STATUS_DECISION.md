# Employment Status Decision

Status: **Investigation only — no code, migration, or schema changed.** Scope is narrower than
`00_EMPLOYEE_AUDIT.md`: this resolves exactly one open item (`employment.status`'s literal value
set) that blocks E-03, by exhaustively citing every place the seven authoritative Employee/E-01
documents and their referenced SRS/PRD/ADR/design sources touch it. Nothing below is invented —
every proposed value is either directly quoted from a source document or explicitly labeled as
this document's own recommendation, not a settled fact.

---

## 1. Current Problem

E-03 (Employment Lifecycle) is the slice that adds the `Employment` ORM model, the FR-EMP-014-
adjacent lifecycle logic, and the rejoin mechanism on top of the live `employment` table. Its own
migration must add a `status` column value set (or formalize the existing undocumented one) before
any application code can validate transitions, gate an exit-initiation action, or let Attendance's
"active employment on date Y" query (`01_EMPLOYEE_MODULE_PLAN.md` §3 item 3) be answered.

No authoritative document enumerates `employment.status`'s values. This was already flagged, not
newly discovered here:

- `00_EMPLOYEE_AUDIT.md` §5, conflict row 3: "`employment.status` value set is undefined."
- `00_EMPLOYEE_AUDIT.md` §16, E-03 row: "Rejoin (§17.1) and `employment.status` value-set (§5 row
  3) must both be settled before this starts."
- `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1: marks this "**REQUIRES PRODUCT DECISION**" and
  states plainly: "Neither `00_EMPLOYEE_AUDIT.md` nor its companions contain the full FR-EMP-014
  ten-state enumeration for `employee.status` either — it is referenced by name and count only,
  never listed. This document does not invent either enumeration."
- `06_EMPLOYEE_FOUNDATION_IMPLEMENTATION_REPORT.md` §15: names this as E-03's blocking item and
  explicitly declines to invent values, consistent with this task's own instruction.

Starting E-03's migration without this resolved risks the exact failure mode both
`00_EMPLOYEE_AUDIT.md` §18 and `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part H warn about: a second
migration shortly after the first, on the second table Employee's implementation touches.

---

## 2. Evidence From Existing Documentation

| Source | Relevant statement | Implication |
|---|---|---|
| `docs/product/08_Database_Architecture.md` §5.2 | `employment` column list ends `..., previous_employment_id, status` — no parenthetical enumeration. Contrast with the *same document*, same section family: `employee.gender` → `MALE/FEMALE/OTHER/UNDISCLOSED`, `employee_assignment.work_location_type` → `(OFFICE/WFH/HYBRID/FIELD)`, `employee_compensation.revision_type` → `(JOINING/ANNUAL/PROMOTION/CORRECTION/MARKET)`, `employee_statutory.tax_regime` → `(OLD/NEW)`, `employee_bank.payment_mode` → `(BANK/CASH/CHEQUE/UPI)`. | The document's authors enumerate values everywhere else in this exact table family; `employment.status` is a genuine, apparently deliberate gap in an otherwise-consistent document, not an inconsistent formatting choice. |
| `docs/product/08_Database_Architecture.md` §5.1 | `employee.status | VARCHAR(25) | see Document 17` — points to a named, external, fully-enumerated source. `employment.status` has no equivalent pointer anywhere. | `employee.status` was deliberately cross-referenced to its source; `employment.status` was not given one, because none exists. |
| `docs/product/17_SRS_Phase1_Core_Modules.md` FR-EMP-014 | "Employee statuses: `PRE_JOINING`, `PROBATION`, `ACTIVE`, `ON_NOTICE`, `SUSPENDED`, `ON_LONG_LEAVE`, `EXITED`, `ABSCONDING`, `RETIRED`, `DECEASED`. State-machine transitions only." | This is the full, only enumerated 10-state list in any source document — and it is explicitly titled "**Employee** statuses," i.e. `employee.status`, not `employment.status`. No FR-EMP-* item enumerates an `employment`-level list. |
| `docs/archive/superseded-v1-nestjs/04_Database_Design_and_Data_Dictionary.md` §5.2 | Identical, word-for-word `employment` column list and "status" mention (no enumeration), predating Doc 08. | The gap is not new to the current documentation generation — it has never been resolved across two independent document authorships, reinforcing that this is a genuine unaddressed gap rather than an editing slip in one document. |
| `docs/product/02_PRD.md` §11 (Terminology) | "**Employment**: A time-bounded relationship between an Employee and a Legal Entity. Supports rehire and inter-entity transfer." No status/state language at all. | The canonical definition of Employment describes its *shape* (time-bounded, 1:N) but says nothing about what states a spell can be in. |
| `docs/product/17_SRS_Phase1_Core_Modules.md` FR-EMP-011 | "inter-entity transfer... closes one employment and opens another." | Confirms an employment spell has a "closed" terminus — direct textual evidence for at least one terminal state, without naming it. |
| `docs/product/17_SRS_Phase1_Core_Modules.md` FR-EXT-002/003 | Notice-period computation, buyout/waiver, garden leave; resignation acceptance workflow with a negotiable last working day and pre-acceptance withdrawal. | Describes a real, distinct period between "resignation initiated" and "last working day reached" — a plausible spell-scoped state, but never named as an `employment.status` value anywhere. |
| `docs/product/17_SRS_Phase1_Core_Modules.md` AC-EXT-010.1 | "...then at 23:59 on 31-Aug their user account is disabled... and their status becomes `EXITED`." | Uses the bare word "status," not qualified as `employee.status` or `employment.status`. Given `EXITED` is one of FR-EMP-014's named `employee.status` values and no equivalent `employment.status` enumeration exists anywhere, this most plausibly refers to `employee.status` — but the AC's own wording does not disambiguate, so it is cited here as suggestive, not conclusive, evidence. |
| `docs/design/screens/01_Employee_List_Directory.md` §3 | Directory filter field: "Employment status (Active / On leave / Notice period / Exited) — defaults to Active only." | The only place in any source document where the literal phrase "Employment status" is paired with a concrete value list. Structurally ambiguous: it may be a UI-level bucketing of `employee.status`'s 10 values (`ON_LONG_LEAVE`→"On leave", `ON_NOTICE`→"Notice period", etc. — all four bucket labels map cleanly onto FR-EMP-014 values), or it may describe the `employment.status` column directly. No document states which. Treated below as supporting evidence for the *shape* of the lifecycle (open → notice → closed, plus a leave-like pause), not as a settled literal enum for the DB column. |
| `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1 | "`employment.status` should be a narrow subset scoped to one spell (e.g. `ACTIVE` / `ON_NOTICE` / `TERMINATED`), never a copy of the full `employee.status` machine... This narrowing principle is locked; the literal string values are not." | This project's own prior recommendation (not a product-approved source) — proposes `TERMINATED` as the closed-state name, distinct from `employee.status`'s `EXITED`. Flagged in its own text as a recommendation requiring sign-off, not a decision. |
| `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D (rehire walkthrough) | "`employment #1` created (`joining_date=2027-06-01`, `legal_entity_id=X`, `status=ACTIVE`)." Later: "`employment #1.exit_date = 2030-09-30`, `status → TERMINATED`/`EXITED`." | Even this project's own architecture-decision document could not settle on one terminal-state name for `employment.status` — it names both `TERMINATED` and `EXITED` side by side with a slash, which is itself direct evidence the ambiguity was never resolved, only narrated around. `status=ACTIVE` for the open state is used unhedged, by contrast — no ambiguity there. |
| `00_EMPLOYEE_AUDIT.md` §5, conflict row 3 | "Decide whether `employment.status` reuses the same enum or has a narrower set (e.g. **ACTIVE/EXITED only**)." | A second, independent proposal from the same document family — a minimal *two*-state set, using `EXITED` (not `TERMINATED`) as the closed-state name. Disagrees with A1's `TERMINATED` proposal on naming, agrees with it on "narrow, not a copy of employee.status." |
| `00_EMPLOYEE_AUDIT.md` §13.4 | Recommended audit-action convention: "`employment`: `EMPLOYMENT_STARTED`, `EMPLOYMENT_UPDATED`, `EMPLOYMENT_TERMINATED`, `EMPLOYMENT_REHIRED`." | Audit *action* names, not `status` column values — but `EMPLOYMENT_TERMINATED` as the exit-side action name is one more data point leaning toward `TERMINATED` as the vocabulary this codebase associates with an employment spell ending, as distinct from `EXITED` (used for the employee identity). |
| `docs/product/08_Database_Architecture.md` §5.2 | `employment` also carries an undocumented `exit_type` column (no enumeration given, same pattern as `status`). | A related, separately-undefined field — `exit_type` is the *reason/manner* of closure (voluntary/involuntary/retirement/etc., per FR-EXT-001's four employer-initiated categories plus resignation), while `status` is the *state* of the spell. These are two different open gaps; only `status` blocks E-03 per the module plan's own scoping (§4 below). |
| `01_EMPLOYEE_MODULE_PLAN.md` §2 "E-03" | "this slice only needs `employment.status → EXITED` and `last_working_day` to be settable" (paraphrasing the exit-initiation hook's thin scope). | The module plan itself, when describing E-03's *minimal* exit-initiation need, reaches for the word `EXITED`, not `TERMINATED` — a third, independent data point using `EXITED`. |

---

## 3. Employee Status vs Employment Status

These are two different concepts, already separated by this project's own locked architecture
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C, B1–B2) and reinforced by every source document
cited above:

- **`employee.status`** describes the **identity's** overall standing, independent of whether any
  `employment` spell is currently open. Its 10-state FR-EMP-014 machine includes states that only
  make sense at the identity level and have no per-spell meaning — `PRE_JOINING` (no employment has
  started yet — there may be no `employment` row at all), `DECEASED` (an identity-level fact, not a
  property of one employment spell), `RETIRED` (typically describes the identity's terminal
  standing after its last spell closes, not a mid-spell condition).
- **`employment.status`** describes one **continuous spell's** own state — whether *this specific*
  employment episode (at *this specific* legal entity, starting on *this specific* joining date) is
  currently open or closed, and optionally, moving toward closure. It says nothing about the
  identity as a whole; a rehired employee has two `employment` rows, each with its own independent
  `status`, while having exactly one `employee.status` value at any point in time.
- **Why copying the 10-state machine onto `employment` would be wrong** (per
  `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1, reaffirmed here): several `employee.status` values
  are structurally meaningless on an `employment` row. `employment.status = PRE_JOINING` on a row
  that, by FR-EMP-002, cannot exist without a `joining_date` already recorded, is a contradiction —
  either the spell has a start date and is at least nominally open, or the row shouldn't exist yet.
  Similarly, `DECEASED`/`RETIRED` describe the *identity's* terminal standing, not a fact about one
  employment spell in isolation (an employee who dies while employed at Legal Entity A has exactly
  one `employment` row that closes — the interesting fact lives on `employee.status`, and
  `employment.status`'s job is only to record that the spell ended, via whatever generic
  "closed" value is chosen, with `exit_type` carrying the "why").
- **Consequence for this decision**: `employment.status`'s value set must be independently derived
  from what a *spell* — not an identity — can be, using only the states the documented employment
  lifecycle (§4) actually requires. This is exactly the exercise `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
  A1 started and left unfinished (principle locked, literal values not).

---

## 4. Required Employment Lifecycle

Assembled only from what the documented FR-EMP-*/FR-EXT-* requirements and the locked rehire model
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B2/D) actually describe an `employment` spell doing,
without adding any state beyond what's textually supported:

1. **A spell begins.** `POST /v1/employees` (or the future rehire entry point) creates an
   `employment` row with `joining_date` set (FR-EMP-002: joining date is mandatory at creation).
   This is the only creation path any document describes for V1 — no separate "offer accepted, not
   yet joined" employment-row state exists, because ATS/candidate coupling is explicitly out of
   scope (`00_EMPLOYEE_AUDIT.md` §12, already locked).
2. **A spell is ongoing.** The normal condition for the length of the employment — `exit_date`/
   `last_working_day` unset. FR-EMP-010/011/012/013 (confirmation, transfer, promotion, manager
   change) all happen during this condition and do not themselves change which `employment` row is
   open — they write to `employee_assignment`/`employee_compensation`, or (for inter-entity
   transfer, FR-EMP-011) close this spell and open a new one, which is item 4 below, not a
   same-row transition.
3. **A spell is ending, but not yet closed.** FR-EXT-001/002/003 describe a real, documented
   window: resignation or employer-initiated exit has been *initiated* (a proposed/negotiated last
   working day exists, notice period is running, withdrawal is still possible before acceptance),
   but the person is still actively employed until that date arrives. This is the one point in the
   evidence (§2) where source documents disagree on whether it needs its own `employment.status`
   value or can be represented without one (§6).
4. **A spell closes.** `exit_date`/`last_working_day` set (FR-EXT-001 exit initiation, FR-EMP-011's
   "closes one employment" for inter-entity transfer, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part
   D's worked example). This is permanent — the row is never reopened; a later rejoin creates a
   **new** `employment` row (`is_rehire=true`, `previous_employment_id` set — already locked).
   Inter-entity transfer (FR-EMP-011) and voluntary/involuntary exit (FR-EXT-001) both terminate a
   spell the same way from `employment.status`'s point of view — the two scenarios are
   distinguished by `exit_type` (a separate, also-undefined field, §2 — not this document's scope
   to resolve) and by whether a new `employment` row happens to exist at a different legal entity,
   not by a different `status` value.

No document describes an `employment` row being deleted, reopened, or existing in a state other
than these four points on one line — there is no evidence for a "cancelled before starting," "on
hold," or "draft" employment state anywhere in the source set (§7).

---

## 5. Proposed Status Values

Only values directly supported by §2's evidence, or explicitly marked as this document's own
recommendation where the sources disagree:

| Value | Meaning | Entry condition | Exit condition | Source |
|---|---|---|---|---|
| `ACTIVE` | The spell is open and ongoing (lifecycle point 2). | Set at row creation (`joining_date` recorded, FR-EMP-002). | Moves to the notice-window value (if adopted, §6) or directly to the closed value, on exit initiation / inter-entity transfer. | `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D ("`status=ACTIVE`" at creation, unhedged — the one value with no naming disagreement anywhere in the evidence). |
| `ON_NOTICE` *(optional — see §6 for the case against)* | Exit has been initiated (resignation accepted or employer-initiated exit begun); last working day is set but not yet reached (lifecycle point 3). | Resignation acceptance (FR-EXT-003) or employer-initiated exit start (FR-EXT-001), once a `last_working_day` is recorded. | Reaching `last_working_day` closes the spell; withdrawal before acceptance (FR-EXT-003) returns to `ACTIVE`. | FR-EXT-002/003 (notice-period computation, negotiable LWD, pre-acceptance withdrawal); `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1's own proposed value name; the Directory filter's "Notice period" bucket (`01_Employee_List_Directory.md` §3, ambiguous per §2 but directionally consistent). |
| `TERMINATED` **or** `EXITED` *(name not settled — see below)* | The spell has permanently ended (lifecycle point 4). | `exit_date`/`last_working_day` reached, or inter-entity transfer closes this spell (FR-EMP-011). | Terminal — never reopened; a later rejoin is a new `employment` row (locked, §3). | FR-EMP-011 ("closes one employment"); `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D (names both `TERMINATED` and `EXITED` without choosing, direct evidence of the unresolved naming conflict); `00_EMPLOYEE_AUDIT.md` §5 row 3 (proposes `EXITED` for a 2-state set); `01_EMPLOYEE_MODULE_PLAN.md` §2 E-03 (reaches for `EXITED` when describing the minimal exit-initiation need); `00_EMPLOYEE_AUDIT.md` §13.4 (proposes the audit action `EMPLOYMENT_TERMINATED`, leaning `TERMINATED` for the column value by association). |

**The terminal-value name is the one piece of this decision no source document resolves, even
provisionally.** Both `TERMINATED` and `EXITED` appear in the evidence, from different documents,
with no document stating a preference between them or acknowledging the other exists. This
document's recommendation, offered for product approval rather than asserted as settled: use
`TERMINATED` for `employment.status`, reserving `EXITED` exclusively for `employee.status`
(FR-EMP-014's own spelling) — so the two columns never share a literal string value that means two
different things at two different scopes, which would be confusing in shared logs, audit rows, and
UI copy that may show both side by side (e.g. the 360° profile's persistent header showing
`employee.status` next to a Job tab listing `employment.status` history). This is a naming-hygiene
argument, not a sourced requirement — product may equally reasonably choose `EXITED` for both
(accepting the shared vocabulary) given two of the four evidence points above already lean that
way.

---

## 6. Recommended Minimal State Set

Two candidate minimal sets are both defensible from the evidence; this document does not collapse
them into one without flagging the trade-off, per the instruction not to invent past what's
justified.

**Option A — three states: `ACTIVE` / `ON_NOTICE` / `TERMINATED`.**
Matches `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1's own proposal exactly. Gives the notice-period
window (lifecycle point 3, FR-EXT-002/003) its own explicit, queryable state — useful for the
Directory's "Notice period" filter bucket and for any future report that needs "who's leaving in
the next N days" without re-deriving it from a raw date comparison every time.

**Option B — two states: `ACTIVE` / `TERMINATED` (or `EXITED`).**
Matches `00_EMPLOYEE_AUDIT.md` §5 row 3's alternative proposal. The notice-period window is not a
distinct `status` value at all — it is *derived*, not stored: `status = ACTIVE AND
last_working_day IS NOT NULL AND last_working_day >= current_date` **is** "on notice," using
columns (`date_of_resignation`, `last_working_day`) that `02_EMPLOYEE_DATA_MODEL.md` §3 already
adds to `employment` regardless of which option is chosen. This mirrors how this codebase already
treats "is this the current row" for effective-dated tables — `effective_to IS NULL`, a derived
condition, not a stored flag (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` B7) — so Option B is more
consistent with an existing convention in this same codebase than Option A is.

**This document's recommendation: Option B is the smaller state set that still satisfies every
documented requirement in §4**, because nothing in FR-EXT-002/003 requires "on notice" to be a
*stored* state rather than a *computed* one — the underlying facts (`last_working_day` set, not yet
reached) are already columns on the same row. Option A is not wrong — it trades one extra stored
value for not having to compute the notice window on every read — but it is not the *minimal* set
the task asks for. Both options are presented in §5's table (`ON_NOTICE` marked optional) so
product can pick either without this document re-deriving the evidence again.

**Either option, the value for the open state is `ACTIVE`** — the one value with zero naming
disagreement anywhere in the evidence (§2, §5).

---

## 7. States Explicitly Rejected

- **The full FR-EMP-014 ten-state `employee.status` machine, copied onto `employment.status`.**
  Rejected per §3: several of its values (`PRE_JOINING`, `DECEASED`, `RETIRED`) describe the
  identity, not a spell, and would be structurally meaningless or duplicative on an `employment`
  row. This is `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1's own locked narrowing principle,
  preserved unchanged here.
- **`PROBATION`, `SUSPENDED`, `ON_LONG_LEAVE`, `ABSCONDING` as `employment.status` values.** These
  are real `employee.status` states (FR-EMP-014) describing the identity's day-to-day standing
  during an *ongoing* spell — they do not represent the spell itself opening, pausing, or closing.
  An employee on long leave or suspended still has exactly one open `employment` row underneath
  them (`status = ACTIVE`, on either option in §6); the suspension/leave fact belongs on
  `employee.status`, not duplicated onto `employment.status`, matching the "never a copy" principle
  in §3.
- **`REHIRED` as a distinct `employment.status` value.** Not needed — `employment.is_rehire`
  (already a separate documented boolean column, `02_EMPLOYEE_DATA_MODEL.md` §3, locked) already
  carries this fact. A rehired spell is simply `ACTIVE` (or, on Option B, `ACTIVE` with
  `is_rehire=true`) like any other open spell; encoding "this is a rehire" into `status` would
  duplicate `is_rehire` for no documented benefit.
- **A "draft"/"pending"/"not yet started" state for a future-dated joining.** No document describes
  this. FR-EMP-005 ("future-dated changes... activate automatically... via the as-of-date read
  pattern") is written about effective-dated child tables (assignment/compensation), which
  `employment` explicitly is not (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C: "a spell is not
  itself versioned"). Whether an `employment` row created today with a `joining_date` next month
  should read as `ACTIVE` immediately or needs a distinct pre-start value is a real question this
  evidence set does not answer — flagged as an open sub-question in §8, not resolved by inventing a
  value.
- **A "cancelled" state.** No document describes an employment row being created and then voided
  before ever starting — the closest analogous idea (a candidate withdrawing before joining) is
  entirely ATS-scoped and out of V1 (`00_EMPLOYEE_AUDIT.md` §12, locked).

---

## 8. Open Product Decision

**Product approval required before E-03 migration.**

Specifically, product sign-off is needed on:

1. **State-set size**: Option A (`ACTIVE`/`ON_NOTICE`/`TERMINATED`) vs Option B
   (`ACTIVE`/`TERMINATED`, notice-window derived from `last_working_day`) — §6.
2. **Terminal-value name**: `TERMINATED` vs `EXITED` — §5. This document recommends `TERMINATED`
   (distinct from `employee.status`'s `EXITED`) but flags real evidence pointing the other way.
3. **Secondary, not blocking**: whether a future-dated `joining_date` (an `employment` row created
   today for a start date next month) should read as `ACTIVE` from creation, or needs its own
   pre-start value — no document raises or answers this; §7's last item. E-03 can reasonably default
   to "no such state, `ACTIVE` from creation" (matching FR-EMP-002's framing that joining date is
   simply a mandatory field, not itself a state gate) without blocking on new product input, but the
   choice should be stated explicitly in E-03's own audit/report rather than assumed silently.

No code, migration, or schema was changed by this investigation.

---

## 9. Other decisions checked and found NOT to block E-03

Per this task's instruction to identify only genuine blockers and not reopen locked decisions, the
following were checked against the evidence and found either already locked or not load-bearing
for E-03 specifically:

- **Rejoin mechanics, `previous_employment_id`, `is_rehire`, `employee_id`-keyed children,
  `employment.version`, effective-dating pattern, Employee's package boundary, BR-14 deferral,
  full RBAC catalogue, ATS out-of-scope** — all already locked per the task's own list; re-verified
  against `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Parts A/B during this investigation and found
  unchanged and uncontradicted. Not reopened.
- **`exit_type`'s enumeration** (§2) — genuinely undefined, same pattern as `status`, but **not** a
  blocker for E-03 specifically: `01_EMPLOYEE_MODULE_PLAN.md`'s own E-03 description scopes the
  exit-initiation hook to "`employment.status → EXITED` [or `TERMINATED`, per this document] and
  `last_working_day` settable" only — `exit_type` classification belongs to the later, separate
  Exit module (`EXIT.INITIATE_*` permissions, `02_EMPLOYEE_DATA_MODEL.md` §2 table C: "Exit
  module, not Employee directly"). E-03 can leave `exit_type` as a nullable, unenumerated column
  without blocking, exactly as `employment.exit_reason_id` already is. Worth resolving before the
  Exit module is built, not before E-03.
- **Rehire entry-point API shape** — `03_EMPLOYEE_API_PLAN.md` §2.1 explicitly flags this as
  "**proposed but not settled**": `POST /v1/employees/{id}/employments` for creating a new
  `employment` row against an existing identity. This is a genuine open item, but it is an API
  *design* choice (does the rehire path deserve a dedicated route, or reuse `POST /v1/employees`
  with special-case handling), not a *product* decision the way status values are — no business
  rule depends on which shape is chosen. Recommend resolving it during E-03's own implementation
  using standard REST conventions (favoring the dedicated sub-resource route the API plan already
  leans toward), rather than treating it as a pre-implementation blocker requiring product sign-off
  the way this document's own subject (§8) does. Flagged here for completeness, not escalated as a
  blocker.
- **`employment_number`** — `02_EMPLOYEE_DATA_MODEL.md` §2 table C marks this "auto/optional," no
  generation scheme documented (unlike `employee_code`, which E-01 explicitly built a number-series
  allocator for). No document treats this as required for E-03 to start; it can ship as a nullable,
  unpopulated column in this slice without contradicting any requirement, and revisited if a later
  document defines a generation rule.

---

## 10. Status

**E-01**: COMPLETE.

**E-03**: BLOCKED.

### Blocker

`employment.status`'s literal value set requires product approval — specifically the two questions
in §8 (state-set size, terminal-value name). The narrowing *principle* (a small, spell-scoped
subset, never a copy of `employee.status`'s 10-state machine) is already locked and was not
reopened by this investigation.

### Other E-03 blockers

None found that require product approval before starting. Two related-but-non-blocking gaps were
identified and are tracked, not escalated: `exit_type`'s enumeration (defer to the Exit module) and
the rehire entry-point API shape (an engineering decision, resolvable during E-03's own
implementation).

### Recommended status set

`ACTIVE` (unhedged across every source) as the open state; `TERMINATED` (this document's
recommendation, to stay distinct from `employee.status`'s `EXITED` — see §5 for the counter-
evidence) as the closed state; `ON_NOTICE` as an optional third state, with this document's
preference for leaving it out and deriving "on notice" from `last_working_day` instead (§6), since
that is the smaller set that still satisfies every documented requirement.

### Next action

Product decision → approve or revise the recommended `employment.status` set (§5, §6, §8) → then,
and only then, implement E-03. This task did not implement E-03, write a migration, or modify any
application code, per its own instruction.

# Employee UX Plan

Companion to `00_EMPLOYEE_AUDIT.md §14 (Phase 14)`. Design review only — no frontend code. A
complete, existing screen-level spec already governs the Directory
(`docs/design/screens/01_Employee_List_Directory.md`); this document summarizes it, extends the
same design discipline to the screens it doesn't cover (Profile, Add-employee wizard,
Assignment/Compensation history, Rejoin), and states section/tab structure so the 360° profile
does not become a single giant form.

---

## 1. Screen inventory (from `docs/product/24_UIUX_Screen_Inventory_and_Design_System.md §3.3`,
24 screens) mapped to implementation slices in `01_EMPLOYEE_MODULE_PLAN.md`

| Screen | Slice | Design source |
|---|---|---|
| Directory (table + card view) | E-09 | `docs/design/screens/01_Employee_List_Directory.md` — fully specified, use as-is |
| Filters panel | E-09 | same doc §3 |
| Employee 360° (9 tabs) | E-02/E-04/E-06/E-07 | `docs/product/24 §4.1` + §2 below |
| Add employee (4-step wizard) | E-01/E-02 | §3 below |
| Edit employee | E-02 | reuses 360° tab-level edit, not a separate page |
| Transfer / Promotion | E-04 | §4 below |
| Salary revision | E-06 | §4 below |
| Confirmation | E-03 | probation workflow, within Employment tab |
| Document upload / verification queue | E-08 | |
| Bulk import (4 screens) | E-09 | upload → validate → preview → commit |
| Import history | E-09 | |
| Letter generation / templates | E-08 | |
| Org chart | E-04 | reporting-tree visualization |
| Profile change requests | E-02 | employee self-service, HR approval queue |
| Employee export | E-09 | |

---

## 2. The 360° profile — tab structure (not a single giant form)

`docs/product/24_UIUX_Screen_Inventory_and_Design_System.md:174-182` (§4.1) is explicit: the 360°
profile is "the single most-used HR screen," gets a **persistent header** (photo, name, code,
designation, department, manager, status, quick actions) with **tabbed content below**, and
"permission-gated tabs are absent, not disabled-and-visible — showing a locked tab tells the user
something exists that they cannot see, which invites social-engineering requests to HR."

Tabs (FR-EMP-017), each independently permission-gated, each a thin view over one part of the
data model in `02_EMPLOYEE_DATA_MODEL.md`:

| Tab | Shows | Permission | Edit surface |
|---|---|---|---|
| **Profile** | Identity (§A), Contact (§B) | `EMPLOYEE.VIEW` (own scope shows own row regardless) | `EMPLOYEE.UPDATE` for uncontrolled fields; controlled fields (name/DOB/bank/PAN/address, FR-EMP-009) submit a profile-change-request instead of writing directly |
| **Job** | Current + historical Assignment (§D/§E) | `EMPLOYEE.VIEW` | `EMPLOYEE.TRANSFER`/`.PROMOTE` open a dedicated workflow (§4), not an inline field edit — this is an insert-a-new-effective-dated-row operation, not a form save |
| **Compensation** | Current + historical Compensation (§J) | `EMPLOYEE.VIEW_COMPENSATION` — **entire tab absent without it**, per the "absent not disabled" rule | `EMPLOYEE.UPDATE_COMPENSATION` opens the salary-revision workflow (§4) |
| **Attendance** | (out of scope — Attendance module not built) | — | Tab renders a "not yet available" state, or is hidden entirely until Attendance ships — recommend hiding, consistent with "absent, not disabled" applied to *capability*, not just permission |
| **Leave** | (out of scope — Leave module not built) | — | same as Attendance |
| **Documents** | `employee_document` list | `EMPLOYEE.VIEW_DOCUMENTS` | `.UPLOAD_DOCUMENTS` / `.VERIFY_DOCUMENTS` |
| **Assets** | (out of scope — Asset module is V3) | — | hidden until built |
| **Performance** | (out of scope — Performance module is V3) | — | hidden until built |
| **Timeline** | `employee_event` unified feed | `EMPLOYEE.VIEW` | system-generated only, no edit surface |

**Recommendation**: ship Profile, Job, Compensation, Documents, Timeline in Employee's own
slices (E-01–E-08); render Attendance/Leave/Assets/Performance tabs only once those modules
actually exist, rather than shipping empty placeholder tabs — this matches the "absent, not
disabled" principle applied at the module-readiness level, not just the permission level, and
avoids a half-built tab shipping ahead of the module it depends on.

**Statutory/Bank data** (§F/§G in `02_EMPLOYEE_DATA_MODEL.md`) has no obvious tab of its own in
the documented 9-tab list — it is RESTRICTED, Payroll-adjacent data with no confirmed view
permission (§00 audit §11.1/§F gap). **Recommendation**: surface it as a sub-section within
Compensation (same `EMPLOYEE.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION`-adjacent gate) until product
confirms a dedicated permission — flagged as a UX decision pending the same product answer
`00_EMPLOYEE_AUDIT.md §15.9`/`02_EMPLOYEE_DATA_MODEL.md §2 section F` already flags.

**Quick actions** in the persistent header (from the screen inventory doc): Apply leave on behalf,
Mark attendance, Generate letter, Initiate transfer, Initiate exit, View audit trail — the first
two are hidden until Attendance/Leave exist; the rest are in Employee's own scope.

---

## 3. Add-employee wizard (4 steps, FR-EMP-002's mandatory-field set drives step 1)

No existing screen spec covers this in the same depth as the Directory doc — proposed structure,
following the same design discipline (permission-gated, empty/error states, no ATS coupling per
`00_EMPLOYEE_AUDIT.md §6`):

1. **Identity & contact** — mandatory: first name, DOB not required (only joining date is,
   FR-EMP-002); optional fields shown with a profile-completeness indicator, not forced.
2. **Employment & organisation** — mandatory: joining date, legal entity, branch, department,
   designation, employment type, reporting manager (nullable, explicitly allowed for a CEO-level
   hire per FR-EMP-002).
3. **Compensation** (permission-gated — step is skipped entirely, not shown-disabled, for a
   creator without `EMPLOYEE.UPDATE_COMPENSATION`) — CTC entry, salary structure selection.
4. **Review & confirm** — summary of all three prior steps, `employee_code` shown as
   system-allocated (not editable), submit creates `employee` + `employment` + first
   `employee_assignment` + first `employee_compensation` row in one transaction.

**No ATS/candidate step** — this wizard is the entire V1 creation path alongside bulk import
(`00_EMPLOYEE_AUDIT.md §6`). **Recommendation**: do not build a "convert from candidate" entry
point; a V2 ATS build can add that as a new wizard variant without touching this one.

---

## 4. Transfer / Promotion / Salary revision — workflow screens, not inline edits

Because these are all effective-dated inserts (`02_EMPLOYEE_DATA_MODEL.md §1.2`), the UX pattern
differs from a plain PATCH-and-save form used everywhere else in the organisation module's
frontend (Branch/Department/Designation/Grade's own inline-edit pattern):

- **Effective date picker** is mandatory on every one of these screens — the user is explicitly
  choosing when the new row starts, not just what its values are.
- **"What changes" preview before submit** — show old value → new value per field, plus the
  computed `effective_to` that will be written onto the row being closed. This mirrors the Bulk
  field update pattern already specified for the Directory's own bulk-action bar
  (`docs/design/screens/01_Employee_List_Directory.md §5`: "Plain-English summary of what changes,
  per-record, before applying").
- **Backdating** into a locked payroll period should surface the `PAYROLL.BACKDATE_OVERRIDE`
  gate visibly (disabled submit + explanation) rather than a raw 403/422 after the fact — this
  can only be built once Payroll's lock-period check exists (`02_EMPLOYEE_DATA_MODEL.md §1.4`);
  until then, the screen should simply not attempt to enforce it client-side.
- **History view** (Job tab, Compensation tab) is a read-only timeline of past effective-dated
  rows, each showing its `effective_from`/`effective_to` range and `change_reason` — this is the
  UI surface for "what was true on date X," satisfying the worked example in the brief (2027 vs
  2029 assignment).

---

## 5. Rejoin — UX implication of `00_EMPLOYEE_AUDIT.md §3`

FR-EMP-015's "warn and offer to link" workflow implies a specific UX moment: during the
add-employee wizard's step 1 (§3 above), a match against an existing (exited) employee's PAN/
Aadhaar/email should surface a non-blocking warning with a "Link to existing record" action that,
if taken, switches the wizard from "create new employee" to "create new employment for
`EMP-000123`" — skipping identity re-entry (name/DOB already exist) and going straight to step 2
(new employment/assignment/compensation). **This UX is only buildable once the underlying rejoin
data-model decision (`00_EMPLOYEE_AUDIT.md §15.1`) is confirmed** — flagged as dependent, not
designed further here.

---

## 6. Accessibility, empty/error states, permission-gating

All of §8–§11 of `docs/design/screens/01_Employee_List_Directory.md` (three distinct empty
states, error-state table, WCAG 2.1 AA floor, "absent not disabled" action-gating, masked-not-null
field rendering) apply identically to every other Employee screen in this plan — restated here by
reference, not duplicated, to avoid the two documents drifting out of sync.

---

## 7. What's deferred

Matches `docs/design/screens/01_Employee_List_Directory.md §12` (saved filter views, multi-column
sort, org-chart-integrated Directory browsing) plus, specific to the screens this document adds:
Attendance/Leave/Assets/Performance tab content (§2 — hidden until those modules exist), the
rejoin-linking wizard variant (§5 — pending the data-model decision), and any visual design pass
(this document, like the Directory spec, is layout/behavior only — visual design against
`docs/design/01_Design_System.md` tokens is a downstream step).

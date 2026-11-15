# Performance Management module docs

**Status:** Phase 0. Every architecture decision is approved, and **no code has been written yet**. The gate document still needs signing (gate §15).

## Read in this order

| # | Document | What it is |
|---|---|---|
| 1 | [`PERFORMANCE_ARCHITECTURE_GATE.md`](PERFORMANCE_ARCHITECTURE_GATE.md) | **The binding plan.** Approved decisions, invariants, existing bugs (B1–B11), remediation work (R1–R9), data model, access matrix, state machines, notifications, feature flags, migrations and merge gates, rollback, phase entry and exit criteria, policy register (P1–P47), sign-off. |
| 2 | [`01_PHASE0_DECISION_LOG.md`](01_PHASE0_DECISION_LOG.md) | Why each of the seven decisions (P34, P35, P19, P9, P15, P21, P25) came out as it did: the code checked, options compared, refinements. |
| 3 | [`00_AUDIT_AND_BLUEPRINT.md`](00_AUDIT_AND_BLUEPRINT.md) | The original audit of the HRMS and the full product blueprint (23 sections). Superseded points are marked. |

If documents disagree, the gate wins.

## Where to start next

1. **Sign the gate** (§15), and sign off the register items marked "by Ph1" in gate §14:
   - P1–P3, P5, P7 (goals and scale);
   - P36 (branch manager access);
   - P40 (turning the module on);
   - P41 (team entity);
   - P43 (mobile scope).
2. **Build the Phase 1 prerequisites**, each as its own PR (gate §5):
   - **R1:** derived reporting-manager rights in `core.rbac` (P34). Changes shipped leave, regularization and overtime behaviour; needs a release note.
   - **R2:** `DEPARTMENT` scope plus the derived `DEPARTMENT_HEAD` role (P35). Has a migration, so it needs **your manual merge**.
   - **R3:** confirm suspected bug B3 and apply INV-1 (current = assignment covering today).
   - **R4:** department-head validation and cleanup report.
   - **R8:** feature-flag wiring.
3. **Then Phase 1:** goals, KPIs, configuration, and the access layer (gate §13).

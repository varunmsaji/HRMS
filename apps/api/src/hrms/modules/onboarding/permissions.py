"""Permission codes owned by the onboarding module.

`docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` §7.1 names a 5-code `ONBOARDING.*`
catalogue, following the `EMPLOYEE.*` catalogue's own naming precedent
(`hrms.modules.employee.permissions`). `.ACTIVATE` is kept separate from `.REVIEW` deliberately —
activation is irreversible (it creates the real `Employee`/`Employment`/`Assignment` rows) and
mirrors why `EMPLOYEE.TERMINATE` got its own code rather than folding into `.UPDATE`.

O1 only wires `.CREATE`/`.VIEW` into the router (case create/list/detail) — `.REVIEW`/
`.ACTIVATE`/`.CANCEL` are seeded and granted here now (same as the migration creating all four
tables up front, module docstring) so later phases (O6/O7) add routes only, no further seed/grant
plumbing."""

ONBOARDING_CREATE = "ONBOARDING.CREATE"
ONBOARDING_VIEW = "ONBOARDING.VIEW"
ONBOARDING_REVIEW = "ONBOARDING.REVIEW"
ONBOARDING_ACTIVATE = "ONBOARDING.ACTIVATE"
ONBOARDING_CANCEL = "ONBOARDING.CANCEL"

ONBOARDING_PERMISSIONS = [
    (ONBOARDING_CREATE, "ONBOARDING", "Start onboarding for a new hire"),
    (ONBOARDING_VIEW, "ONBOARDING", "View onboarding cases"),
    (ONBOARDING_REVIEW, "ONBOARDING", "Verify or reject an onboarding case's sections/documents"),
    (ONBOARDING_ACTIVATE, "ONBOARDING", "Activate a verified onboarding case into a real employee"),
    (ONBOARDING_CANCEL, "ONBOARDING", "Cancel an onboarding case"),
]

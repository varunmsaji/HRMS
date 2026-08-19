"""Permission codes owned by the organisation module."""

ORG_COMPANY_MANAGE = "ORG.COMPANY.MANAGE"
DASHBOARD_COMPANY_VIEW = "DASHBOARD.COMPANY.VIEW"

# Sprint 3A (docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md, Feature 2.6) is treated as
# authoritative for this code over docs/product/19_RBAC_and_Permission_Matrix.md §3.6, which
# names the same resource `ORG.ENTITY.MANAGE` — the sprint doc is the more recent,
# module-scoped, implementation-precise source (5 occurrences vs. 1 abbreviated summary
# table entry). Single permission gates both viewing and managing legal entities, matching
# the existing Company precedent (ORG_COMPANY_MANAGE) rather than inventing a view/manage
# split with no doc precedent.
ORG_LEGAL_ENTITY_MANAGE = "ORG.LEGAL_ENTITY.MANAGE"

# docs/product/19_RBAC_and_Permission_Matrix.md:100 names this exact code (`.BRANCH.MANAGE`)
# with no naming conflict — unlike Legal Entity, no doc reconciliation is needed here.
# Single permission gates both viewing and managing branches, matching the Company/Legal
# Entity precedent rather than inventing a view/manage split with no doc precedent.
ORG_BRANCH_MANAGE = "ORG.BRANCH.MANAGE"

# docs/product/19_RBAC_and_Permission_Matrix.md:100 names this exact code with no naming
# conflict. Single permission gates both viewing and managing departments, matching the
# Company/Legal Entity/Branch precedent rather than inventing a view/manage split.
ORG_DEPARTMENT_MANAGE = "ORG.DEPARTMENT.MANAGE"

# docs/product/19_RBAC_and_Permission_Matrix.md:100 and
# docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1412 both name this exact code with no naming
# conflict. Single permission gates both viewing and managing designations, matching the
# Company/Legal Entity/Branch/Department precedent rather than inventing a view/manage split.
ORG_DESIGNATION_MANAGE = "ORG.DESIGNATION.MANAGE"

# docs/product/19_RBAC_and_Permission_Matrix.md:100 names this exact code with no naming
# conflict. Single permission gates both viewing and managing grades, matching the
# Company/Legal Entity/Branch/Department/Designation precedent rather than inventing a
# view/manage split. Setting `grade_id` on a Designation continues to require only
# ORG.DESIGNATION.MANAGE, not this permission — same posture as Designation's own
# `department_id` field requiring only ORG.DESIGNATION.MANAGE, not ORG.DEPARTMENT.MANAGE.
ORG_GRADE_MANAGE = "ORG.GRADE.MANAGE"

# docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1416 defines and uses this exact code in the
# ORG domain (matching where `shift` actually lives — the `organisation` module owns it as
# org-setup config this slice). docs/product/19_RBAC_and_Permission_Matrix.md:56-58 instead
# places shift management under `ATTENDANCE.SHIFT_MANAGE` — resolved the same way this
# series already resolved the Legal Entity naming conflict: the Sprint doc is the more
# recent, module-scoped, implementation-precise source. See
# docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §7.
ORG_SHIFT_MANAGE = "ORG.SHIFT.MANAGE"

# docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §23.2 and WD-19 name both of these
# codes verbatim. `ORG_CALENDAR_MANAGE` gates WorkCalendar, WeeklyOffPattern,
# CalendarException, and PolicyAssignment (all "the composition/assignment layer");
# `ORG_HOLIDAY_MANAGE` gates HolidayCalendar and Holiday (the reusable dated-fact catalogue).
# Single permission gates both viewing and managing each, matching the existing
# Company/LegalEntity/Branch/.../Shift precedent — no view/manage split.
ORG_CALENDAR_MANAGE = "ORG.CALENDAR.MANAGE"
ORG_HOLIDAY_MANAGE = "ORG.HOLIDAY.MANAGE"

ORGANISATION_PERMISSIONS = [
    (ORG_COMPANY_MANAGE, "ORG", "Manage company settings"),
    (DASHBOARD_COMPANY_VIEW, "DASHBOARD", "View company dashboard"),
    (ORG_LEGAL_ENTITY_MANAGE, "ORG", "Manage legal entities"),
    (ORG_BRANCH_MANAGE, "ORG", "Manage branches"),
    (ORG_DEPARTMENT_MANAGE, "ORG", "Manage departments"),
    (ORG_DESIGNATION_MANAGE, "ORG", "Manage designations"),
    (ORG_GRADE_MANAGE, "ORG", "Manage grades"),
    (ORG_SHIFT_MANAGE, "ORG", "Manage shifts"),
    (
        ORG_CALENDAR_MANAGE,
        "ORG",
        "Manage workforce calendars, weekly-off patterns, and calendar assignments",
    ),
    (ORG_HOLIDAY_MANAGE, "ORG", "Manage holiday calendars and holidays"),
]

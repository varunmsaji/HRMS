"""Permission codes owned by the attendance module (WD-19).

Config screens are COMPANY-scoped, matching Organisation's `.MANAGE` convention — Attendance
policy definitions are administered by HR/Company Admin, never self-service (architecture §23.2:
"Employee self-service never manages policies").

W4 adds the *operational* codes (architecture §23.2 table) — `ATTENDANCE.VIEW` follows Employee's
resource/action + data-scope style (`EMPLOYEE.VIEW`, not `VIEW_OWN`/`VIEW_TEAM`), granted to
`COMPANY_ADMIN` at COMPANY scope at registration like every other code here
(`organisation.service.register_company`, which iterates this list generically — no per-code
wiring needed there). SELF/REPORTEES/REPORTEE_TREE grants for other roles are a role-authoring
concern (`role_permission.data_scope`, `RBAC_DATA_SCOPE_DECISIONS.md` Decision A), exercised in
this slice's security tests exactly as `EMPLOYEE.VIEW`'s scoping already is — W4 does not ship a
new default "Manager"/"Employee" role, mirroring the Employee module's own posture."""

ATTENDANCE_POLICY_MANAGE = "ATTENDANCE.POLICY_MANAGE"
ATTENDANCE_VIEW = "ATTENDANCE.VIEW"
ATTENDANCE_VIEW_ALL = "ATTENDANCE.VIEW_ALL"
ATTENDANCE_PUNCH = "ATTENDANCE.PUNCH"
ATTENDANCE_PUNCH_ON_BEHALF = "ATTENDANCE.PUNCH_ON_BEHALF"
ATTENDANCE_RECOMPUTE = "ATTENDANCE.RECOMPUTE"
ATTENDANCE_ROSTER_MANAGE = "ATTENDANCE.ROSTER_MANAGE"

# W6 (WD-28 decision 6) — regularization workflow. Reads reuse `ATTENDANCE_VIEW` (no fourth
# code), mirroring WD-27's "roster viewing reuses ATTENDANCE.VIEW". Spelling kept as
# "REGULARIZATION" (codebase convention: `RegularizationPolicy`/`regularization_policy`),
# not architecture §23.2's one inconsistent "REGULARISE" instance.
ATTENDANCE_REGULARIZATION_REQUEST = "ATTENDANCE.REGULARIZATION_REQUEST"
ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF = "ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF"
ATTENDANCE_REGULARIZATION_APPROVE = "ATTENDANCE.REGULARIZATION_APPROVE"

ATTENDANCE_PERMISSIONS = [
    (
        ATTENDANCE_POLICY_MANAGE,
        "ATTENDANCE",
        "Manage attendance, overtime, and regularization policies and their assignments",
    ),
    (ATTENDANCE_VIEW, "ATTENDANCE", "View attendance days and punches within scope"),
    (ATTENDANCE_VIEW_ALL, "ATTENDANCE", "View attendance company-wide, ignoring reporting tree"),
    (ATTENDANCE_PUNCH, "ATTENDANCE", "Record own punches"),
    (ATTENDANCE_PUNCH_ON_BEHALF, "ATTENDANCE", "Record punches on behalf of other employees"),
    (ATTENDANCE_RECOMPUTE, "ATTENDANCE", "Trigger a privileged recompute of an attendance day"),
    (
        ATTENDANCE_ROSTER_MANAGE,
        "ATTENDANCE",
        "Create, update, publish, and delete shift roster entries",
    ),
    (
        ATTENDANCE_REGULARIZATION_REQUEST,
        "ATTENDANCE",
        "Submit a regularization request for own attendance",
    ),
    (
        ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF,
        "ATTENDANCE",
        "Submit a regularization request on behalf of another employee",
    ),
    (
        ATTENDANCE_REGULARIZATION_APPROVE,
        "ATTENDANCE",
        "Approve or reject regularization requests",
    ),
]

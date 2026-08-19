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
]

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

# W7 (WD-29 decision 6) — overtime approval workflow. Reads reuse `ATTENDANCE_VIEW`/
# `ATTENDANCE_VIEW_ALL` (no fourth code) — OT records are system-detected and attached to
# attendance days the caller can already view, not self-submitted content needing its own view
# gate, mirroring WD-28 decision 6's identical reasoning for regularization reads.
ATTENDANCE_OVERTIME_APPROVE = "ATTENDANCE.OVERTIME_APPROVE"

# W8 (decision log WD-30) — period finalization/locking. Architecture §23.2 names exactly these
# two codes (`ATTENDANCE.LOCK` / `.UNLOCK`), both COMPANY-scoped — a period has no `employee_id`
# to resolve a narrower DataScope against, mirroring `ATTENDANCE_POLICY_MANAGE`'s static-gate
# posture. `LOCK` covers the whole create/validate/finalize surface (all preparatory steps toward
# the same COMPANY-scoped administrative action per architecture); `UNLOCK` is deliberately
# separate since reopening a locked period is a materially higher-risk action than closing one.
# Reads (list/get/validate-status/summary) reuse `ATTENDANCE_VIEW`/`ATTENDANCE_VIEW_ALL` — no
# third read code, mirroring WD-28 decision 6 / WD-29 decision 6's identical reasoning.
ATTENDANCE_LOCK = "ATTENDANCE.LOCK"
ATTENDANCE_UNLOCK = "ATTENDANCE.UNLOCK"

# W9 (architecture §21/§25, decision log WD-31) — the Leave -> Attendance projection adapter.
# COMPANY-scoped, mirroring `ATTENDANCE_LOCK`'s static-gate posture: this is a narrow internal
# integration seam a future Leave module (or, until then, an authorized internal/test caller)
# uses to publish/cancel approved leave projections, not a self-service employee action. Reads
# reuse `ATTENDANCE_VIEW`/`ATTENDANCE_VIEW_ALL` — no third code, mirroring every other read-reuse
# precedent in this file (WD-28 decision 6 / WD-29 decision 6 / WD-30's identical reasoning).
ATTENDANCE_LEAVE_PROJECTION_SYNC = "ATTENDANCE.LEAVE_PROJECTION_SYNC"

# Face attendance — enrolling someone's biometric profile is a materially higher-risk act than
# punching, so it gets its own code rather than riding on `PUNCH_ON_BEHALF`. Data-scoped like
# `PUNCH_ON_BEHALF`: the target employee must be inside the caller's scope.
ATTENDANCE_FACE_ENROLLMENT_MANAGE = "ATTENDANCE.FACE_ENROLLMENT_MANAGE"

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
    (
        ATTENDANCE_OVERTIME_APPROVE,
        "ATTENDANCE",
        "Approve or reject system-detected overtime",
    ),
    (
        ATTENDANCE_LOCK,
        "ATTENDANCE",
        "Create, validate, and finalize/close attendance periods",
    ),
    (
        ATTENDANCE_UNLOCK,
        "ATTENDANCE",
        "Reopen a closed/locked attendance period",
    ),
    (
        ATTENDANCE_LEAVE_PROJECTION_SYNC,
        "ATTENDANCE",
        "Publish or cancel an approved leave projection (Leave -> Attendance adapter)",
    ),
    (
        ATTENDANCE_FACE_ENROLLMENT_MANAGE,
        "ATTENDANCE",
        "Enroll, add reference photos for, and revoke employee face profiles",
    ),
]

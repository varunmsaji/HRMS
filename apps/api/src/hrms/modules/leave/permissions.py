"""Permission codes owned by the Leave module (LEAVE_DECISION_LOG.md LD-08).

Same two-part, underscore-joined convention Attendance actually ships (not
`02_Module_Standard.md`'s illustrative three-part dotted example). Config screens
(`LEAVE.POLICY_MANAGE`, `LEAVE.TYPE_MANAGE`) are COMPANY-scoped, matching every other policy
module's `.MANAGE` convention. `LEAVE.BALANCE_VIEW`/`LEAVE.BALANCE_VIEW_ALL` are seeded now
(L1) even though nothing reads balances yet (L2) — reads reuse a `.VIEW`-style code rather than
adding one later, matching the repeated convention already stated in Attendance's own
`permissions.py` (WD-28/29/30/31 decision 6/6/7/9)."""

LEAVE_TYPE_MANAGE = "LEAVE.TYPE_MANAGE"
LEAVE_POLICY_MANAGE = "LEAVE.POLICY_MANAGE"
LEAVE_BALANCE_VIEW = "LEAVE.BALANCE_VIEW"
LEAVE_BALANCE_VIEW_ALL = "LEAVE.BALANCE_VIEW_ALL"
LEAVE_BALANCE_ADJUST = "LEAVE.BALANCE_ADJUST"

# L4 (not yet built, seeded here in the identity table so future migrations don't need a fresh
# INSERT ... WHERE NOT EXISTS pattern the way EMPLOYEE.VIEW_STATUTORY's own history required —
# see employee/permissions.py's note on that).
LEAVE_APPLICATION_SUBMIT = "LEAVE.APPLICATION_SUBMIT"
LEAVE_APPLICATION_SUBMIT_ON_BEHALF = "LEAVE.APPLICATION_SUBMIT_ON_BEHALF"
LEAVE_APPLICATION_APPROVE = "LEAVE.APPLICATION_APPROVE"

# L5.5 — client spec §7 (LEAVE_DECISION_LOG.md LD-16). COMPANY-scoped config, same `.MANAGE`
# convention as LEAVE_TYPE_MANAGE/LEAVE_POLICY_MANAGE above.
LEAVE_COMBINATION_RULE_MANAGE = "LEAVE.COMBINATION_RULE_MANAGE"

# Client spec §10 (LEAVE_DECISION_LOG.md LD-20). COMPANY-scoped config, same `.MANAGE`
# convention.
LEAVE_YEAR_SETTING_MANAGE = "LEAVE.YEAR_SETTING_MANAGE"

# Client spec §16 (LEAVE_DECISION_LOG.md LD-22). COMPANY-scoped config, same `.MANAGE`
# convention — HR/compliance enters statutory minimums, distinct from `.POLICY_MANAGE` since a
# policy author may not be the person authorized to set legal floors.
LEAVE_STATUTORY_MINIMUM_MANAGE = "LEAVE.STATUTORY_MINIMUM_MANAGE"

LEAVE_PERMISSIONS: list[tuple[str, str, str]] = [
    (LEAVE_TYPE_MANAGE, "LEAVE", "Manage leave types"),
    (LEAVE_POLICY_MANAGE, "LEAVE", "Manage leave policies and policy versions"),
    (LEAVE_BALANCE_VIEW, "LEAVE", "View own leave balance"),
    (LEAVE_BALANCE_VIEW_ALL, "LEAVE", "View leave balances within scope"),
    (LEAVE_BALANCE_ADJUST, "LEAVE", "Manually adjust a leave balance (ledger entry)"),
    (LEAVE_APPLICATION_SUBMIT, "LEAVE", "Submit a leave application"),
    (
        LEAVE_APPLICATION_SUBMIT_ON_BEHALF,
        "LEAVE",
        "Submit a leave application on behalf of another employee",
    ),
    (LEAVE_APPLICATION_APPROVE, "LEAVE", "Approve or reject a leave application"),
    (LEAVE_COMBINATION_RULE_MANAGE, "LEAVE", "Manage leave combination (exclusivity) rules"),
    (LEAVE_YEAR_SETTING_MANAGE, "LEAVE", "Manage the company's leave year configuration"),
    (LEAVE_STATUTORY_MINIMUM_MANAGE, "LEAVE", "Manage statutory leave minimums (compliance)"),
]

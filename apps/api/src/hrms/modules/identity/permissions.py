"""Permission codes owned by the identity / settings domain (B1 subset)."""

SETTINGS_USER_MANAGE = "SETTINGS.USER.MANAGE"
SETTINGS_ROLE_MANAGE = "SETTINGS.ROLE.MANAGE"
EMPLOYEE_VIEW = "EMPLOYEE.VIEW"

B1_PERMISSIONS = [
    (SETTINGS_USER_MANAGE, "SETTINGS", "Manage users"),
    (SETTINGS_ROLE_MANAGE, "SETTINGS", "Manage roles"),
    (EMPLOYEE_VIEW, "EMPLOYEE", "View employees within scope"),
]

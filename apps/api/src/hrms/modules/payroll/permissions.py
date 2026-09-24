"""Permission codes owned by the Payroll module.

Phase 5.1: one COMPANY-scoped setup code for components, structures and employee salary
assignment. Reading an employee's salary breakup reuses `EMPLOYEE.VIEW_COMPENSATION` with its
`DataScope` — a salary breakup is compensation data, and a second view permission would let the
two drift apart."""

PAYROLL_SETUP_MANAGE = "PAYROLL.SETUP_MANAGE"

PAYROLL_PERMISSIONS: list[tuple[str, str, str]] = [
    (
        PAYROLL_SETUP_MANAGE,
        "PAYROLL",
        "Manage salary components, salary structures and employee salary assignments",
    ),
]

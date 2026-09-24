"""Permission codes owned by the Payroll module.

Phase 5.1: one COMPANY-scoped setup code for components, structures and employee salary
assignment. Reading an employee's salary breakup reuses `EMPLOYEE.VIEW_COMPENSATION` with its
`DataScope` — a salary breakup is compensation data, and a second view permission would let the
two drift apart.

Phase 5.2: pay runs. `RUN_PROCESS` prepares a run (create, lock inputs, compute, acknowledge
variances, roll back); `RUN_APPROVE` approves, finalises and marks it paid. D9 — maker ≠ checker:
the user who last computed a run can never approve it, whatever permissions they hold.

Phase 5.3: `STATUTORY_MANAGE` edits the statutory rate master and records compliance sign-off
(verification) of each rate.

Phase 5.4: `PAYSLIP_VIEW_OWN` (the EMPLOYEE role, SELF) reads one's own finalised payslips;
`BANK_ADVICE_DOWNLOAD` (COMPANY_ADMIN only) downloads the bank file, which carries full account
numbers."""

PAYROLL_SETUP_MANAGE = "PAYROLL.SETUP_MANAGE"
PAYROLL_RUN_VIEW = "PAYROLL.RUN_VIEW"
PAYROLL_RUN_PROCESS = "PAYROLL.RUN_PROCESS"
PAYROLL_RUN_APPROVE = "PAYROLL.RUN_APPROVE"
PAYROLL_STATUTORY_MANAGE = "PAYROLL.STATUTORY_MANAGE"
PAYROLL_PAYSLIP_VIEW_OWN = "PAYROLL.PAYSLIP_VIEW_OWN"
PAYROLL_BANK_ADVICE_DOWNLOAD = "PAYROLL.BANK_ADVICE_DOWNLOAD"

PAYROLL_PERMISSIONS: list[tuple[str, str, str]] = [
    (
        PAYROLL_SETUP_MANAGE,
        "PAYROLL",
        "Manage salary components, salary structures and employee salary assignments",
    ),
    (PAYROLL_RUN_VIEW, "PAYROLL", "View pay runs and their employee pay"),
    (
        PAYROLL_RUN_PROCESS,
        "PAYROLL",
        "Create pay runs, lock inputs, compute, acknowledge variances and roll back",
    ),
    (PAYROLL_RUN_APPROVE, "PAYROLL", "Approve, finalise and mark pay runs paid"),
    (
        PAYROLL_STATUTORY_MANAGE,
        "PAYROLL",
        "Manage and verify statutory rates (PF, ESI, professional tax, LWF)",
    ),
    (PAYROLL_PAYSLIP_VIEW_OWN, "PAYROLL", "View one's own payslips from finalised pay runs"),
    (
        PAYROLL_BANK_ADVICE_DOWNLOAD,
        "PAYROLL",
        "Download a finalised pay run's bank advice (full account numbers)",
    ),
]

#: Granted to HR_ADMIN at COMPANY scope; COMPANY_ADMIN holds every `PAYROLL.*` code.
PAYROLL_HR_ADMIN_PERMISSIONS = (
    PAYROLL_SETUP_MANAGE,
    PAYROLL_RUN_VIEW,
    PAYROLL_RUN_PROCESS,
    PAYROLL_STATUTORY_MANAGE,
)

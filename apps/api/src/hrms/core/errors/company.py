"""Errors for a company whose lifecycle status (set by a platform admin) limits what its users
can do. 403: the caller is authenticated, the *company's state* forbids the action. The `code`
tells a client which screen to show; none of them is retryable until the status changes."""

from hrms.core.errors.base import AppError


class CompanyAccessError(AppError):
    status_code = 403


class CompanyPendingApprovalError(CompanyAccessError):
    code = "COMPANY_PENDING_APPROVAL"

    def __init__(self) -> None:
        super().__init__(
            "Your company is awaiting approval. You can look around, but changes are disabled "
            "until it is approved."
        )


class CompanySuspendedError(CompanyAccessError):
    code = "COMPANY_SUSPENDED"

    def __init__(self) -> None:
        super().__init__(
            "This company is suspended and is read-only. Contact support to restore access."
        )


class CompanyRejectedError(CompanyAccessError):
    code = "COMPANY_REJECTED"

    def __init__(self) -> None:
        super().__init__("This company registration was not approved. Contact support.")


class CompanyTerminatedError(CompanyAccessError):
    code = "COMPANY_TERMINATED"

    def __init__(self) -> None:
        super().__init__("This company account has been closed. Contact support.")

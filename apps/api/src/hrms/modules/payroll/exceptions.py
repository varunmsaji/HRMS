"""Module-specific AppError subclasses for the Payroll module."""

from typing import Any

from hrms.core.errors.base import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)


def _detail(field: str, code: str, message: str) -> list[dict[str, Any]]:
    return [{"field": field, "code": code, "message": message}]


class SalaryComponentNotFoundError(NotFoundError):
    code = "SALARY_COMPONENT_NOT_FOUND"

    def __init__(self, message: str = "Salary component not found") -> None:
        super().__init__(message)


class SalaryComponentCodeAlreadyExistsError(ConflictError):
    code = "SALARY_COMPONENT_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A salary component with this code already exists") -> None:
        super().__init__(message, details=_detail("code", self.code, message))


class SalaryComponentSystemFieldError(ValidationError):
    """A system component's type is fixed — the breakup and pay-run rules depend on it."""

    code = "SALARY_COMPONENT_SYSTEM_FIELD"

    def __init__(self, message: str = "A system component's type cannot be changed") -> None:
        super().__init__(message, details=_detail("component_type", self.code, message))


class SalaryStructureNotFoundError(NotFoundError):
    code = "SALARY_STRUCTURE_NOT_FOUND"

    def __init__(self, message: str = "Salary structure not found") -> None:
        super().__init__(message)


class SalaryStructureCodeAlreadyExistsError(ConflictError):
    code = "SALARY_STRUCTURE_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A salary structure with this code already exists") -> None:
        super().__init__(message, details=_detail("code", self.code, message))


class SalaryStructureVersionNotFoundError(NotFoundError):
    code = "SALARY_STRUCTURE_VERSION_NOT_FOUND"

    def __init__(self, message: str = "Salary structure version not found") -> None:
        super().__init__(message)


class SalaryStructureDraftExistsError(ConflictError):
    code = "SALARY_STRUCTURE_DRAFT_EXISTS"

    def __init__(self, message: str = "This salary structure already has a draft version") -> None:
        super().__init__(message, details=_detail("salary_structure_id", self.code, message))


class SalaryStructureVersionNotDraftError(ConflictError):
    code = "SALARY_STRUCTURE_VERSION_NOT_DRAFT"

    def __init__(self, message: str = "Only a draft version can be changed") -> None:
        super().__init__(message, details=_detail("status", self.code, message))


class SalaryStructureInvalidError(ValidationError):
    """The structure's lines cannot produce a valid breakup (`breakup.BreakupError`)."""

    code = "SALARY_STRUCTURE_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(message, details=_detail("lines", self.code, message))


class SalaryStructureEffectiveFromError(ValidationError):
    code = "SALARY_STRUCTURE_EFFECTIVE_FROM"

    def __init__(
        self,
        message: str = "effective_from must be after the current published version's start",
    ) -> None:
        super().__init__(message, details=_detail("effective_from", self.code, message))


class EmployeeSalaryInvalidError(ValidationError):
    code = "EMPLOYEE_SALARY_INVALID"

    def __init__(self, message: str, *, field: str = "effective_from") -> None:
        super().__init__(message, details=_detail(field, self.code, message))


class SalaryBreakupUnavailableError(ValidationError):
    """No breakup can be produced for the employee on that date — no salary assignment, no CTC,
    or no published structure version covering it."""

    code = "SALARY_BREAKUP_UNAVAILABLE"

    def __init__(self, message: str) -> None:
        super().__init__(message, details=_detail("as_of", self.code, message))


class StalePayrollResourceError(ConflictError):
    code = "STALE_RESOURCE"

    def __init__(self, message: str, *, current: dict[str, Any]) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "version",
                    "code": "STALE_RESOURCE",
                    "message": message,
                    "context": {"current": current},
                }
            ],
        )


# ---------------------------------------------------------------------------
# Phase 5.2 — pay runs
# ---------------------------------------------------------------------------


class PayRunNotFoundError(NotFoundError):
    code = "PAY_RUN_NOT_FOUND"

    def __init__(self, message: str = "Pay run not found") -> None:
        super().__init__(message)


class PayRunEmployeeNotFoundError(NotFoundError):
    code = "PAY_RUN_EMPLOYEE_NOT_FOUND"

    def __init__(self, message: str = "This employee is not in the pay run") -> None:
        super().__init__(message)


class PayRunAlreadyExistsError(ConflictError):
    """Decision 14/18 — one pay run per legal entity per calendar month."""

    code = "PAY_RUN_ALREADY_EXISTS"

    def __init__(
        self, message: str = "A pay run for this legal entity and month already exists"
    ) -> None:
        super().__init__(message, details=_detail("month", self.code, message))


class PayRunLegalEntityInvalidError(ValidationError):
    code = "PAY_RUN_LEGAL_ENTITY_INVALID"

    def __init__(self, message: str = "Legal entity not found or inactive") -> None:
        super().__init__(message, details=_detail("legal_entity_id", self.code, message))


class PayRunInvalidTransitionError(ConflictError):
    code = "PAY_RUN_INVALID_TRANSITION"

    def __init__(self, message: str) -> None:
        super().__init__(message, details=_detail("status", self.code, message))


class PayRunInputsUnavailableError(ConflictError):
    """PD-2 — the legal entity's attendance period for the month is missing or not `CLOSED`."""

    code = "PAY_RUN_ATTENDANCE_NOT_CLOSED"

    def __init__(
        self,
        message: str = (
            "The legal entity's attendance period for this month does not exist or is not "
            "closed — close it before locking the pay run's inputs"
        ),
    ) -> None:
        super().__init__(message, details=_detail("attendance_period_id", self.code, message))


class PayRunAttendanceChangedError(ConflictError):
    """The attendance period was reopened after the inputs were locked — the snapshot may be
    stale."""

    code = "PAY_RUN_ATTENDANCE_CHANGED"

    def __init__(
        self,
        message: str = (
            "The attendance period was reopened after this run's inputs were locked — roll the "
            "run back to draft and lock its inputs again"
        ),
    ) -> None:
        super().__init__(message, details=_detail("attendance_period_id", self.code, message))


class PayRunBlockedError(ConflictError):
    """Approval refused: employees with errors, or variances not yet acknowledged."""

    code = "PAY_RUN_BLOCKED"

    def __init__(self, message: str, *, reasons: list[dict[str, Any]]) -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": self.code, "message": message,
                      "context": {"reasons": reasons}}],
        )  # fmt: skip


class PayRunMakerCheckerError(PermissionDeniedError):
    """D9 — the user who computed a run cannot approve it."""

    code = "PAY_RUN_MAKER_CHECKER"

    def __init__(
        self, message: str = "The user who computed this pay run cannot approve it"
    ) -> None:
        super().__init__(message)

"""Module-specific AppError subclasses for the Payroll module."""

from typing import Any

from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError


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

"""Module-specific AppError subclasses for the organisation module."""

from typing import Any

from hrms.core.errors.base import ConflictError, LockedError, ValidationError


class CurrencyLockedError(ValidationError):
    code = "CURRENCY_LOCKED"

    def __init__(self, message: str = "Currency cannot be changed after trial") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "currency",
                    "code": "CURRENCY_LOCKED",
                    "message": message,
                }
            ],
        )


class InvalidWorkingDaysError(ValidationError):
    code = "INVALID_WORKING_DAYS"

    def __init__(self, message: str = "At least one working day is required") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "working_days",
                    "code": "INVALID_WORKING_DAYS",
                    "message": message,
                }
            ],
        )


class CompanyWriteBlockedError(LockedError):
    """Raised when a write is blocked by company lifecycle status (e.g. SUSPENDED)."""

    def __init__(self, message: str = "Company is suspended and cannot be modified") -> None:
        super().__init__(message, code="LOCKED")


class LegalEntityDeactivationBlockedError(ConflictError):
    """FR-ORG-014 — never hard-delete; deactivation is blocked while active Branch rows
    still reference this legal entity."""

    code = "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES"

    def __init__(self, *, active_branch_count: int) -> None:
        message = "This legal entity cannot be deactivated while it has active branches"
        super().__init__(
            message,
            details=[
                {
                    "field": "is_active",
                    "code": "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES",
                    "message": message,
                    "context": {"active_branch_count": active_branch_count},
                }
            ],
        )


class BranchDeactivationBlockedError(ConflictError):
    """FR-ORG-014 — never hard-delete; deactivation is blocked while active Department rows
    still reference this branch. (The Employee half of FR-ORG-014 is out of scope: Employee
    does not exist yet.)"""

    code = "BRANCH_HAS_ACTIVE_DEPARTMENTS"

    def __init__(self, *, active_department_count: int) -> None:
        message = "This branch cannot be deactivated while it has active departments"
        super().__init__(
            message,
            details=[
                {
                    "field": "is_active",
                    "code": "BRANCH_HAS_ACTIVE_DEPARTMENTS",
                    "message": message,
                    "context": {"active_department_count": active_department_count},
                }
            ],
        )


class InvalidLegalEntityError(ValidationError):
    """Raised when a Branch is created/updated against a `legal_entity_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — the FK constraint alone
    would surface an opaque `IntegrityError`/500, not the documented 422 envelope."""

    code = "INVALID_LEGAL_ENTITY"

    def __init__(
        self, message: str = "legal_entity_id does not reference a valid legal entity"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "legal_entity_id",
                    "code": "INVALID_LEGAL_ENTITY",
                    "message": message,
                }
            ],
        )


class InvalidBranchError(ValidationError):
    """Raised when a Department is created/updated against a `branch_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — mirrors
    `InvalidLegalEntityError` for Branch's own `legal_entity_id`."""

    code = "INVALID_BRANCH"

    def __init__(self, message: str = "branch_id does not reference a valid branch") -> None:
        super().__init__(
            message,
            details=[{"field": "branch_id", "code": "INVALID_BRANCH", "message": message}],
        )


class InvalidParentDepartmentError(ValidationError):
    """Raised when a Department's `parent_id` does not exist, is soft-deleted, or belongs
    to a different tenant."""

    code = "INVALID_PARENT_DEPARTMENT"

    def __init__(self, message: str = "parent_id does not reference a valid department") -> None:
        super().__init__(
            message,
            details=[
                {"field": "parent_id", "code": "INVALID_PARENT_DEPARTMENT", "message": message}
            ],
        )


class InvalidDepartmentError(ValidationError):
    """Raised when a Designation is created/updated against a `department_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — mirrors `InvalidBranchError`
    for Department's own `branch_id`."""

    code = "INVALID_DEPARTMENT"

    def __init__(
        self, message: str = "department_id does not reference a valid department"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "department_id", "code": "INVALID_DEPARTMENT", "message": message}],
        )


class InvalidGradeError(ValidationError):
    """Raised when a Designation is created/updated against a `grade_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — mirrors
    `InvalidDepartmentError` for Designation's own `department_id`."""

    code = "INVALID_GRADE"

    def __init__(self, message: str = "grade_id does not reference a valid grade") -> None:
        super().__init__(
            message,
            details=[{"field": "grade_id", "code": "INVALID_GRADE", "message": message}],
        )


class InvalidCtcRangeError(ValidationError):
    """Sprint 3 Task 3.3.1's own documented rule: `min_ctc <= max_ctc` when both are
    present (docs/modules/grade/00_GRADE_AUDIT.md §6.4)."""

    code = "INVALID_CTC_RANGE"

    def __init__(self, message: str = "min_ctc must not be greater than max_ctc") -> None:
        super().__init__(
            message,
            details=[{"field": "max_ctc", "code": "INVALID_CTC_RANGE", "message": message}],
        )


class GradeCodeAlreadyExistsError(ConflictError):
    """The `grade` table already carries a `UNIQUE (company_id, code)` constraint
    (predates this slice, scripts/sql/001_init_schema.sql) — this converts the resulting
    `IntegrityError` into the documented error envelope rather than a raw 500, mirroring how
    `register_company` converts a duplicate-email `IntegrityError` into `ConflictError`."""

    code = "GRADE_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A grade with this code already exists") -> None:
        super().__init__(
            message,
            details=[{"field": "code", "code": "GRADE_CODE_ALREADY_EXISTS", "message": message}],
        )


class InvalidShiftTimeRangeError(ValidationError):
    """Task 4.2.1's own documented rule (docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md
    §6.2): `end_time` before `start_time` is only valid when `is_cross_midnight=true`."""

    code = "INVALID_SHIFT_TIME_RANGE"

    def __init__(
        self, message: str = "end_time must be after start_time unless is_cross_midnight is set"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "end_time", "code": "INVALID_SHIFT_TIME_RANGE", "message": message}],
        )


class InvalidShiftHoursRangeError(ValidationError):
    """Task 4.2.1's own documented rule (docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md
    §6.3): `half_day_threshold_hours` must be less than `min_hours_full_day` when both are
    present."""

    code = "INVALID_SHIFT_HOURS_RANGE"

    def __init__(
        self,
        message: str = "half_day_threshold_hours must be less than min_hours_full_day",
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "half_day_threshold_hours",
                    "code": "INVALID_SHIFT_HOURS_RANGE",
                    "message": message,
                }
            ],
        )


class DepartmentCycleDetectedError(ConflictError):
    """FR-ORG-005 — the department hierarchy must never contain a cycle. Raised when the
    candidate `parent_id` is the department itself or one of its own descendants."""

    code = "DEPARTMENT_CYCLE_DETECTED"

    def __init__(
        self, message: str = "This parent department would create a cycle in the hierarchy"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "parent_id", "code": "DEPARTMENT_CYCLE_DETECTED", "message": message}
            ],
        )


class DepartmentMaxDepthExceededError(ConflictError):
    """FR-ORG-005 — the department hierarchy is capped at 5 levels."""

    code = "DEPARTMENT_MAX_DEPTH_EXCEEDED"

    def __init__(
        self, message: str = "This parent department would exceed the maximum hierarchy depth of 5"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "parent_id",
                    "code": "DEPARTMENT_MAX_DEPTH_EXCEEDED",
                    "message": message,
                }
            ],
        )


class StaleResourceError(ConflictError):
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

"""Module-specific AppError subclasses for the employee module.

Defined locally rather than imported from `organisation/exceptions.py` — the two modules are
independent packages (locked decision #7) and each owns its own error shapes, even where the
shape (e.g. `StaleResourceError`) is structurally identical to another module's. Both ultimately
subclass the shared `core.errors.base` hierarchy.
"""

from typing import Any

from hrms.core.errors.base import ConflictError, ValidationError


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


class EmployeeSeatLimitExceededError(ConflictError):
    """Raised by `EmployeeService.create_employee` when the company's active employee count
    has already reached the plan's resolved `EMPLOYEE_SEATS` limit
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A6). Never raised when
    the resolved limit is `None` (unlimited) or when no subscription can be resolved at all
    (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.4 — fail open on unresolvable data, fail closed on an
    actually-resolved limit)."""

    code = "EMPLOYEE_SEAT_LIMIT_EXCEEDED"

    def __init__(
        self, message: str = "The plan's employee seat limit has been reached", *, limit: int
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "company_id",
                    "code": "EMPLOYEE_SEAT_LIMIT_EXCEEDED",
                    "message": message,
                    "context": {"seat_limit": limit},
                }
            ],
        )


class InvalidLegalEntityReferenceError(ValidationError):
    """Raised when an `Employment` is created/updated against a `legal_entity_id` that does
    not exist, is soft-deleted, or belongs to a different tenant — mirrors `organisation`'s
    own `InvalidLegalEntityError` for Branch, defined locally per this module's error-shape
    convention (see module docstring)."""

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


class EmploymentDatesOverlapError(ConflictError):
    """Raised when inserting an employment row would overlap an existing one for the same
    employee — the `employment_no_overlap` GiST exclusion constraint's friendly-error
    backstop. Covers both a genuine date overlap between two historical spells and the
    "employee already has an `ACTIVE` employment" case (an open spell's range extends to
    infinity, so any new insert overlaps it)."""

    code = "EMPLOYMENT_DATES_OVERLAP"

    def __init__(
        self,
        message: str = (
            "This employment's dates overlap an existing employment episode for this "
            "employee, or the employee already has an active employment"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "joining_date", "code": "EMPLOYMENT_DATES_OVERLAP", "message": message}
            ],
        )


class EmploymentNotActiveError(ConflictError):
    """Raised when an action that requires an `ACTIVE` employment (a field correction via
    `PATCH`, or the `terminate` action) is attempted against an employment row that is already
    `TERMINATED`. Employment episodes are immutable historical records once closed
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C) — there is no path
    that reopens or edits a `TERMINATED` row."""

    code = "EMPLOYMENT_NOT_ACTIVE"

    def __init__(self, message: str = "This employment is not active") -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": "EMPLOYMENT_NOT_ACTIVE", "message": message}],
        )


class InvalidLastWorkingDayError(ValidationError):
    code = "INVALID_LAST_WORKING_DAY"

    def __init__(
        self, message: str = "last_working_day cannot be before the employment's joining_date"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "last_working_day",
                    "code": "INVALID_LAST_WORKING_DAY",
                    "message": message,
                }
            ],
        )


class NoActiveEmploymentError(ConflictError):
    """Raised when an assignment's `effective_from` falls on a date the employee has no
    covering employment episode (`EmploymentRepository.get_employment_as_of` returns `None`).
    Not a DB constraint — `employee_assignment` deliberately has no `employment_id` column
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B3), so this integrity
    rule has no FK/CHECK backstop and is enforced only here
    (`docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.1)."""

    code = "NO_ACTIVE_EMPLOYMENT"

    def __init__(
        self,
        message: str = (
            "This employee has no employment episode covering the given effective_from date"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "effective_from", "code": "NO_ACTIVE_EMPLOYMENT", "message": message}
            ],
        )


class AssignmentDatesOverlapError(ConflictError):
    """Raised when inserting an assignment row would overlap an existing one for the same
    employee — the `employee_assignment_no_overlap` GiST exclusion constraint's friendly-error
    backstop, mirroring `EmploymentDatesOverlapError` exactly."""

    code = "ASSIGNMENT_DATES_OVERLAP"

    def __init__(
        self,
        message: str = ("This assignment's dates overlap an existing assignment for this employee"),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "effective_from", "code": "ASSIGNMENT_DATES_OVERLAP", "message": message}
            ],
        )


class AssignmentFieldsRequiredError(ValidationError):
    """Raised when the very first assignment for an employee (no current row to carry
    unspecified fields forward from) omits one of the mandatory placement fields
    (`branch_id`/`department_id`/`designation_id`,
    `02_EMPLOYEE_DATA_MODEL.md` §2 section D). Conditional on server-side state (whether a
    current row exists), so it cannot be expressed as a static Pydantic-required field
    (`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.3)."""

    code = "ASSIGNMENT_FIELDS_REQUIRED"

    def __init__(self, missing_fields: list[str]) -> None:
        message = f"{', '.join(missing_fields)} required for an employee's first assignment"
        super().__init__(
            message,
            details=[
                {
                    "field": field,
                    "code": "ASSIGNMENT_FIELDS_REQUIRED",
                    "message": message,
                }
                for field in missing_fields
            ],
        )


class InvalidBranchReferenceError(ValidationError):
    code = "INVALID_BRANCH"

    def __init__(self, message: str = "branch_id does not reference a valid branch") -> None:
        super().__init__(
            message, details=[{"field": "branch_id", "code": "INVALID_BRANCH", "message": message}]
        )


class InvalidDepartmentReferenceError(ValidationError):
    code = "INVALID_DEPARTMENT"

    def __init__(
        self, message: str = "department_id does not reference a valid department"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "department_id", "code": "INVALID_DEPARTMENT", "message": message}],
        )


class InvalidDesignationReferenceError(ValidationError):
    code = "INVALID_DESIGNATION"

    def __init__(
        self, message: str = "designation_id does not reference a valid designation"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "designation_id", "code": "INVALID_DESIGNATION", "message": message}
            ],
        )


class InvalidGradeReferenceError(ValidationError):
    code = "INVALID_GRADE"

    def __init__(self, message: str = "grade_id does not reference a valid grade") -> None:
        super().__init__(
            message, details=[{"field": "grade_id", "code": "INVALID_GRADE", "message": message}]
        )


class AssignmentVersionRequiredError(ValidationError):
    """Raised when a `POST .../assignments` call omits `If-Match` while the employee already
    has a current assignment row to close — the version being checked belongs to the row being
    closed, not the row being created, so it cannot be inferred
    (`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §15). Not required for an employee's very
    first assignment, since there is nothing to version-check."""

    code = "ASSIGNMENT_VERSION_REQUIRED"

    def __init__(
        self,
        message: str = (
            "If-Match is required: this employee already has a current assignment to close"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "If-Match", "code": "ASSIGNMENT_VERSION_REQUIRED", "message": message}
            ],
        )


class InvalidEffectiveFromError(ValidationError):
    """Raised when `effective_from` does not fall strictly after the current assignment row's
    own `effective_from` — the write pattern (`02_EMPLOYEE_DATA_MODEL.md` §1.2) closes the
    current row the day before the new one starts, which is only meaningful if the new row
    starts later."""

    code = "INVALID_EFFECTIVE_FROM"

    def __init__(
        self,
        message: str = (
            "effective_from must be strictly after the current assignment's effective_from"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "effective_from", "code": "INVALID_EFFECTIVE_FROM", "message": message}
            ],
        )


class InvalidShiftReferenceError(ValidationError):
    code = "INVALID_SHIFT"

    def __init__(self, message: str = "shift_id does not reference a valid shift") -> None:
        super().__init__(
            message, details=[{"field": "shift_id", "code": "INVALID_SHIFT", "message": message}]
        )


class ShiftIdRequiredError(ValidationError):
    """Raised when `change_type="SHIFT_CHANGE"` is requested without `shift_id` — unlike every
    other field on this endpoint, a shift change is meaningless without stating which shift, so
    this is checked in addition to (not instead of) the general carry-forward rule."""

    code = "SHIFT_ID_REQUIRED"

    def __init__(
        self, message: str = "shift_id is required when change_type is SHIFT_CHANGE"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "shift_id", "code": "SHIFT_ID_REQUIRED", "message": message}],
        )


class CompensationDatesOverlapError(ConflictError):
    """Raised when inserting a compensation row would overlap an existing one for the same
    employee — the `employee_compensation_no_overlap` GiST exclusion constraint's
    friendly-error backstop, mirroring `AssignmentDatesOverlapError` exactly."""

    code = "COMPENSATION_DATES_OVERLAP"

    def __init__(
        self,
        message: str = (
            "This compensation row's dates overlap an existing compensation row for this employee"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "COMPENSATION_DATES_OVERLAP",
                    "message": message,
                }
            ],
        )


class CompensationVersionRequiredError(ValidationError):
    """Raised when a `POST .../compensation` call omits `If-Match` while the employee already
    has a current compensation row to close — the version being checked belongs to the row
    being closed, not the row being created, so it cannot be inferred, mirroring
    `AssignmentVersionRequiredError` exactly. Not required for an employee's very first
    compensation row, since there is nothing to version-check."""

    code = "COMPENSATION_VERSION_REQUIRED"

    def __init__(
        self,
        message: str = (
            "If-Match is required: this employee already has a current compensation row to close"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "If-Match", "code": "COMPENSATION_VERSION_REQUIRED", "message": message}
            ],
        )


class InvalidReportingManagerError(ValidationError):
    """Covers both `reporting_manager_id` and `dotted_line_manager_id` — raised when the
    referenced id does not resolve to an existing, same-tenant, non-deleted `Employee`, or
    when it equals the assignment's own `employee_id` (an employee cannot manage themselves —
    a direct-self-reference guard only, not full cycle detection,
    `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.5)."""

    code = "INVALID_REPORTING_MANAGER"

    def __init__(self, *, field: str, message: str) -> None:
        super().__init__(
            message,
            details=[{"field": field, "code": "INVALID_REPORTING_MANAGER", "message": message}],
        )

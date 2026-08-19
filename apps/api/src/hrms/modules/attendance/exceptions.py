"""Module-specific AppError subclasses for the attendance module.

Shared across all three policy families (Attendance/Overtime/Regularization) since they share
one identity+version+publish shape (mirrors `organisation.exceptions`'s `ShiftVersion*` classes,
generalised here instead of tripled — the three families differ only in which typed rule
children they carry, not in the versioning state machine)."""

from typing import Any

from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError


class PolicyCodeAlreadyExistsError(ConflictError):
    """A partial unique index on `(company_id, code)` for active rows backs this, mirroring
    `HolidayCalendarCodeAlreadyExistsError`."""

    code = "POLICY_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A policy with this code already exists") -> None:
        super().__init__(
            message,
            details=[{"field": "code", "code": "POLICY_CODE_ALREADY_EXISTS", "message": message}],
        )


class PolicyDraftAlreadyExistsError(ConflictError):
    """At most one open DRAFT version per policy identity (partial unique index, mirrors
    `shift_version_one_open_draft_idx`)."""

    code = "POLICY_DRAFT_ALREADY_EXISTS"

    def __init__(
        self, message: str = "This policy already has an open draft version"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "policy_id", "code": "POLICY_DRAFT_ALREADY_EXISTS", "message": message}
            ],
        )


class PolicyVersionNotDraftError(ConflictError):
    """A published version can never be mutated/discarded again — a new draft must be created."""

    code = "POLICY_VERSION_NOT_DRAFT"

    def __init__(self, message: str = "Only a DRAFT version can be modified") -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": "POLICY_VERSION_NOT_DRAFT", "message": message}],
        )


class PolicyVersionPreviousVersionRequiredError(ValidationError):
    """When a currently open PUBLISHED version already exists, the caller must supply
    `expected_previous_version` so it can be closed (mirrors
    `ShiftVersionPreviousVersionRequiredError`)."""

    code = "POLICY_VERSION_PREVIOUS_VERSION_REQUIRED"

    def __init__(
        self,
        message: str = (
            "expected_previous_version is required to publish over an existing published version"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "expected_previous_version",
                    "code": "POLICY_VERSION_PREVIOUS_VERSION_REQUIRED",
                    "message": message,
                }
            ],
        )


class InvalidPolicyVersionEffectiveFromError(ValidationError):
    code = "INVALID_POLICY_VERSION_EFFECTIVE_FROM"

    def __init__(
        self,
        message: str = (
            "effective_from must be after the currently published version's effective_from"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "INVALID_POLICY_VERSION_EFFECTIVE_FROM",
                    "message": message,
                }
            ],
        )


class PolicyVersionOverlapError(ConflictError):
    """GiST exclusion backstop for the insert-new/close-previous publish flow, converts the
    resulting `IntegrityError` into the documented envelope (mirrors `ShiftVersionOverlapError`)."""

    code = "POLICY_VERSION_OVERLAP"

    def __init__(
        self,
        message: str = "Another published version already covers part of this date range",
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "effective_from", "code": "POLICY_VERSION_OVERLAP", "message": message}
            ],
        )


class PolicyVersionNotFoundForDateError(NotFoundError):
    code = "POLICY_VERSION_NOT_FOUND_FOR_DATE"

    def __init__(
        self, message: str = "No published policy version covers this date"
    ) -> None:
        super().__init__(message)


class StalePolicyResourceError(ConflictError):
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


class PolicyPublishIncompleteError(ValidationError):
    """Raised when a draft is missing typed configuration required to publish — e.g. an
    Attendance Policy with zero hour bands (architecture §36: "publishing incomplete policy" must
    be a clear validation error, never silently normalized)."""

    code = "POLICY_PUBLISH_INCOMPLETE"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": "POLICY_PUBLISH_INCOMPLETE", "message": message}],
        )


class InvalidPolicyBandError(ValidationError):
    """Raised when hour/late/early-departure bands are missing, negative, unordered, gapped, or
    overlapping (architecture §36). Applies uniformly to all three band child tables."""

    code = "INVALID_POLICY_BAND"

    def __init__(self, message: str, *, field: str = "bands") -> None:
        super().__init__(
            message,
            details=[{"field": field, "code": "INVALID_POLICY_BAND", "message": message}],
        )


class InvalidPolicyRateRowError(ValidationError):
    code = "INVALID_POLICY_RATE_ROW"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[
                {"field": "rate_rows", "code": "INVALID_POLICY_RATE_ROW", "message": message}
            ],
        )


class InvalidRegularizationAllowedTypeError(ValidationError):
    code = "INVALID_REGULARIZATION_ALLOWED_TYPE"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "allowed_types",
                    "code": "INVALID_REGULARIZATION_ALLOWED_TYPE",
                    "message": message,
                }
            ],
        )


# ---------------------------------------------------------------------------
# W4 — Punch / AttendanceDay
# ---------------------------------------------------------------------------


class AttendanceDayLockedError(ConflictError):
    """Recompute refused because `AttendanceDay.is_locked` is true (WD-11 — locked days never
    silently recompute). No W4 code path can set `is_locked=true` yet (`AttendanceLock`, the
    period-lock entity, is W8 per architecture §30) — this exists so the recompute code path
    already has the refusal wired for when W8 lands."""

    code = "ATTENDANCE_DAY_LOCKED"

    def __init__(
        self, message: str = "This attendance day is locked and cannot be recomputed"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "is_locked", "code": "ATTENDANCE_DAY_LOCKED", "message": message}],
        )


class DuplicatePunchIdempotencyKeyError(ConflictError):
    """The partial unique index on `(company_id, idempotency_key)` backs this — mirrors
    `PolicyCodeAlreadyExistsError`'s pattern of converting a DB-level `IntegrityError` into the
    documented envelope."""

    code = "DUPLICATE_PUNCH_IDEMPOTENCY_KEY"

    def __init__(
        self, message: str = "A punch with this idempotency_key already exists"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "idempotency_key",
                    "code": "DUPLICATE_PUNCH_IDEMPOTENCY_KEY",
                    "message": message,
                }
            ],
        )

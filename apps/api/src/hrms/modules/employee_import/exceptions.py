"""Module-specific AppError subclasses for employee_import."""

from hrms.core.errors.base import AppError, NotFoundError, ValidationError


class ImportBatchNotFoundError(NotFoundError):
    code = "IMPORT_BATCH_NOT_FOUND"

    def __init__(self, message: str = "Import batch not found") -> None:
        super().__init__(message)


class ImportRowLimitExceededError(ValidationError):
    """Raised when an upload has more than `MAX_IMPORT_ROWS` data rows — enforced synchronously
    at upload time, before the file ever reaches S3/Celery, so the client gets an immediate,
    actionable error instead of waiting for an async batch to fail."""

    code = "IMPORT_ROW_LIMIT_EXCEEDED"

    def __init__(self, *, row_count: int, limit: int) -> None:
        message = f"File has {row_count} rows; the limit per import is {limit}"
        super().__init__(
            message,
            details=[{"field": "file", "code": "IMPORT_ROW_LIMIT_EXCEEDED", "message": message}],
        )


class ImportFileTooLargeError(ValidationError):
    """Raised when the uploaded CSV exceeds `MAX_IMPORT_FILE_SIZE_BYTES` (SEC-03) — checked
    before the file is parsed, mirroring `OnboardingDocumentTooLargeError`'s own posture."""

    code = "IMPORT_FILE_TOO_LARGE"

    def __init__(self, max_size_bytes: int) -> None:
        message = f"File exceeds the {max_size_bytes // (1024 * 1024)}MB upload limit"
        super().__init__(
            message,
            details=[{"field": "file", "code": "IMPORT_FILE_TOO_LARGE", "message": message}],
        )


class ImportHeaderInvalidError(ValidationError):
    """Raised when the CSV header row is missing required columns or contains unrecognized
    ones — checked once, up front, so a mistyped header produces one clear error instead of a
    confusing per-row failure for every single row in the file."""

    code = "IMPORT_HEADER_INVALID"

    def __init__(self, *, missing: list[str], unexpected: list[str]) -> None:
        parts = []
        if missing:
            parts.append(f"missing required columns: {', '.join(missing)}")
        if unexpected:
            parts.append(f"unrecognized columns: {', '.join(unexpected)}")
        message = "Invalid CSV header — " + "; ".join(parts)
        super().__init__(
            message,
            details=[{"field": "file", "code": "IMPORT_HEADER_INVALID", "message": message}],
        )


class ImportFileEmptyError(ValidationError):
    code = "IMPORT_FILE_EMPTY"

    def __init__(self, message: str = "File has no data rows") -> None:
        super().__init__(
            message, details=[{"field": "file", "code": "IMPORT_FILE_EMPTY", "message": message}]
        )


class ImportFileUnreadableError(ValidationError):
    """Raised when the upload is not a UTF-8 CSV (binary content, a different encoding, or a
    malformed CSV stream) - detected at upload time, before anything reaches S3 or the queue, so
    the client gets a 422 instead of an unhandled decode error."""

    code = "IMPORT_FILE_UNREADABLE"

    def __init__(self, message: str = "File is not a readable UTF-8 CSV") -> None:
        super().__init__(
            message,
            details=[{"field": "file", "code": "IMPORT_FILE_UNREADABLE", "message": message}],
        )


class ImportQueueUnavailableError(AppError):
    """The batch was stored but could not be handed to the job queue (broker unreachable). The
    batch has been closed as `FAILED`, so nothing is left `PENDING` waiting for a message that was
    never sent; the client may simply upload the file again."""

    code = "IMPORT_QUEUE_UNAVAILABLE"
    status_code = 503

    def __init__(
        self,
        message: str = "The import could not be queued; no data was imported. Try again shortly",
    ) -> None:
        super().__init__(message)

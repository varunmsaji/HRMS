from typing import Any

#: What a client is told for a server-side failure that has no curated `public_message`.
GENERIC_SERVER_ERROR_MESSAGE = "An unexpected error occurred"


class AppError(Exception):
    """Base application error mapped to the Document 09 §1.3 envelope."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    #: EH-B-02 — the only text a client may be shown for a 5xx subclass. An instance `message`
    #: on a 5xx is for the server log (it may name fields, key versions or a provider), so it is
    #: never forwarded; a subclass that wants users to see guidance sets this to a fixed string.
    #: Ignored for 4xx, whose instance message is the curated business explanation.
    public_message: str | None = None
    #: Protocol headers the response must carry (`WWW-Authenticate` on a 401, `Retry-After` on a
    #: 429/503). A class default; an instance may override it with its own value.
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if headers is not None:
            self.headers = headers
        self.message = message
        self.details = details or []

    @property
    def client_message(self) -> str:
        """The message safe to put in the response envelope."""
        if self.status_code >= 500:
            return self.public_message or GENERIC_SERVER_ERROR_MESSAGE
        return self.message

    @property
    def client_details(self) -> list[dict[str, Any]]:
        """Field details safe to return: none for a 5xx (they are written for the log)."""
        return [] if self.status_code >= 500 else self.details


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409


class PermissionDeniedError(AppError):
    code = "PERMISSION_DENIED"
    status_code = 403


class LockedError(AppError):
    code = "LOCKED"
    status_code = 423

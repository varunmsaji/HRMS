import hashlib

from pydantic import BaseModel, Field


def error_reference(request_id: str) -> str:
    """EH-B-03 — short, speakable support reference for a server-side failure (`ERR-1A2B3C4D`).
    Derived from the request id with a hash, so it is stable for one request (the log carries the
    same value) and cannot be chosen by a client that supplies its own `X-Request-Id`."""
    return "ERR-" + hashlib.sha256(request_id.encode()).hexdigest()[:8].upper()


class ErrorDetail(BaseModel):
    field: str | None = None
    code: str
    message: str
    context: dict[str, object] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str
    #: Present on 5xx only: what the user quotes to support; searchable in the server log.
    reference: str | None = None
    documentation_url: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody

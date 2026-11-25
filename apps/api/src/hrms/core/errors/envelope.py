import hashlib
from typing import Any

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer


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

    @model_serializer(mode="wrap")
    def _omit_empty_reference(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """The key exists only on a 5xx. Every other error body keeps exactly the shape it had
        before `reference` was added, so a client written against that shape still holds."""
        data: dict[str, Any] = handler(self)
        if data.get("reference") is None:
            data.pop("reference", None)
        return data


class ErrorEnvelope(BaseModel):
    error: ErrorBody

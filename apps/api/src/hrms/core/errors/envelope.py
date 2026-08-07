from pydantic import BaseModel, Field


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
    documentation_url: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody

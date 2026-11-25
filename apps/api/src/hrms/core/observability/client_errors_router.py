"""EH-W-02 / EH-M-01 — `POST /v1/client-errors`: where the web app and the mobile app report a
failure that happened on the user's device, so a developer can find it from the `ERR-…` reference
the user was shown.

Deliberately narrow:

* **Scrubbed by construction.** The schema has no free-text message field. A report is an error
  class name, a few code locations, a route path, status/code and the id of the failed API call.
  Every field is length-bounded; unknown fields are ignored, never stored.
* **Unauthenticated.** A login or registration screen can crash too. The client IP is rate limited
  instead (fail closed, like every limiter here), and the body is size-capped in `create_app`.
  Anything that identifies the user comes from the verified tenant context, never from the body.
* **One log event.** It is written as a structured `client_error` record through the normal
  redaction pipeline, so it is searchable in the platform log viewer next to the server-side
  records. Nothing is stored in the database and nothing is sent to a third party.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from hrms.core.errors.handlers import tenant_log_fields
from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.observability.metrics import ERRORS, safe_count
from hrms.core.observability.redaction import redact_path
from hrms.shared.rate_limit import rate_limit

router = APIRouter(tags=["observability"])
_logger = get_logger("hrms.client_errors")

#: Per client IP. A crash loop on one device must not be able to flood the log.
_client_error_rate_limit = rate_limit("client_errors", limit=20, window_seconds=60)

#: Largest request body accepted (`create_app` wires `MaxUploadSizeMiddleware` to this).
MAX_CLIENT_ERROR_BODY_BYTES = 8 * 1024


class ClientErrorReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Literal["web", "mobile"]
    kind: str = Field(max_length=32)
    error_class: str = Field(max_length=120)
    frames: list[str] = Field(default_factory=list, max_length=5)
    path: str | None = Field(default=None, max_length=200)
    request_id: str | None = Field(default=None, max_length=64)
    reference: str | None = Field(default=None, max_length=24)
    status: int | None = Field(default=None, ge=0, le=599)
    code: str | None = Field(default=None, max_length=64)
    app_version: str | None = Field(default=None, max_length=32)


@router.post(
    "/client-errors",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_client_error_rate_limit)],
    include_in_schema=False,
)
async def report_client_error(body: ClientErrorReport) -> Response:
    safe_count(ERRORS, "client_error", body.source)
    safe_log(
        _logger.error,
        "client_error",
        source=body.source,
        kind=body.kind,
        error_class=body.error_class,
        frames=[frame[:200] for frame in body.frames],
        # The page path can carry a bearer token (`/reset-password/<token>`); mask it like every
        # other logged path.
        page_path=redact_path(body.path) if body.path else None,
        client_request_id=body.request_id,
        reference=body.reference,
        http_status=body.status,
        error_code=body.code,
        app_version=body.app_version,
        **tenant_log_fields(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

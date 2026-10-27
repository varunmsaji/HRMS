"""`GET /metrics` - Prometheus scrape endpoint, closed by default.

* Disabled (404) until `METRICS_TOKEN` is set, so a deployment that has not chosen a scraper
  exposes nothing. A 404, not a 401: the endpoint's existence is not advertised.
* Requires `Authorization: Bearer <METRICS_TOKEN>` (constant-time compare). It is not part of the
  tenant API: no user JWT is accepted, no tenant data is in the output.
* Must not be proxied by Nginx (`infra/nginx/conf.d/hrms.conf.template` returns 404 for it). The
  scraper reaches `api:8000` over the private Docker network.
* A rejected request (401, or 404 while disabled) is logged as an ordinary `http_request` event and
  counted like any other request (a 401 also lands in `hrms_http_denials_total`); only a
  *successful* scrape is left
  out of the logs and the request metrics. Nginx never proxies this path, so only containers on
  the private network can reach it.
"""

import hmac

from fastapi import APIRouter, Header, HTTPException, Response, status

from hrms.core.config.settings import get_settings
from hrms.core.observability.scrape import render_metrics

router = APIRouter(tags=["observability"], include_in_schema=False)

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics")
async def metrics(authorization: str | None = Header(default=None)) -> Response:
    token = get_settings().metrics_token
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
        )
    return Response(content=await render_metrics(), media_type=_CONTENT_TYPE)

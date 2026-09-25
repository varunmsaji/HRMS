"""SEC-06 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — the HttpOnly cookie that
replaces returning the refresh token in a JSON response body. Before this, every token-issuing
endpoint (login, refresh, registration, invite acceptance) put the raw 30-day refresh token in
its JSON response, which the frontend then wrote to `localStorage` — a value a page's own
JavaScript can read, and therefore a value an XSS payload can read and exfiltrate.

`hrms_refresh` was already the cookie name `POST /v1/auth/token/refresh` fell back to reading
(`identity/router.py`'s `body.refresh_token or request.cookies.get("hrms_refresh")`) — nothing in
this codebase ever set it until this change wired the write side up too.

Cookie shape:
  - `HttpOnly` — always; this is the entire point (client-side JavaScript, malicious or not,
    cannot read the value).
  - `Secure` — conditional on the request actually being HTTPS, the same pattern SEC-05's HSTS
    header already established (`core/security_headers.py`): this repository has no TLS
    termination anywhere yet (Docker/Nginx/HTTPS is a later, separate phase), so a
    hardcoded `Secure=True` would make the cookie silently never send in any environment that
    exists today. It activates automatically the day a trusted reverse proxy terminates TLS in
    front of this app, with zero further code changes.
  - `SameSite=Lax` — the primary CSRF defense for the refresh endpoint (a `POST`): Lax cookies are
    not attached to cross-site `fetch`/XHR requests at all (only to a cross-site top-level *GET*
    navigation), so a malicious page cannot trigger a cross-site `POST /v1/auth/token/refresh`
    with this cookie attached. A separate double-submit CSRF token would be redundant defense for
    this one endpoint given that property, and was deliberately not added (smallest safe change).
  - `Path=/v1/auth` — scoped to the auth routes that actually consume it (`token/refresh`,
    `logout`), not sent on every other API request.
"""

from fastapi import Request, Response

from hrms.core.config.settings import Settings

REFRESH_COOKIE_NAME = "hrms_refresh"
REFRESH_COOKIE_PATH = "/v1/auth"


def set_refresh_cookie(
    response: Response, request: Request, *, raw_refresh_token: str, settings: Settings
) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=settings.jwt_refresh_ttl_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)

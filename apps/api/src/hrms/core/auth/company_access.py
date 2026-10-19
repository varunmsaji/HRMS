"""Company-lifecycle gate for tenant (non-platform) requests.

`PENDING_APPROVAL` and `SUSPENDED` companies are *read-only*: their users can sign in and read,
but every state-changing request is refused. `REJECTED` and `TERMINATED` companies cannot sign in
or use an existing token at all. `TRIAL` and `ACTIVE` are unrestricted.

One function is shared by the three places that must agree: sign-in, token refresh, and the
per-request `get_current_user` dependency (so a status change takes effect on the very next
request, not when the access token expires)."""

from hrms.core.errors.company import (
    CompanyAccessError,
    CompanyPendingApprovalError,
    CompanyRejectedError,
    CompanySuspendedError,
    CompanyTerminatedError,
)

#: Statuses whose users may read but not write.
READ_ONLY_STATUSES = frozenset({"PENDING_APPROVAL", "SUSPENDED"})
#: Statuses whose users get no access.
BLOCKED_STATUSES = frozenset({"REJECTED", "TERMINATED"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Writes under these prefixes stay allowed in read-only mode (sign-out, token refresh, ...).
_WRITE_ALLOWED_PREFIXES = ("/v1/auth/",)


def _error_for(status: str) -> CompanyAccessError:
    return {
        "PENDING_APPROVAL": CompanyPendingApprovalError,
        "SUSPENDED": CompanySuspendedError,
        "REJECTED": CompanyRejectedError,
        "TERMINATED": CompanyTerminatedError,
    }[status]()


def assert_can_sign_in(company_status: str) -> None:
    """Sign-in / refresh: only blocked statuses are refused (read-only ones may sign in)."""
    if company_status in BLOCKED_STATUSES:
        raise _error_for(company_status)


def assert_request_allowed(company_status: str, *, method: str, path: str) -> None:
    """Per-request gate for an already-authenticated tenant user."""
    if company_status in BLOCKED_STATUSES:
        raise _error_for(company_status)
    if company_status in READ_ONLY_STATUSES:
        if method.upper() in _SAFE_METHODS or path.startswith(_WRITE_ALLOWED_PREFIXES):
            return
        raise _error_for(company_status)

"""Company-lifecycle gate: which statuses may sign in, and which may write."""

import pytest

from hrms.core.auth.company_access import assert_can_sign_in, assert_request_allowed
from hrms.core.errors.company import CompanyAccessError


@pytest.mark.parametrize("status", ["TRIAL", "ACTIVE", "PENDING_APPROVAL", "SUSPENDED"])
def test_these_statuses_may_sign_in(status: str) -> None:
    assert_can_sign_in(status)


@pytest.mark.parametrize(
    ("status", "code"),
    [("REJECTED", "COMPANY_REJECTED"), ("TERMINATED", "COMPANY_TERMINATED")],
)
def test_blocked_statuses_cannot_sign_in(status: str, code: str) -> None:
    with pytest.raises(CompanyAccessError) as caught:
        assert_can_sign_in(status)
    assert caught.value.code == code and caught.value.status_code == 403


@pytest.mark.parametrize("status", ["TRIAL", "ACTIVE"])
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_active_companies_are_unrestricted(status: str, method: str) -> None:
    assert_request_allowed(status, method=method, path="/v1/branches")


@pytest.mark.parametrize(
    ("status", "code"),
    [("PENDING_APPROVAL", "COMPANY_PENDING_APPROVAL"), ("SUSPENDED", "COMPANY_SUSPENDED")],
)
def test_read_only_statuses_allow_reads_and_auth_but_not_writes(status: str, code: str) -> None:
    for method in ("GET", "HEAD", "OPTIONS"):
        assert_request_allowed(status, method=method, path="/v1/employees")
    assert_request_allowed(status, method="POST", path="/v1/auth/logout")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(CompanyAccessError) as caught:
            assert_request_allowed(status, method=method, path="/v1/employees")
        assert caught.value.code == code


@pytest.mark.parametrize("status", ["REJECTED", "TERMINATED"])
def test_blocked_statuses_cannot_even_read(status: str) -> None:
    with pytest.raises(CompanyAccessError):
        assert_request_allowed(status, method="GET", path="/v1/employees")

"""CI guard: a permission-gated route must USE the data scope its permission was granted with.

Static (AST) inventory of every route under `hrms.modules.*.router`; see `scope_guard.py` for the
patterns covered and the limits. Reviewed exceptions live in `scope_guard_exceptions.toml`.
A static guard supplements - it does not replace - the runtime scope tests
(`test_period_summary_scope.py`, `test_adjustment_scope.py`).

Regression coverage for DEF-B6-02 (attendance-period summary) and DEF-B10-01 (leave-ledger
adjustment / encashment): both original shapes are flagged by the scanner, and the three fixed
handlers must stay in the inventory, bound to a scope, with no exception.
"""

import tomllib
from pathlib import Path

import pytest

from . import scope_guard as guard

_EXCEPTIONS = Path(__file__).with_name("scope_guard_exceptions.toml")
_KINDS = {"company_level", "scope_irrelevant", "known_gap"}
CONSTS = {"ATTENDANCE_VIEW": "ATTENDANCE.VIEW", "LEAVE_BALANCE_ADJUST": "LEAVE.BALANCE_ADJUST"}

_SUMMARY = "/attendance-periods/{period_id}/summary"
FIXED_HANDLERS = {
    "hrms.modules.attendance.router:get_attendance_period_summary": _SUMMARY,
    "hrms.modules.leave.router:create_leave_ledger_adjustment": "/leave-ledger/adjustments",
    "hrms.modules.leave.router:create_leave_ledger_encashment": "/leave-ledger/encashments",
    # B12 / OBS-HRA-01 - formerly `known_gap`; each enforces scope (runtime regression tests).
    "hrms.modules.attendance.router:calculate_attendance_day": "/attendance/days/calculate",
    "hrms.modules.attendance.router:recompute_attendance_day": (
        "/attendance/days/{attendance_day_id}/recompute"
    ),
    "hrms.modules.attendance.router:calculate_attendance_range": (
        "/attendance/days/calculate-range"
    ),
    "hrms.modules.attendance.router:keep_leave_over_punches": (
        "/attendance/days/{attendance_day_id}/work-on-leave/keep-leave"
    ),
    "hrms.modules.account_invite.router:invite_employee": "/employees/{employee_id}/invite",
}


def _exceptions() -> tuple[dict[str, dict], dict[str, dict]]:
    data = tomllib.loads(_EXCEPTIONS.read_text())
    perms = {e["code"]: e for e in data.get("permission", [])}
    handlers = {e["key"]: e for e in data.get("handler", [])}
    return perms, handlers


def _scan(src: str) -> list[guard.Handler]:
    return guard.scan_source(src, "synthetic.router", CONSTS)


# ------------------------------------------------------------------ scanner: defective shapes


def test_flags_the_def_b6_02_shape_unused_underscore_scope() -> None:
    (h,) = _scan(
        """
@router.get("/attendance-periods/{period_id}/summary")
async def summary(
    period_id,
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[S, Depends(get_service)],
):
    return await service.get_summary(period_id)
"""
    )
    assert h.ignored == ("ATTENDANCE.VIEW",)


def test_flags_the_def_b10_01_shape() -> None:
    (h,) = _scan(
        """
@router.post("/leave-ledger/adjustments")
async def adjust(
    body,
    _scope: Annotated[object, Depends(require_permission(LEAVE_BALANCE_ADJUST))],
    service: Annotated[S, Depends(get_service)],
):
    return await service.create_adjustment(body.employee_id, body)
"""
    )
    assert h.ignored == ("LEAVE.BALANCE_ADJUST",)


def test_flags_alias_decorator_dependencies_default_value_and_custom_scope_dependency() -> None:
    handlers = _scan(
        """
_Scoped = Annotated[object, Depends(require_permission(ATTENDANCE_VIEW))]

@router.get("/a")
async def via_alias(scope: _Scoped):
    return 1

@router.get("/b", dependencies=[Depends(require_permission(LEAVE_BALANCE_ADJUST))])
async def via_decorator():
    return 1

@router.get("/c")
async def via_default(scope=Depends(require_permission(ATTENDANCE_VIEW))):
    return 1

@router.get("/d")
async def via_custom(scope: Annotated[DataScope, Depends(_my_view_scope)]):
    return 1
"""
    )
    assert {h.function: h.ignored for h in handlers} == {
        "via_alias": ("ATTENDANCE.VIEW",),
        "via_decorator": ("LEAVE.BALANCE_ADJUST",),
        "via_default": ("ATTENDANCE.VIEW",),
        "via_custom": ("<dependency:_my_view_scope>",),
    }


def test_flags_imperative_resolve_data_scope_whose_result_is_never_read() -> None:
    (h,) = _scan(
        """
@router.post("/x")
async def imperative(user, rbac):
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, ATTENDANCE_VIEW)
    return 1
"""
    )
    assert h.ignored == ("ATTENDANCE.VIEW",)


# ------------------------------------------------------------------ scanner: enforcing shapes


def test_clean_when_the_scope_is_read_or_forwarded() -> None:
    handlers = _scan(
        """
@router.get("/ok1")
async def forwarded(
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))], service
):
    return await service.list(scope=scope)

@router.post("/ok2")
async def checked(user, rbac, service):
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, LEAVE_BALANCE_ADJUST)
    if not scope.levels:
        raise PermissionError
    return await service.go(scope)
"""
    )
    assert [h.ignored for h in handlers] == [(), ()]
    assert all(h.scope_params for h in handlers)


# ------------------------------------------------------------------ the real repository


def test_every_scope_ignoring_route_is_a_reviewed_exception() -> None:
    perms, handlers = _exceptions()
    unreviewed = [
        f"{h.method} {h.path} ({h.key}) ignores the scope of {', '.join(h.ignored)}"
        for h in guard.scan_repo()
        if h.ignored and h.key not in handlers and not all(p in perms for p in h.ignored)
    ]
    assert not unreviewed, (
        "These routes are gated by a permission that can be granted below COMPANY scope but never "
        "read the scope (the DEF-B6-02 / DEF-B10-01 defect class). Apply the scope to the target "
        "employee(s) in the service layer, or - only if the resource is not per-employee - add a "
        "reviewed entry with a reason to scope_guard_exceptions.toml:\n" + "\n".join(unreviewed)
    )


def test_exceptions_are_documented_and_not_stale() -> None:
    perms, handlers = _exceptions()
    scanned = guard.scan_repo()
    ignoring_perms = {p for h in scanned if h.ignored for p in h.ignored}
    ignoring_keys = {h.key for h in scanned if h.ignored}
    for entry in [*perms.values(), *handlers.values()]:
        assert entry["kind"] in _KINDS, entry
        assert len(entry["reason"]) >= 40, f"exception needs a real rationale: {entry}"
    assert not (set(perms) - ignoring_perms), (
        f"stale permission exceptions: {sorted(set(perms) - ignoring_perms)}"
    )
    assert not (set(handlers) - ignoring_keys), (
        f"stale handler exceptions: {sorted(set(handlers) - ignoring_keys)}"
    )
    for key, entry in handlers.items():
        assert entry["permission"] in next(h for h in scanned if h.key == key).ignored, entry
    assert all(p["kind"] == "company_level" for p in perms.values()), (
        "permission-wide exceptions may only be company_level; employee-targeted or own-record "
        "handlers need per-handler entries"
    )


def test_no_unresolved_permission_in_the_inventory() -> None:
    bad = [h.key for h in guard.scan_repo() if any(p == "<unresolved>" for p in h.permissions)]
    assert not bad, f"guard cannot resolve the permission of: {bad}"


@pytest.mark.parametrize(("key", "path"), sorted(FIXED_HANDLERS.items()))
def test_def_b6_02_and_def_b10_01_routes_enforce_scope_and_are_not_excepted(
    key: str, path: str
) -> None:
    perms, handlers = _exceptions()
    (h,) = [x for x in guard.scan_repo() if x.key == key]
    assert h.path == path and h.scope_params and not h.ignored, h
    assert key not in handlers
    assert not set(h.permissions) & set(perms)
    assert not {
        "ATTENDANCE.VIEW",
        "LEAVE.BALANCE_ADJUST",
        "ATTENDANCE.VIEW_ALL",
        "ATTENDANCE.RECOMPUTE",
        "EMPLOYEE.INVITE",
    } & set(perms)

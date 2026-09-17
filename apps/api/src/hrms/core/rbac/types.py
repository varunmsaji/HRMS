from dataclasses import dataclass, field
from enum import StrEnum


class DataScopeLevel(StrEnum):
    """`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision C locked four levels
    (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`) and left `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/
    `ALL_COMPANIES` deliberately unbuilt, pending Decision B's open question: derived from the
    caller's own org placement, or explicitly per-user assigned. `BRANCH` is now added, resolved
    the derived way (Model 2 in Decision B) — same shape as `REPORTEES`/`REPORTEE_TREE`: no new
    storage, read off the caller's own *current* `EmployeeAssignment.branch_id`
    (`employee.repository.EmployeeAssignmentRepository.get_branch_colleague_ids`). This means one
    holder's scope is always their own single branch — a manager responsible for more than one
    branch, or a branch with co-managers, is not expressible without a second role, the same
    accepted limitation Decision A already documents for `REPORTEES`/`REPORTEE_TREE`.
    `DEPARTMENT`/`LEGAL_ENTITY`/`ALL_COMPANIES` remain out of scope."""

    SELF = "SELF"
    REPORTEES = "REPORTEES"
    REPORTEE_TREE = "REPORTEE_TREE"
    BRANCH = "BRANCH"
    COMPANY = "COMPANY"


@dataclass(frozen=True, slots=True)
class DataScope:
    """The set of scope levels a caller's roles grant for one specific permission code —
    resolved by `RbacService.resolve_data_scope` (`core/rbac/service.py`). Deliberately carries
    only *levels*, not resolved employee IDs: `core/rbac` has no knowledge of
    `employee_assignment`/reporting hierarchies (`hrms.core` may not import `hrms.modules`,
    `apps/api/.importlinter`) — turning `levels` into a concrete visible-ID set is the
    consuming module's job (e.g. `EmployeeService.resolve_visible_employee_ids`,
    `25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §7). An empty `levels` set means no
    grant was found — fails closed, never implies `COMPANY`."""

    levels: frozenset[DataScopeLevel] = field(default_factory=frozenset)

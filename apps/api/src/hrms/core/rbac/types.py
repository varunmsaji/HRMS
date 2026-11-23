from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


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
    `DEPARTMENT`/`LEGAL_ENTITY`/`ALL_COMPANIES` remain out of scope.

    `ASSIGNED_BRANCHES` (2026-11-22) is the admin-assigned form of branch access for `HR_ADMIN`
    and `BRANCH_MANAGER`: the branches come from `user_branch_access` (carried on
    `DataScope.branch_ids`), not from the holder's own job placement, and one holder may cover
    several branches. `RbacService.resolve_data_scope` produces it by replacing those two roles'
    `COMPANY` / `BRANCH` grants; a user who also holds `COMPANY_ADMIN` keeps `COMPANY`. The older
    single-branch `BRANCH` level is no longer produced for those roles (see the addendum in
    `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`)."""

    SELF = "SELF"
    REPORTEES = "REPORTEES"
    REPORTEE_TREE = "REPORTEE_TREE"
    BRANCH = "BRANCH"
    ASSIGNED_BRANCHES = "ASSIGNED_BRANCHES"
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
    #: Live `user_branch_access` branch ids of the caller. Meaningful only with
    #: `ASSIGNED_BRANCHES` in `levels`; an empty set then means "no branch": fails closed.
    branch_ids: frozenset[UUID] = field(default_factory=frozenset)
    #: True when a `COMPANY` grant (the HR_ADMIN kind: approve, reassign, ...) was narrowed to the
    #: assigned branches. HR-stage approvals accept the caller for an employee in `branch_ids`
    #: only when this is set; a `BRANCH_MANAGER`'s narrowed grant never is.
    company_grant_restricted: bool = False

    @property
    def is_branch_restricted(self) -> bool:
        """The caller reaches only their assigned branches: `ASSIGNED_BRANCHES` without a
        `COMPANY` grant. A company administrator is never restricted."""
        return (
            DataScopeLevel.ASSIGNED_BRANCHES in self.levels
            and DataScopeLevel.COMPANY not in self.levels
        )

    @classmethod
    def union(cls, *scopes: "DataScope") -> "DataScope":
        """The combined scope of several permissions' scopes (a route that accepts either of two
        permissions). Building `DataScope(levels=a.levels | b.levels)` by hand would drop
        `branch_ids`, and an `ASSIGNED_BRANCHES` caller would then see nobody."""
        levels: frozenset[DataScopeLevel] = frozenset().union(*(s.levels for s in scopes))
        branch_ids: frozenset[UUID] = frozenset().union(*(s.branch_ids for s in scopes))
        return cls(
            levels=levels,
            branch_ids=branch_ids,
            company_grant_restricted=any(s.company_grant_restricted for s in scopes),
        )

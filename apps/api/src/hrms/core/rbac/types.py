from dataclasses import dataclass, field
from enum import StrEnum


class DataScopeLevel(StrEnum):
    """`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision C — four levels only in this
    slice. `TEAM` (ambiguous — one level or recursive?) is retired in favor of the two explicit
    names `REPORTEES`/`REPORTEE_TREE` `docs/product/19_RBAC_and_Permission_Matrix.md §5` already
    uses. `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` are deliberately not added yet —
    out of this slice's scope (`docs/modules/employee/
    25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §3)."""

    SELF = "SELF"
    REPORTEES = "REPORTEES"
    REPORTEE_TREE = "REPORTEE_TREE"
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

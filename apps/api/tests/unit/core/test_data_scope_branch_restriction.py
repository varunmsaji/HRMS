"""`DataScope.is_branch_restricted`: true only for a caller limited to their assigned branches."""

from uuid import uuid4

from hrms.core.rbac.types import DataScope, DataScopeLevel


def test_assigned_branches_alone_is_restricted() -> None:
    scope = DataScope(
        levels=frozenset({DataScopeLevel.ASSIGNED_BRANCHES}), branch_ids=frozenset({uuid4()})
    )
    assert scope.is_branch_restricted


def test_a_company_grant_means_not_restricted() -> None:
    both = DataScope(levels=frozenset({DataScopeLevel.ASSIGNED_BRANCHES, DataScopeLevel.COMPANY}))
    assert not both.is_branch_restricted
    assert not DataScope(levels=frozenset({DataScopeLevel.COMPANY})).is_branch_restricted


def test_other_levels_and_no_grant_are_not_restricted() -> None:
    assert not DataScope().is_branch_restricted
    assert not DataScope(levels=frozenset({DataScopeLevel.REPORTEES})).is_branch_restricted


def test_reporting_level_alongside_assigned_branches_is_still_restricted() -> None:
    scope = DataScope(
        levels=frozenset({DataScopeLevel.ASSIGNED_BRANCHES, DataScopeLevel.REPORTEES})
    )
    assert scope.is_branch_restricted


def test_union_with_a_company_scope_lifts_the_restriction() -> None:
    restricted = DataScope(
        levels=frozenset({DataScopeLevel.ASSIGNED_BRANCHES}), branch_ids=frozenset({uuid4()})
    )
    company = DataScope(levels=frozenset({DataScopeLevel.COMPANY}))
    assert not DataScope.union(restricted, company).is_branch_restricted

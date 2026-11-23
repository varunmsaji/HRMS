"""Test helpers for admin-assigned branch access.

Before admin-assigned branches, the real `HR_ADMIN` role meant "the whole company". It now means
"the assigned branches", so a test that needs an HR who sees everyone assigns them every branch and
places the employees at a branch (an employee with no branch is invisible to a branch HR).
"""

from uuid import UUID

from sqlalchemy import text

from hrms.core.db.session import get_session_factory


async def grant_all_branches(company_id: UUID, user_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO user_branch_access (company_id, user_id, branch_id)
                SELECT :cid, :uid, b.id FROM branch b
                WHERE b.company_id = :cid AND b.deleted_at IS NULL AND b.is_active
                ON CONFLICT (company_id, user_id, branch_id) WHERE deleted_at IS NULL DO NOTHING
                """
            ),
            {"cid": str(company_id), "uid": str(user_id)},
        )
        await session.commit()


async def place_at_one_branch(company_id: UUID, employee_ids: list[UUID]) -> UUID:
    """Creates one branch and puts every employee there: moves a current assignment onto it, or
    adds one when the employee has none."""
    from tests.integration.modules.employee.test_employee_data_scope import (
        _assign_manager,
        _setup_branches,
    )

    (branch_id,) = await _setup_branches(company_id=company_id, count=1)
    factory = get_session_factory()
    for employee_id in employee_ids:
        async with factory() as session:
            moved = await session.execute(
                text(
                    "UPDATE employee_assignment SET branch_id = :b WHERE company_id = :c "
                    "AND employee_id = :e AND effective_to IS NULL AND deleted_at IS NULL"
                ),
                {"b": str(branch_id), "c": str(company_id), "e": str(employee_id)},
            )
            await session.commit()
        if moved.rowcount == 0:
            await _assign_manager(
                company_id=company_id,
                employee_id=employee_id,
                reporting_manager_id=None,
                branch_id=branch_id,
            )
    return branch_id


async def make_branch(company_id: UUID) -> UUID:
    """One live branch (with its legal entity) for a tenant that has none, so an HR administrator or
    branch manager can be invited with the branch the API now requires. Sets the tenant first, so it
    also works when the suite runs as the row-level-security-bound runtime role."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from hrms.core.db.session import set_rls_company_id
    from hrms.modules.organisation.models import Branch, LegalEntity

    now = datetime.now(UTC)
    legal_entity_id, branch_id = uuid4(), uuid4()
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        session.add(
            LegalEntity(
                id=legal_entity_id,
                company_id=company_id,
                name="Test Legal Entity",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            Branch(
                id=branch_id,
                company_id=company_id,
                legal_entity_id=legal_entity_id,
                name=f"Test Branch {branch_id.hex[:8]}",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return branch_id

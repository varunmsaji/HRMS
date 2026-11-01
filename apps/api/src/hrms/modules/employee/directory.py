"""Read-only directory enrichment for the Employees screen: headline counts and, for a page of
employee ids, the current designation / department / branch / reporting manager / shift.

Pure aggregation over rows this module and `organisation` own — nothing is written and no figure is
invented. Visibility is the caller's `DataScope`, resolved by `EmployeeService`; ids outside it are
simply not returned."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NAME_SQL = (
    "coalesce(nullif({a}.display_name, ''), "
    "trim({a}.first_name || ' ' || coalesce({a}.last_name, '')))"
)


class DirectorySummary(BaseModel):
    total: int
    active: int
    on_probation: int
    on_notice: int
    department_count: int
    department_names: list[str]


class DirectoryRow(BaseModel):
    employee_id: UUID
    designation: str | None
    department: str | None
    branch: str | None
    manager_name: str | None
    shift_name: str | None


async def directory_summary(
    session: AsyncSession, company_id: UUID, visible_ids: frozenset[UUID] | None
) -> DirectorySummary:
    params: dict[str, object] = {"cid": company_id}
    scope = ""
    if visible_ids is not None:
        scope = "AND e.id = ANY(:ids)"
        params["ids"] = list(visible_ids)
    counts = (
        await session.execute(
            text(
                f"""
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE e.is_active) AS active,
                       count(*) FILTER (WHERE e.status = 'PROBATION') AS on_probation,
                       count(*) FILTER (WHERE e.status = 'ON_NOTICE') AS on_notice
                FROM employee e
                WHERE e.company_id = :cid AND e.deleted_at IS NULL {scope}
                """
            ),
            params,
        )
    ).one()
    depts = (
        await session.execute(
            text(
                f"""
                SELECT d.name, count(*) AS n
                FROM employee e
                JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
                JOIN department d ON d.id = a.department_id
                WHERE e.company_id = :cid AND e.deleted_at IS NULL {scope}
                GROUP BY d.name ORDER BY n DESC, d.name
                """
            ),
            params,
        )
    ).all()
    return DirectorySummary(
        total=int(counts.total),
        active=int(counts.active),
        on_probation=int(counts.on_probation),
        on_notice=int(counts.on_notice),
        department_count=len(depts),
        department_names=[r.name for r in depts[:4]],
    )


async def directory_rows(
    session: AsyncSession,
    company_id: UUID,
    employee_ids: list[UUID],
    visible_ids: frozenset[UUID] | None,
) -> list[DirectoryRow]:
    if visible_ids is not None:
        employee_ids = [i for i in employee_ids if i in visible_ids]
    if not employee_ids:
        return []
    rows = (
        await session.execute(
            text(
                f"""
                SELECT e.id, dg.title AS designation, d.name AS department, b.name AS branch,
                       {_NAME_SQL.format(a="m")} AS manager_name, s.name AS shift_name
                FROM employee e
                LEFT JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
                LEFT JOIN designation dg ON dg.id = a.designation_id
                LEFT JOIN department d ON d.id = a.department_id
                LEFT JOIN branch b ON b.id = a.branch_id
                LEFT JOIN employee m ON m.id = a.reporting_manager_id
                LEFT JOIN shift s ON s.id = a.shift_id
                WHERE e.company_id = :cid AND e.deleted_at IS NULL AND e.id = ANY(:ids)
                """
            ),
            {"cid": company_id, "ids": employee_ids},
        )
    ).all()
    return [
        DirectoryRow(
            employee_id=r.id,
            designation=r.designation,
            department=r.department,
            branch=r.branch,
            manager_name=(r.manager_name or None),
            shift_name=r.shift_name,
        )
        for r in rows
    ]

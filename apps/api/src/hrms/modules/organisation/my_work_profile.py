"""Employee self-service "where and when do I work" read for the mobile Home: the caller's current
shift (name and scheduled times) and work location (branch). The employee comes only from the
caller (the router passes `AuthenticatedUser.employee_id`); there is no employee parameter.

An employee cannot read `/shifts` or `/branches` (both need management permissions), so this is the
one place that exposes those two facts, and only for the caller's own current placement. Nothing is
inferred: a missing placement, shift or branch is returned as `None`, never a default.
"""

from datetime import date, time
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import Company
from hrms.core.db.session import get_session
from hrms.modules.employee.models import EmployeeAssignment
from hrms.modules.organisation.models import (
    Branch,
    Department,
    Designation,
    Shift,
    ShiftVersion,
)
from hrms.shared.business_time import business_today


class MyShiftRead(BaseModel):
    name: str
    start_time: time | None = None
    end_time: time | None = None
    timezone: str | None = None


class MyWorkLocationRead(BaseModel):
    name: str
    city: str | None = None
    address_line1: str | None = None
    work_location_type: str | None = None


class MyWorkProfileRead(BaseModel):
    shift: MyShiftRead | None = None
    work_location: MyWorkLocationRead | None = None
    designation: str | None = None
    department: str | None = None


class MyWorkProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_my_work_profile(self, company_id: UUID, employee_id: UUID) -> MyWorkProfileRead:
        company_tz = (
            await self._session.execute(select(Company.timezone).where(Company.id == company_id))
        ).scalar_one()
        today = business_today(company_tz)
        assignment = (
            await self._session.execute(
                select(EmployeeAssignment).where(
                    EmployeeAssignment.company_id == company_id,
                    EmployeeAssignment.employee_id == employee_id,
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.effective_from <= today,
                    or_(
                        EmployeeAssignment.effective_to.is_(None),
                        EmployeeAssignment.effective_to >= today,
                    ),
                )
            )
        ).scalar_one_or_none()
        if assignment is None:
            return MyWorkProfileRead()
        shift = (
            await self._shift(company_id, assignment.shift_id, today)
            if assignment.shift_id
            else None
        )
        location = (
            await self._location(company_id, assignment.branch_id, assignment.work_location_type)
            if assignment.branch_id
            else None
        )
        designation = (
            (
                await self._session.execute(
                    select(Designation.name).where(
                        Designation.company_id == company_id,
                        Designation.id == assignment.designation_id,
                    )
                )
            ).scalar_one_or_none()
            if assignment.designation_id
            else None
        )
        department = (
            (
                await self._session.execute(
                    select(Department.name).where(
                        Department.company_id == company_id,
                        Department.id == assignment.department_id,
                    )
                )
            ).scalar_one_or_none()
            if assignment.department_id
            else None
        )
        return MyWorkProfileRead(
            shift=shift, work_location=location, designation=designation, department=department
        )

    async def _shift(self, company_id: UUID, shift_id: UUID, today: date) -> MyShiftRead | None:
        shift = (
            await self._session.execute(
                select(Shift).where(
                    Shift.company_id == company_id,
                    Shift.id == shift_id,
                    Shift.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if shift is None:
            return None
        version = (
            await self._session.execute(
                select(ShiftVersion).where(
                    ShiftVersion.company_id == company_id,
                    ShiftVersion.shift_id == shift_id,
                    ShiftVersion.status == "PUBLISHED",
                    ShiftVersion.deleted_at.is_(None),
                    ShiftVersion.effective_from <= today,
                    or_(ShiftVersion.effective_to.is_(None), ShiftVersion.effective_to >= today),
                )
            )
        ).scalar_one_or_none()
        if version is not None and version.start_time and version.end_time:
            return MyShiftRead(
                name=shift.name,
                start_time=version.start_time,
                end_time=version.end_time,
                timezone=version.timezone,
            )
        # SPLIT/flexible versions have no single start/end; name only rather than a guess.
        return MyShiftRead(name=shift.name)

    async def _location(
        self, company_id: UUID, branch_id: UUID, work_location_type: str | None
    ) -> MyWorkLocationRead | None:
        branch = (
            await self._session.execute(
                select(Branch).where(
                    Branch.company_id == company_id,
                    Branch.id == branch_id,
                    Branch.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if branch is None:
            return None
        return MyWorkLocationRead(
            name=branch.name,
            city=branch.city,
            address_line1=branch.address_line1,
            work_location_type=work_location_type,
        )


def get_my_work_profile_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> MyWorkProfileService:
    return MyWorkProfileService(session)

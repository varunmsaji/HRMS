"""A live "what is still left to set up" checklist for administrators.

Separate from `company_setup_progress` on purpose: that records whether registration finished
(`onboarded_at`, status COMPLETE) and stays true once set. This answers a different question:
whether the rules the company will actually run on exist yet. It is worked out on every request
from the real data and never stored."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.organisation.repository import (
    OrganisationRepository,
    PolicyAssignmentRepository,
    ShiftVersionRepository,
)


class SetupChecklistItem(BaseModel):
    code: str
    label: str
    description: str
    required: bool
    is_complete: bool
    # Where in the app to finish it. The mobile app mirrors these paths.
    path: str


class SetupChecklistRead(BaseModel):
    items: list[SetupChecklistItem]
    required_total: int
    required_complete: int
    # The first required step still open, else the first optional one, else null.
    next_code: str | None


class SetupChecklistService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._assignments = PolicyAssignmentRepository()

    async def _company_wide(self, company_id: UUID, policy_kind: str) -> list:
        return await self._assignments.list_assignments(
            self._session,
            company_id=company_id,
            policy_kind=policy_kind,
            scope_type="COMPANY",
            current_only=True,
        )

    async def _company_policy_live(self, company_id: UUID, policy_kind: str) -> bool:
        """A company-wide assignment whose policy has published rules, not an empty shell."""
        from hrms.modules.attendance.service import AttendanceService
        from hrms.modules.leave.service import LeavePolicyService

        for assignment in await self._company_wide(company_id, policy_kind):
            if policy_kind == "LEAVE_POLICY":
                live = await LeavePolicyService(self._session).policy_is_published(
                    company_id, assignment.policy_id
                )
            else:
                live = await AttendanceService(self._session).policy_is_published(
                    company_id, policy_kind, assignment.policy_id
                )
            if live:
                return True
        return False

    async def get(self, company_id: UUID) -> SetupChecklistRead:
        shift_types = await ShiftVersionRepository().list_open_shift_types(
            self._session, company_id=company_id
        )
        branches = await OrganisationRepository().list_branches(
            self._session, company_id=company_id
        )
        has_calendar = bool(await self._company_wide(company_id, "WORK_CALENDAR"))

        items = [
            SetupChecklistItem(
                code="SHIFT",
                label="Create a shift",
                description="Working hours that days are judged against.",
                required=True,
                is_complete=bool(shift_types),
                path="/app/shifts",
            ),
            SetupChecklistItem(
                code="WORK_CALENDAR",
                label="Set working days and holidays",
                description="Which days are working days, weekly offs and holidays for everyone.",
                required=True,
                is_complete=has_calendar,
                path="/app/work-calendars/setup",
            ),
            SetupChecklistItem(
                code="ATTENDANCE_POLICY",
                label="Set attendance rules for the whole company",
                description="How punches become present, half-day or absent.",
                required=True,
                is_complete=await self._company_policy_live(company_id, "ATTENDANCE_POLICY"),
                path="/app/attendance-policies/new",
            ),
            SetupChecklistItem(
                code="REGULARIZATION_POLICY",
                label="Choose how attendance corrections are approved",
                description="Who can ask for a correction and who approves it.",
                required=False,
                is_complete=await self._company_policy_live(company_id, "REGULARIZATION_POLICY"),
                path="/app/regularization-policies/new",
            ),
            SetupChecklistItem(
                code="OVERTIME_POLICY",
                label="Set overtime rules",
                description="Who can earn overtime and who approves it. Skip if you do not pay it.",
                required=False,
                is_complete=await self._company_policy_live(company_id, "OVERTIME_POLICY"),
                path="/app/overtime-policies/new",
            ),
            SetupChecklistItem(
                code="LEAVE_POLICY",
                label="Set up leave",
                description="Leave types, and how each is earned and used.",
                required=False,
                is_complete=await self._company_policy_live(company_id, "LEAVE_POLICY"),
                path="/app/leave-types",
            ),
            SetupChecklistItem(
                code="BRANCH",
                label="Add your offices",
                description="Locations, and their map position if you check where people punch.",
                required=False,
                is_complete=any(branch.is_active for branch in branches),
                path="/app/branches",
            ),
        ]
        required = [item for item in items if item.required]
        open_items = [item for item in items if not item.is_complete]
        next_item = next((i for i in open_items if i.required), None) or next(
            iter(open_items), None
        )
        return SetupChecklistRead(
            items=items,
            required_total=len(required),
            required_complete=sum(1 for item in required if item.is_complete),
            next_code=next_item.code if next_item else None,
        )


def get_setup_checklist_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> SetupChecklistService:
    return SetupChecklistService(session)

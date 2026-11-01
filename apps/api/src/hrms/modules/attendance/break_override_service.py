"""Employee break overrides (break management V1).

An override is an effective-dated, audited layer over the employee's shift version — it never
edits a `shift_break`. Rows are not edited in place either: a change is `revoke` + a new row, so
the history of who changed what, when and why is complete. The caller must hold
`ATTENDANCE.ROSTER_MANAGE` with the employee inside their data scope, and nobody can override
their own breaks."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.break_repository import EmployeeBreakOverrideRepository
from hrms.modules.attendance.break_rules import resolve_breaks, validate_rule_set
from hrms.modules.attendance.break_schemas import (
    EmployeeBreakOverrideCreate,
    EmployeeBreakOverrideRead,
    override_to_read,
)
from hrms.modules.attendance.break_service import BreakEventService, override_to_data
from hrms.modules.attendance.models import EmployeeBreakOverride
from hrms.modules.attendance.service import (
    _ensure_date_open,
    _ensure_employee_visible,
    _ensure_shift_in_company,
)


def _time(value: str | None) -> Any:
    if value is None:
        return None
    hour, minute = value.split(":")
    from datetime import time

    return time(int(hour), int(minute))


class EmployeeBreakOverrideService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = EmployeeBreakOverrideRepository()
        self._audit = AuditService()

    async def create(
        self,
        company_id: UUID,
        body: EmployeeBreakOverrideCreate,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeBreakOverrideRead:
        await _ensure_employee_visible(
            self._session, company_id, body.employee_id, scope, caller_employee_id
        )
        if caller_employee_id is not None and caller_employee_id == body.employee_id:
            raise PermissionDeniedError("You cannot override your own breaks")
        await _ensure_shift_in_company(self._session, company_id, body.shift_id)
        await _ensure_date_open(
            self._session, company_id, body.effective_from, employee_id=body.employee_id
        )

        row_id = uuid4()
        now = datetime.now(UTC)
        data: dict[str, Any] = {
            "id": row_id,
            "company_id": company_id,
            "employee_id": body.employee_id,
            "shift_id": body.shift_id,
            "action": body.action,
            "target_break_name": body.target_break_name,
            "effective_from": body.effective_from,
            "effective_to": body.effective_to,
            "reason": body.reason,
            "name": body.name,
            "break_type": body.break_type,
            "break_kind": body.break_kind,
            "mode": body.mode,
            "start_time": _time(body.start_time),
            "end_time": _time(body.end_time),
            "window_start": _time(body.window_start),
            "window_end": _time(body.window_end),
            "min_minutes": body.min_minutes,
            "max_minutes": body.max_minutes,
            "scheduled_minutes": body.scheduled_minutes,
            "is_paid": body.is_paid,
            "is_mandatory": body.is_mandatory,
            "crosses_midnight": (
                body.break_kind == "FIXED_WINDOW"
                and body.start_time is not None
                and body.end_time is not None
                and body.end_time < body.start_time
            )
            or None,
            "excess_outcome": body.excess_outcome,
            "auto_deduct_full": body.auto_deduct_full,
            "optional_recorded_deducts": body.optional_recorded_deducts,
            "optional_scheduled_fallback": body.optional_scheduled_fallback,
            "sort_order": body.sort_order,
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        candidate = EmployeeBreakOverride(**data)
        await self._validate_against_shift(company_id, candidate)
        try:
            async with self._session.begin_nested():
                row = await self._repo.insert(self._session, data=data)
        except IntegrityError as exc:
            raise ConflictError(
                "An override for this break already covers part of that period. Revoke it first.",
                details=[
                    {
                        "field": "effective_from",
                        "code": "BREAK_OVERRIDE_OVERLAP",
                        "message": "overlapping override",
                    }
                ],
            ) from exc
        read = override_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BREAK_OVERRIDE_CREATED",
            entity_type="employee_break_override",
            entity_id=row.id,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _validate_against_shift(
        self, company_id: UUID, candidate: EmployeeBreakOverride
    ) -> None:
        """Resolves the employee's breaks on the override's first day with the candidate applied
        and refuses it if it targets nothing or leaves an invalid configuration."""
        from hrms.modules.organisation.service import OrganisationService

        events = BreakEventService(self._session)
        company = await OrganisationService(self._session).get_company_profile(company_id)
        schedule, shift_id = await events._schedule_for(
            company_id, candidate.employee_id, candidate.effective_from, company.timezone
        )
        if schedule.shift_inputs is None:
            raise ValidationError("The employee has no shift on the override's start date")
        if candidate.shift_id is not None and candidate.shift_id != shift_id:
            raise ValidationError("The employee is not on that shift on the override's start date")
        base = [b for b in schedule.shift_inputs.breaks if b.is_enabled]
        if candidate.action in ("REPLACE", "DISABLE"):
            wanted = (candidate.target_break_name or "").strip().lower()
            if not any(b.name.strip().lower() == wanted for b in base):
                raise ValidationError(
                    f"The employee's shift has no break named '{candidate.target_break_name}'"
                )
        resolved = resolve_breaks(
            base,
            [override_to_data(candidate)],
            target_date=candidate.effective_from,
            shift_id=shift_id,
        )
        if candidate.action == "ADD" and not any(
            b.override_id == candidate.id for b in resolved.breaks
        ):
            raise ValidationError(f"A break named '{candidate.name}' already exists")
        problem = validate_rule_set(resolved.breaks)
        if problem is not None:
            raise ValidationError(problem)

    async def list_for_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        include_revoked: bool,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> list[EmployeeBreakOverrideRead]:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        rows = await self._repo.list_for_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            include_revoked=include_revoked,
        )
        return [override_to_read(r) for r in rows]

    async def revoke(
        self,
        company_id: UUID,
        override_id: UUID,
        reason: str,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeBreakOverrideRead:
        row = await self._repo.get(self._session, company_id=company_id, override_id=override_id)
        if row is None:
            raise NotFoundError("Resource not found")
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        if caller_employee_id is not None and caller_employee_id == row.employee_id:
            raise PermissionDeniedError("You cannot change your own break overrides")
        if row.revoked_at is not None:
            raise ConflictError("This override has already been revoked")
        before = override_to_read(row).model_dump(mode="json")
        today: date = datetime.now(UTC).date()
        await _ensure_date_open(
            self._session, company_id, max(row.effective_from, today), employee_id=row.employee_id
        )
        await self._repo.revoke(
            self._session,
            row=row,
            revoked_by=actor_user_id,
            reason=reason,
            now=datetime.now(UTC),
        )
        read = override_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BREAK_OVERRIDE_REVOKED",
            entity_type="employee_break_override",
            entity_id=row.id,
            before=before,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

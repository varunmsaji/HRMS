"""Business logic for the Leave module — the public interface for other modules (Module
Standard). L1: leave-type identity CRUD + leave-policy identity/version CRUD with the same
draft/publish/discard lifecycle every other policy family in this codebase uses. L2: the
append-only leave ledger (ADR-0004) and balance computation. L3: the monthly accrual engine
(LEAVE_DECISION_LOG.md LD-06), invoked from `leave/tasks.py`. No application workflow (L4) or
comp-off redemption (L5) yet — see LEAVE_DECISION_LOG.md LD-09."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import NotFoundError
from hrms.core.rbac.types import DataScope
from hrms.modules.leave.exceptions import (
    LeavePolicyCodeAlreadyExistsError,
    LeavePolicyDraftAlreadyExistsError,
    LeavePolicyPublishIncompleteError,
    LeavePolicyVersionNotDraftError,
    LeavePolicyVersionOverlapError,
    LeavePolicyVersionPreviousVersionRequiredError,
    LeaveTypeCodeAlreadyExistsError,
    StaleLeaveResourceError,
)
from hrms.modules.leave.repository import (
    LeaveLedgerRepository,
    LeavePolicyRepository,
    LeaveTypeRepository,
)
from hrms.modules.leave.schemas import (
    LeaveBalanceRead,
    LeaveLedgerAdjustmentCreate,
    LeaveLedgerEntryRead,
    LeavePolicyCreate,
    LeavePolicyRead,
    LeavePolicyUpdate,
    LeavePolicyVersionCreate,
    LeavePolicyVersionPublishRequest,
    LeavePolicyVersionRead,
    LeavePolicyVersionUpdate,
    LeaveTypeCreate,
    LeaveTypeRead,
    LeaveTypeUpdate,
    build_leave_policy_update_values,
    build_leave_policy_version_update_values,
    build_leave_type_update_values,
    leave_ledger_entry_to_audit_dict,
    leave_ledger_entry_to_read,
    leave_policy_to_audit_dict,
    leave_policy_to_read,
    leave_policy_version_to_audit_dict,
    leave_policy_version_to_read,
    leave_type_to_audit_dict,
    leave_type_to_read,
)


class LeaveTypeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeaveTypeRepository()

    async def create(
        self,
        company_id: UUID,
        body: LeaveTypeCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveTypeRead:
        now = datetime.now(UTC)
        leave_type_id = uuid4()
        try:
            row = await self._repo.insert(
                self._session,
                data={
                    "id": leave_type_id,
                    "company_id": company_id,
                    "code": body.code,
                    "name": body.name,
                    "is_paid_default": body.is_paid_default,
                    "requires_balance": body.requires_balance,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise LeaveTypeCodeAlreadyExistsError() from exc

        read = leave_type_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_TYPE_CREATED",
            entity_type="leave_type",
            entity_id=leave_type_id,
            after=leave_type_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list(self, company_id: UUID) -> list[LeaveTypeRead]:
        rows = await self._repo.list(self._session, company_id=company_id)
        return [leave_type_to_read(r) for r in rows]

    async def get(self, company_id: UUID, leave_type_id: UUID) -> LeaveTypeRead:
        row = await self._repo.get(
            self._session, company_id=company_id, leave_type_id=leave_type_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return leave_type_to_read(row)

    async def update(
        self,
        company_id: UUID,
        leave_type_id: UUID,
        patch: LeaveTypeUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveTypeRead:
        row = await self._repo.get(
            self._session, company_id=company_id, leave_type_id=leave_type_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = leave_type_to_read(row)

        values = build_leave_type_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            result = await self._repo.update(
                self._session,
                company_id=company_id,
                leave_type_id=leave_type_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                latest = await self._repo.get(
                    self._session, company_id=company_id, leave_type_id=leave_type_id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                raise StaleLeaveResourceError(
                    "This leave type has been modified by another request",
                    current=leave_type_to_audit_dict(leave_type_to_read(latest)),
                )
            updated = result

        after_read = leave_type_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_TYPE_UPDATED",
            entity_type="leave_type",
            entity_id=leave_type_id,
            before=leave_type_to_audit_dict(before_read),
            after=leave_type_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read


class LeavePolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeavePolicyRepository()
        self._type_repo = LeaveTypeRepository()

    # -----------------------------------------------------------------
    # Leave Policy — identity
    # -----------------------------------------------------------------

    async def create_policy(
        self,
        company_id: UUID,
        body: LeavePolicyCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicyRead:
        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=body.leave_type_id
        )
        if leave_type is None:
            raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        policy_id = uuid4()
        try:
            row = await self._repo.insert_policy(
                self._session,
                data={
                    "id": policy_id,
                    "company_id": company_id,
                    "leave_type_id": body.leave_type_id,
                    "name": body.name,
                    "code": body.code,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise LeavePolicyCodeAlreadyExistsError() from exc

        read = leave_policy_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_POLICY_CREATED",
            entity_type="leave_policy",
            entity_id=policy_id,
            after=leave_policy_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_policies(self, company_id: UUID) -> list[LeavePolicyRead]:
        rows = await self._repo.list_policies(self._session, company_id=company_id)
        return [leave_policy_to_read(r) for r in rows]

    async def get_policy(self, company_id: UUID, policy_id: UUID) -> LeavePolicyRead:
        row = await self._repo.get_policy(self._session, company_id=company_id, policy_id=policy_id)
        if row is None:
            raise NotFoundError("Resource not found")
        return leave_policy_to_read(row)

    async def update_policy(
        self,
        company_id: UUID,
        policy_id: UUID,
        patch: LeavePolicyUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicyRead:
        row = await self._repo.get_policy(self._session, company_id=company_id, policy_id=policy_id)
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = leave_policy_to_read(row)

        values = build_leave_policy_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            try:
                result = await self._repo.update_policy(
                    self._session,
                    company_id=company_id,
                    policy_id=policy_id,
                    values=values,
                    expected_version=expected_version,
                    now=now,
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise LeavePolicyCodeAlreadyExistsError() from exc
            if result is None:
                latest = await self._repo.get_policy(
                    self._session, company_id=company_id, policy_id=policy_id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                raise StaleLeaveResourceError(
                    "This leave policy has been modified by another request",
                    current=leave_policy_to_audit_dict(leave_policy_to_read(latest)),
                )
            updated = result

        after_read = leave_policy_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_POLICY_UPDATED",
            entity_type="leave_policy",
            entity_id=policy_id,
            before=leave_policy_to_audit_dict(before_read),
            after=leave_policy_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    # -----------------------------------------------------------------
    # Leave Policy — versions
    # -----------------------------------------------------------------

    async def create_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        body: LeavePolicyVersionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicyVersionRead:
        policy = await self._repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        existing_draft = await self._repo.get_open_draft(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if existing_draft is not None:
            raise LeavePolicyDraftAlreadyExistsError()

        now = datetime.now(UTC)
        version_id = uuid4()
        row = await self._repo.insert_version(
            self._session,
            data={
                "id": version_id,
                "company_id": company_id,
                "policy_id": policy_id,
                "status": "DRAFT",
                "version": 1,
                "effective_from": body.effective_from,
                "effective_to": None,
                "allow_employee_request": body.allow_employee_request,
                "allow_manager_request_on_behalf": body.allow_manager_request_on_behalf,
                "allow_hr_request_on_behalf": body.allow_hr_request_on_behalf,
                "max_backdated_days": body.max_backdated_days,
                "max_requests_per_month": body.max_requests_per_month,
                "reason_required": body.reason_required,
                "attachment_required": body.attachment_required,
                "approval_chain": body.approval_chain,
                "half_day_allowed": body.half_day_allowed,
                "accrual_frequency": body.accrual_frequency,
                "accrual_rate_per_cycle": body.accrual_rate_per_cycle,
                "max_carry_forward_days": body.max_carry_forward_days,
                "encashment_allowed": body.encashment_allowed,
                "allow_negative_balance": body.allow_negative_balance,
                "sandwich_rule_enabled": body.sandwich_rule_enabled,
                "publish_reason": None,
                "published_at": None,
                "published_by": None,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
        )

        read = leave_policy_version_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_POLICY_VERSION_CREATED",
            entity_type="leave_policy_version",
            entity_id=version_id,
            after=leave_policy_version_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_versions(
        self, company_id: UUID, policy_id: UUID
    ) -> list[LeavePolicyVersionRead]:
        policy = await self._repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        versions = await self._repo.list_versions(
            self._session, company_id=company_id, policy_id=policy_id
        )
        return [leave_policy_version_to_read(v) for v in versions]

    async def _get_version_or_404(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> tuple[Any, LeavePolicyVersionRead]:
        version = await self._repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        return version, leave_policy_version_to_read(version)

    async def get_version(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> LeavePolicyVersionRead:
        _, read = await self._get_version_or_404(company_id, policy_id, version_id)
        return read

    async def update_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        patch: LeavePolicyVersionUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicyVersionRead:
        version, before_read = await self._get_version_or_404(company_id, policy_id, version_id)
        if version.status != "DRAFT":
            raise LeavePolicyVersionNotDraftError()

        values = build_leave_policy_version_update_values(patch)
        now = datetime.now(UTC)
        updated = version
        if values:
            result = await self._repo.update_version(
                self._session,
                company_id=company_id,
                policy_id=policy_id,
                version_id=version_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                _, latest_read = await self._get_version_or_404(company_id, policy_id, version_id)
                raise StaleLeaveResourceError(
                    "This leave policy version has been modified by another request",
                    current=leave_policy_version_to_audit_dict(latest_read),
                )
            updated = result

        after_read = leave_policy_version_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_POLICY_VERSION_UPDATED",
            entity_type="leave_policy_version",
            entity_id=version_id,
            before=leave_policy_version_to_audit_dict(before_read),
            after=leave_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def discard_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicyVersionRead:
        version, before_read = await self._get_version_or_404(company_id, policy_id, version_id)
        if version.status != "DRAFT":
            raise LeavePolicyVersionNotDraftError()

        now = datetime.now(UTC)
        result = await self._repo.discard_version(
            self._session,
            company_id=company_id,
            policy_id=policy_id,
            version_id=version_id,
            expected_version=expected_version,
            now=now,
        )
        if result is None:
            _, latest_read = await self._get_version_or_404(company_id, policy_id, version_id)
            raise StaleLeaveResourceError(
                "This leave policy version has been modified by another request",
                current=leave_policy_version_to_audit_dict(latest_read),
            )

        after_read = leave_policy_version_to_read(result)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_POLICY_VERSION_DISCARDED",
            entity_type="leave_policy_version",
            entity_id=version_id,
            before=leave_policy_version_to_audit_dict(before_read),
            after=leave_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def publish_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        body: LeavePolicyVersionPublishRequest,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicyVersionRead:
        """Insert-new/close-previous — mirrors `publish_attendance_policy_version` exactly (two
        concurrency tokens: the draft's own `If-Match`, and `expected_previous_version` for the
        currently open published row, required only when one exists)."""
        draft = await self._repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if draft is None:
            raise NotFoundError("Resource not found")
        if draft.status != "DRAFT":
            raise LeavePolicyVersionNotDraftError()
        if draft.effective_from is None:
            raise LeavePolicyPublishIncompleteError("effective_from is required to publish")

        before_read = leave_policy_version_to_read(draft)

        current = await self._repo.get_current_published(
            self._session, company_id=company_id, policy_id=policy_id
        )
        now = datetime.now(UTC)
        if current is not None:
            assert current.effective_from is not None
            if draft.effective_from <= current.effective_from:
                raise LeavePolicyPublishIncompleteError(
                    "effective_from must be after the currently published version's effective_from"
                )
            if body.expected_previous_version is None:
                raise LeavePolicyVersionPreviousVersionRequiredError()
            closed = await self._repo.close_version(
                self._session,
                company_id=company_id,
                version_id=current.id,
                effective_to=draft.effective_from - timedelta(days=1),
                expected_version=body.expected_previous_version,
                now=now,
            )
            if closed is None:
                raise StaleLeaveResourceError(
                    "The currently published leave policy version has been modified by another "
                    "request",
                    current={},
                )

        try:
            updated = await self._repo.update_version(
                self._session,
                company_id=company_id,
                policy_id=policy_id,
                version_id=version_id,
                values={
                    "status": "PUBLISHED",
                    "publish_reason": body.publish_reason,
                    "published_at": now,
                    "published_by": actor_user_id,
                },
                expected_version=expected_version,
                now=now,
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise LeavePolicyVersionOverlapError() from exc

        if updated is None:
            _, latest_read = await self._get_version_or_404(company_id, policy_id, version_id)
            raise StaleLeaveResourceError(
                "This leave policy version has been modified by another request",
                current=leave_policy_version_to_audit_dict(latest_read),
            )

        after_read = leave_policy_version_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_POLICY_VERSION_PUBLISHED",
            entity_type="leave_policy_version",
            entity_id=version_id,
            before=leave_policy_version_to_audit_dict(before_read),
            after=leave_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def resolve_version_as_of(
        self, company_id: UUID, policy_id: UUID, as_of: date
    ) -> LeavePolicyVersionRead:
        policy = await self._repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        version = await self._repo.find_effective_as_of(
            self._session, company_id=company_id, policy_id=policy_id, as_of=as_of
        )
        if version is None:
            raise NotFoundError("Resource not found")
        return leave_policy_version_to_read(version)

    async def policy_exists(self, company_id: UUID, policy_kind: str, policy_id: UUID) -> bool:
        """Mirrors `AttendanceService.policy_exists` — the one place `organisation` needs to
        validate a polymorphic `PolicyAssignment.policy_id` against a Leave-owned identity
        (LD-04)."""
        if policy_kind != "LEAVE_POLICY":
            return False
        row = await self._repo.get_policy(self._session, company_id=company_id, policy_id=policy_id)
        return row is not None


class LeaveLedgerService:
    """L2 — the append-only balance ledger (ADR-0004/DEC-004: balance is always `SUM(amount)`
    over `leave_ledger`, never a stored counter). Employee-visibility narrowing follows the
    established cross-module seam (`EmployeeService.resolve_visible_employee_ids`, documented at
    `employee/service.py` as "the exact seam a future Attendance/Leave/Payroll module would
    call") rather than re-deriving reporting-hierarchy logic here — same pattern
    `attendance.service`'s `_resolve_visible_employee_ids` wraps, called directly via local
    import per this codebase's established cross-module-seam convention (not duplicated, unlike
    the approval-chain logic in LD-05 — that was genuinely domain business logic each module
    reimplements; visibility resolution is shared infrastructure every module already reuses the
    same way)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeaveLedgerRepository()
        self._type_repo = LeaveTypeRepository()

    async def _resolve_visible_employee_ids(
        self, company_id: UUID, scope: DataScope, caller_employee_id: UUID | None
    ) -> frozenset[UUID] | None:
        from hrms.modules.employee.service import EmployeeService

        return await EmployeeService(self._session).resolve_visible_employee_ids(
            company_id, scope, caller_employee_id
        )

    async def _ensure_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> None:
        visible_ids = await self._resolve_visible_employee_ids(
            company_id, scope, caller_employee_id
        )
        if visible_ids is not None and employee_id not in visible_ids:
            raise NotFoundError("Resource not found")

    async def create_adjustment(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: LeaveLedgerAdjustmentCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveLedgerEntryRead:
        """No `scope` narrowing here — deliberately. `LEAVE.BALANCE_ADJUST` is a COMPANY-scoped
        HR-admin action (mirrors `ATTENDANCE.POLICY_MANAGE`'s posture: the permission grant
        itself is the gate, not a per-employee visibility check), not a SELF/REPORTEES-scoped
        read. The target employee still must exist in this company — enforced via the
        `employee_id` FK at insert time (a nonexistent id raises `IntegrityError`, surfaced as a
        plain 500 today; a dedicated `EmployeeNotFoundError` translation is a reasonable follow-
        up but not required for L2's scope)."""
        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=body.leave_type_id
        )
        if leave_type is None:
            raise NotFoundError("Resource not found")

        entry_id = uuid4()
        row = await self._repo.insert(
            self._session,
            data={
                "id": entry_id,
                "company_id": company_id,
                "employee_id": employee_id,
                "leave_type_id": body.leave_type_id,
                "entry_type": "ADJUSTMENT",
                "amount": body.amount,
                "effective_date": body.effective_date,
                "reference_id": None,
                "reason": body.reason,
                "created_by_user_id": actor_user_id,
            },
        )

        read = leave_ledger_entry_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_LEDGER_ADJUSTMENT_CREATED",
            entity_type="leave_ledger",
            entity_id=entry_id,
            after=leave_ledger_entry_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_entries(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        leave_type_id: UUID | None,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> list[LeaveLedgerEntryRead]:
        await self._ensure_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        rows = await self._repo.list_for_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
        )
        return [leave_ledger_entry_to_read(r) for r in rows]

    async def get_balances(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> list[LeaveBalanceRead]:
        await self._ensure_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        rows = await self._repo.get_balances(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [
            LeaveBalanceRead(
                employee_id=employee_id,
                leave_type_id=r.leave_type_id,
                leave_type_code=r.leave_type_code,
                leave_type_name=r.leave_type_name,
                balance=r.balance,
            )
            for r in rows
        ]


def _previous_month_bounds(as_of: date) -> tuple[date, date]:
    """The calendar month immediately before `as_of` — e.g. `as_of=2026-09-01` gives
    `(2026-08-01, 2026-08-31)`. Standard "accrual runs after month-end, for the month that just
    ended" HR practice; not itself a client-given rule, just the obvious reading of "monthly
    cron" (`docs/architecture/04_Background_Job_Architecture.md` §5)."""
    first_of_this_month = as_of.replace(day=1)
    period_end = first_of_this_month - timedelta(days=1)
    period_start = period_end.replace(day=1)
    return period_start, period_end


def _prorate_accrual(
    rate: Decimal, period_start: date, period_end: date, worked_start: date, worked_end: date
) -> Decimal:
    total_days = (period_end - period_start).days + 1
    worked_days = (worked_end - worked_start).days + 1
    if worked_days >= total_days:
        return rate.quantize(Decimal("0.01"))
    prorated = (rate * worked_days) / total_days
    return prorated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class LeaveAccrualService:
    """L3 — the monthly accrual engine (LEAVE_DECISION_LOG.md LD-06). Invoked by the
    `leave.accrue_company` Celery task (`leave/tasks.py`), never from an HTTP route — this is
    background-job business logic, not a request-scoped one, so it takes no `DataScope`/caller
    and writes system-generated ledger rows (`created_by_user_id=None`).

    **Scope of this slice:** only `accrual_frequency == "MONTHLY"` policies accrue. `YEARLY`
    policies are resolved but skipped — LD-06 answered the client's rate/cap/encashment/
    negative-balance/sandwich-rule questions, not a yearly cadence's anchor date (fiscal-year
    start vs. joining-date anniversary), so nothing is guessed here (WD-21 fail-closed
    precedent). Carry-forward cap enforcement (`max_carry_forward_days`) is likewise out of
    scope — that's a year-end sweep, not a monthly accrual concern, and has no anchor to trigger
    from yet either. Both are natural follow-up slices once a fiscal-year anchor is decided."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ledger_repo = LeaveLedgerRepository()
        self._type_repo = LeaveTypeRepository()
        self._policy_repo = LeavePolicyRepository()

    async def run_for_company(self, company_id: UUID, *, as_of: date) -> int:
        """Accrue for the calendar month before `as_of`, for every employee whose employment
        span overlaps it and every active, balance-backed leave type that resolves to a
        `MONTHLY` published policy for them. Idempotent — safe to call more than once for the
        same `as_of` (a re-run, a retried task): already-written cycles are skipped via
        `LeaveLedgerRepository.exists_for_cycle`, never double-inserted (ADR-0004: corrections
        are new rows, but duplicates are not corrections)."""
        period_start, period_end = _previous_month_bounds(as_of)

        from hrms.modules.employee.service import EmploymentService
        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

        spans = await EmploymentService(self._session).list_spans_overlapping(
            company_id, date_from=period_start, date_to=period_end
        )
        if not spans:
            return 0

        leave_types = await self._type_repo.list(self._session, company_id=company_id)
        accrual_types = [t for t in leave_types if t.is_active and t.requires_balance]
        if not accrual_types:
            return 0

        resolver = CalendarResolutionService(self._session)
        written = 0
        for employee_id, joining_date, last_working_day in spans:
            worked_start = max(period_start, joining_date)
            worked_end = min(period_end, last_working_day or period_end)
            if worked_start > worked_end:
                continue

            for leave_type in accrual_types:
                found = await resolver.resolve_policy_assignment(
                    company_id,
                    "LEAVE_POLICY",
                    employee_id=employee_id,
                    target_date=period_end,
                    leave_type_id=leave_type.id,
                )
                if found is None:
                    continue
                assignment, _scope_type = found

                version = await self._policy_repo.find_effective_as_of(
                    self._session,
                    company_id=company_id,
                    policy_id=assignment.policy_id,
                    as_of=period_end,
                )
                if version is None or version.accrual_frequency != "MONTHLY":
                    continue
                if not version.accrual_rate_per_cycle or version.accrual_rate_per_cycle <= 0:
                    continue

                already_written = await self._ledger_repo.exists_for_cycle(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    leave_type_id=leave_type.id,
                    entry_type="ACCRUAL",
                    effective_date=period_end,
                )
                if already_written:
                    continue

                amount = _prorate_accrual(
                    version.accrual_rate_per_cycle,
                    period_start,
                    period_end,
                    worked_start,
                    worked_end,
                )
                if amount <= 0:
                    continue

                await self._ledger_repo.insert(
                    self._session,
                    data={
                        "id": uuid4(),
                        "company_id": company_id,
                        "employee_id": employee_id,
                        "leave_type_id": leave_type.id,
                        "entry_type": "ACCRUAL",
                        "amount": amount,
                        "effective_date": period_end,
                        "reference_id": version.id,
                        "reason": f"Monthly accrual for {period_start:%B %Y}",
                        "created_by_user_id": None,
                    },
                )
                written += 1
        return written

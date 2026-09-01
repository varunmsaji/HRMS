"""Business logic for the Leave module — the public interface for other modules (Module
Standard). L1: leave-type identity CRUD + leave-policy identity/version CRUD with the same
draft/publish/discard lifecycle every other policy family in this codebase uses. L2: the
append-only leave ledger (ADR-0004) and balance computation. L3: the monthly accrual engine
(LEAVE_DECISION_LOG.md LD-06), invoked from `leave/tasks.py`. L4: application submission +
approval workflow (LD-02/LD-05/LD-12/LD-13). No comp-off redemption (L5) yet — see
LEAVE_DECISION_LOG.md LD-09."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import NotFoundError, PermissionDeniedError
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.leave.exceptions import (
    LeaveApplicationApproverMismatchError,
    LeaveApplicationAttachmentRequiredError,
    LeaveApplicationCalendarNotResolvedError,
    LeaveApplicationDateRangeInvalidError,
    LeaveApplicationHalfDayNotAllowedError,
    LeaveApplicationInsufficientBalanceError,
    LeaveApplicationInvalidTransitionError,
    LeaveApplicationLimitExceededError,
    LeaveApplicationNotFoundError,
    LeaveApplicationNotPermittedError,
    LeaveApplicationPolicyNotResolvedError,
    LeaveApplicationReasonRequiredError,
    LeaveApplicationSelfApprovalNotAllowedError,
    LeaveApplicationWindowExceededError,
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
    LeaveApplicationActionRepository,
    LeaveApplicationDayRepository,
    LeaveApplicationRepository,
    LeaveLedgerRepository,
    LeavePolicyRepository,
    LeaveTypeRepository,
)
from hrms.modules.leave.schemas import (
    LeaveApplicationCreate,
    LeaveApplicationRead,
    LeaveApplicationReviewInput,
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
    leave_application_to_audit_dict,
    leave_application_to_read,
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


class LeaveApplicationService:
    """L4 — submission + approval workflow (LEAVE_DECISION_LOG.md LD-02/LD-05/LD-12/LD-13).
    Mirrors `AttendanceRegularizationRequestService`'s state machine and approval-chain
    resolution (LD-05: mirrored, not shared code) — `submit`/`_get_reviewable`/`_approve_internal`
    below map directly onto that service's `submit`/`_get_reviewable`/`_approve_internal`. Two
    pieces have no Regularization precedent: the sandwich-rule day-breakdown computation (no
    balance/downstream projection exists in Regularization) and post-approval cancellation
    reversal (LD-13 — Regularization's `cancel` only permits cancelling a still-`SUBMITTED`
    request)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeaveApplicationRepository()
        self._day_repo = LeaveApplicationDayRepository()
        self._action_repo = LeaveApplicationActionRepository()
        self._type_repo = LeaveTypeRepository()
        self._policy_repo = LeavePolicyRepository()
        self._ledger_repo = LeaveLedgerRepository()

    # -----------------------------------------------------------------
    # Shared helpers
    # -----------------------------------------------------------------

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

    async def _record_action(
        self,
        *,
        company_id: UUID,
        leave_application_id: UUID,
        action: str,
        actor_user_id: UUID | None,
        actor_employee_id: UUID | None,
        stage: str | None,
        comment: str | None,
    ) -> None:
        await self._action_repo.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "leave_application_id": leave_application_id,
                "action": action,
                "actor_user_id": actor_user_id,
                "actor_employee_id": actor_employee_id,
                "stage": stage,
                "comment": comment,
            },
        )

    async def _read(self, row: Any, *, company_id: UUID) -> LeaveApplicationRead:
        days = await self._day_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=row.id
        )
        actions = await self._action_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=row.id
        )
        return leave_application_to_read(row, days=days, actions=actions)

    async def _stale_error(
        self, company_id: UUID, application_id: UUID
    ) -> LeaveApplicationNotFoundError | StaleLeaveResourceError:
        current = await self._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if current is None:
            return LeaveApplicationNotFoundError()
        current_read = await self._read(current, company_id=company_id)
        return StaleLeaveResourceError(
            "This application has been modified by another request",
            current=leave_application_to_audit_dict(current_read),
        )

    # -----------------------------------------------------------------
    # Submit
    # -----------------------------------------------------------------

    async def _compute_day_breakdown(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: LeaveApplicationCreate,
        sandwich_rule_enabled: bool,
    ) -> list[dict[str, Any]]:
        """Per-day fractions for the application's date range, honoring LD-06's sandwich rule.
        Fails closed (`LeaveApplicationCalendarNotResolvedError`) if any date's `WorkCalendar`
        doesn't resolve — never silently assumes WORKING (mirrors
        `CalendarResolutionService.resolve_for_employee`'s own `config_incomplete` posture).

        WORKING/SPECIAL_WORKING days are leave-consuming by default; WEEKLY_OFF/HOLIDAY/SHUTDOWN
        are not, unless the sandwich rule brackets one between two consuming days *within this
        same application's range* (no cross-application look-back — a separate, earlier
        application on an adjacent date is not consulted here)."""
        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

        resolver = CalendarResolutionService(self._session)
        span_days = (body.end_date - body.start_date).days + 1
        dates = [body.start_date + timedelta(days=i) for i in range(span_days)]

        day_types: dict[date, str] = {}
        for one_date in dates:
            resolved = await resolver.resolve_for_employee(company_id, employee_id, one_date)
            if resolved.config_incomplete or resolved.day_type is None:
                raise LeaveApplicationCalendarNotResolvedError()
            day_types[one_date] = resolved.day_type.day_type

        consuming: dict[date, bool] = {
            d: day_types[d] in ("WORKING", "SPECIAL_WORKING") for d in dates
        }

        if sandwich_rule_enabled:
            for i in range(1, len(dates) - 1):
                d = dates[i]
                if consuming[d]:
                    continue
                if consuming[dates[i - 1]] and consuming[dates[i + 1]]:
                    consuming[d] = True

        breakdown: list[dict[str, Any]] = []
        for d in dates:
            if not consuming[d]:
                continue
            is_sandwich = day_types[d] not in ("WORKING", "SPECIAL_WORKING")
            fraction = Decimal("1.00")
            half = None
            if body.half_day is not None and d == body.start_date and d == body.end_date:
                fraction = Decimal("0.50")
                half = body.half_day
            breakdown.append(
                {
                    "date": d,
                    "fraction": fraction,
                    "half": half,
                    "is_sandwich_generated": is_sandwich,
                }
            )

        if not breakdown:
            raise LeaveApplicationDateRangeInvalidError(
                "This date range has no leave-consuming days"
            )
        return breakdown

    async def submit(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: LeaveApplicationCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        on_behalf: bool,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveApplicationRead:
        """Mirrors `AttendanceRegularizationRequestService.submit`'s exact validation order and
        approval-chain resolution (LD-05). No future-date restriction — unlike Regularization,
        a leave application is normally forward-dated (planned leave), so `start_date` in the
        future is the expected case, not an error."""
        await self._ensure_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=body.leave_type_id
        )
        if leave_type is None:
            raise NotFoundError("Resource not found")

        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

        resolver = CalendarResolutionService(self._session)
        found = await resolver.resolve_policy_assignment(
            company_id,
            "LEAVE_POLICY",
            employee_id=employee_id,
            target_date=body.start_date,
            leave_type_id=body.leave_type_id,
        )
        if found is None:
            raise LeaveApplicationPolicyNotResolvedError()
        assignment, _scope_type = found

        policy_version = await self._policy_repo.find_effective_as_of(
            self._session,
            company_id=company_id,
            policy_id=assignment.policy_id,
            as_of=body.start_date,
        )
        if policy_version is None:
            raise LeaveApplicationPolicyNotResolvedError()

        if on_behalf:
            if not (
                policy_version.allow_manager_request_on_behalf
                or policy_version.allow_hr_request_on_behalf
            ):
                raise LeaveApplicationNotPermittedError(
                    "The applicable policy does not allow on-behalf requests"
                )
        elif not policy_version.allow_employee_request:
            raise LeaveApplicationNotPermittedError(
                "The applicable policy does not allow employee self-service requests"
            )

        if body.half_day is not None and not policy_version.half_day_allowed:
            raise LeaveApplicationHalfDayNotAllowedError()

        if policy_version.max_backdated_days is not None:
            backdated_days = (date.today() - body.start_date).days
            if backdated_days > policy_version.max_backdated_days:
                raise LeaveApplicationWindowExceededError()

        if policy_version.reason_required and not body.reason:
            raise LeaveApplicationReasonRequiredError()
        if policy_version.attachment_required and not body.attachment_reference:
            raise LeaveApplicationAttachmentRequiredError()

        now = datetime.now(UTC)
        if policy_version.max_requests_per_month is not None:
            month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
            count = await self._repo.count_since(
                self._session, company_id=company_id, employee_id=employee_id, since=month_start
            )
            if count >= policy_version.max_requests_per_month:
                raise LeaveApplicationLimitExceededError()

        day_breakdown = await self._compute_day_breakdown(
            company_id, employee_id, body, policy_version.sandwich_rule_enabled
        )
        total_days = sum((d["fraction"] for d in day_breakdown), Decimal("0.00"))

        if leave_type.requires_balance:
            balances = await self._ledger_repo.get_balances(
                self._session, company_id=company_id, employee_id=employee_id
            )
            current_balance = next(
                (b.balance for b in balances if b.leave_type_id == leave_type.id), Decimal("0.00")
            )
            # LD-06: never negative — hard-capped at current balance, no exceptions.
            if current_balance < total_days:
                raise LeaveApplicationInsufficientBalanceError()

        approval_chain = policy_version.approval_chain
        resolved_manager_id: UUID | None = None
        approval_stage: str | None
        if approval_chain == "AUTO":
            approval_stage = None
        elif approval_chain == "HR":
            approval_stage = "HR"
        else:  # MANAGER or MANAGER_THEN_HR
            from hrms.modules.employee.service import EmployeeAssignmentService

            assignment_service = EmployeeAssignmentService(self._session)
            employee_assignment = await assignment_service.get_assignment_as_of(
                company_id, employee_id, body.start_date
            )
            resolved_manager_id = (
                employee_assignment.reporting_manager_id if employee_assignment else None
            )
            # Mirrors Regularization/Overtime: resolution failure routes to HR, audited, never
            # auto-approved on failure.
            approval_stage = "MANAGER" if resolved_manager_id is not None else "HR"

        application_id = uuid4()
        data = {
            "id": application_id,
            "company_id": company_id,
            "employee_id": employee_id,
            "leave_type_id": body.leave_type_id,
            "leave_policy_version_id": policy_version.id,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "total_days": total_days,
            "reason": body.reason,
            "attachment_reference": body.attachment_reference,
            "status": "SUBMITTED",
            "approval_chain": approval_chain,
            "approval_stage": approval_stage,
            "resolved_approver_manager_id": resolved_manager_id,
            "submitted_by_user_id": actor_user_id,
            "submitted_at": now,
        }
        row = await self._repo.insert(self._session, data=data)

        await self._day_repo.insert_many(
            self._session,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "leave_application_id": application_id,
                    "calendar_date": d["date"],
                    "fraction": d["fraction"],
                    "half": d["half"],
                    "is_sandwich_generated": d["is_sandwich_generated"],
                }
                for d in day_breakdown
            ],
        )

        await self._record_action(
            company_id=company_id,
            leave_application_id=application_id,
            action="SUBMITTED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=None,
            comment=body.reason,
        )
        if approval_chain in ("MANAGER", "MANAGER_THEN_HR") and resolved_manager_id is None:
            await self._record_action(
                company_id=company_id,
                leave_application_id=application_id,
                action="APPROVER_UNRESOLVED",
                actor_user_id=None,
                actor_employee_id=None,
                stage="MANAGER",
                comment="No manager resolved as of the start date; routed to HR",
            )

        read = await self._read(row, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_APPLICATION_SUBMITTED",
            entity_type="leave_application",
            entity_id=application_id,
            after=leave_application_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )

        if approval_chain == "AUTO":
            read = await self._approve_internal(
                company_id,
                row,
                actor_user_id=actor_user_id,
                actor_employee_id=caller_employee_id,
                reviewer_comment="Auto-approved per policy (approval_chain=AUTO)",
                expected_version=row.version,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return read

    # -----------------------------------------------------------------
    # Approve / reject
    # -----------------------------------------------------------------

    async def _get_reviewable(
        self,
        company_id: UUID,
        application_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> Any:
        row = await self._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if row is None:
            raise LeaveApplicationNotFoundError()
        if row.status != "SUBMITTED" or row.approval_stage is None:
            raise LeaveApplicationInvalidTransitionError()
        # Self-approval is always blocked, no policy escape hatch — mirrors WD-28 decision 5.
        if caller_employee_id is not None and row.employee_id == caller_employee_id:
            raise LeaveApplicationSelfApprovalNotAllowedError()

        if row.approval_stage == "MANAGER":
            if caller_employee_id is None or caller_employee_id != row.resolved_approver_manager_id:
                raise LeaveApplicationApproverMismatchError()
        else:  # HR
            if DataScopeLevel.COMPANY not in scope.levels:
                raise LeaveApplicationApproverMismatchError(
                    "HR-stage approval requires a company-wide LEAVE.APPLICATION_APPROVE grant"
                )
        return row

    async def approve(
        self,
        company_id: UUID,
        application_id: UUID,
        body: LeaveApplicationReviewInput,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveApplicationRead:
        row = await self._get_reviewable(
            company_id, application_id, scope=scope, caller_employee_id=caller_employee_id
        )
        return await self._approve_internal(
            company_id,
            row,
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            reviewer_comment=body.reviewer_comment,
            expected_version=expected_version,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def reject(
        self,
        company_id: UUID,
        application_id: UUID,
        body: LeaveApplicationReviewInput,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveApplicationRead:
        row = await self._get_reviewable(
            company_id, application_id, scope=scope, caller_employee_id=caller_employee_id
        )
        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            application_id=application_id,
            values={
                "status": "REJECTED",
                "approval_stage": None,
                "reviewed_by_user_id": actor_user_id,
                "reviewed_at": now,
                "reviewer_comment": body.reviewer_comment,
                "rejection_reason": body.rejection_reason,
            },
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, application_id)

        await self._record_action(
            company_id=company_id,
            leave_application_id=application_id,
            action="REJECTED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=row.approval_stage,
            comment=body.rejection_reason or body.reviewer_comment,
        )
        read = await self._read(updated, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_APPLICATION_REJECTED",
            entity_type="leave_application",
            entity_id=application_id,
            before=leave_application_to_audit_dict(await self._read(row, company_id=company_id)),
            after=leave_application_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _approve_internal(
        self,
        company_id: UUID,
        row: Any,
        *,
        actor_user_id: UUID | None,
        actor_employee_id: UUID | None,
        reviewer_comment: str | None,
        expected_version: int,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LeaveApplicationRead:
        now = datetime.now(UTC)
        is_final_stage = not (
            row.approval_chain == "MANAGER_THEN_HR" and row.approval_stage == "MANAGER"
        )
        values: dict[str, Any] = (
            {
                "status": "APPROVED",
                "approval_stage": None,
                "reviewed_by_user_id": actor_user_id,
                "reviewed_at": now,
                "reviewer_comment": reviewer_comment,
            }
            if is_final_stage
            else {"approval_stage": "HR"}
        )

        before_read = await self._read(row, company_id=company_id)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            application_id=row.id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, row.id)

        if not is_final_stage:
            await self._record_action(
                company_id=company_id,
                leave_application_id=row.id,
                action="STAGE_APPROVED",
                actor_user_id=actor_user_id,
                actor_employee_id=actor_employee_id,
                stage="MANAGER",
                comment=reviewer_comment,
            )
            read = await self._read(updated, company_id=company_id)
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="LEAVE_APPLICATION_STAGE_APPROVED",
                entity_type="leave_application",
                entity_id=row.id,
                before=leave_application_to_audit_dict(before_read),
                after=leave_application_to_audit_dict(read),
                ip=ip_address,
                user_agent=user_agent,
            )
            return read

        await self._record_action(
            company_id=company_id,
            leave_application_id=row.id,
            action="APPROVED",
            actor_user_id=actor_user_id,
            actor_employee_id=actor_employee_id,
            stage=row.approval_stage,
            comment=reviewer_comment,
        )
        approved_read = await self._read(updated, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_APPLICATION_APPROVED",
            entity_type="leave_application",
            entity_id=row.id,
            before=leave_application_to_audit_dict(before_read),
            after=leave_application_to_audit_dict(approved_read),
            ip=ip_address,
            user_agent=user_agent,
        )

        return await self._apply_approval(
            company_id,
            updated,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _apply_approval(
        self,
        company_id: UUID,
        row: Any,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LeaveApplicationRead:
        """LD-12: runs inside the same transaction as the approval write that preceded it — if
        `LeaveProjectionService.sync()` refuses any single day (its attendance period is
        already closed), the whole transaction (including the `status='APPROVED'` write) rolls
        back with the exception, mirroring
        `AttendanceRegularizationRequestService._apply_correction`'s exact posture. Never a
        partially-approved, partially-synced application."""
        from hrms.modules.attendance.schemas import LeaveProjectionSync
        from hrms.modules.attendance.service import LeaveProjectionService

        # `leave_application_day.half` uses this module's own FIRST_HALF/SECOND_HALF vocabulary
        # (LeaveApplicationCreate's `_HALF_DAY_VALUES`); `LeaveProjectionSync.half` uses
        # Attendance's own FIRST/SECOND vocabulary — translated at the boundary, not unified,
        # since each module owns its own field shape (LD-05's mirrored-not-shared posture).
        half_to_projection_half = {"FIRST_HALF": "FIRST", "SECOND_HALF": "SECOND"}

        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=row.leave_type_id
        )
        days = await self._day_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=row.id
        )
        # LEAVE.APPLICATION_APPROVE already gated this action — this cross-module call is not
        # re-deriving Attendance's own RBAC, just satisfying `sync()`'s required scope param
        # (mirrors L2's `create_adjustment` "the permission grant itself is the gate" posture).
        full_scope = DataScope(levels=frozenset({DataScopeLevel.COMPANY}))
        projection_service = LeaveProjectionService(self._session)

        for day in days:
            synced = await projection_service.sync(
                company_id,
                LeaveProjectionSync(
                    employee_id=row.employee_id,
                    attendance_date=day.calendar_date,
                    leave_application_id=row.id,
                    leave_type_id=row.leave_type_id,
                    leave_type_code=leave_type.code if leave_type is not None else None,
                    fraction=str(day.fraction),
                    half=half_to_projection_half.get(day.half) if day.half else None,
                    is_paid=leave_type.is_paid_default if leave_type is not None else True,
                ),
                scope=full_scope,
                caller_employee_id=None,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await self._day_repo.set_projection_id(
                self._session,
                company_id=company_id,
                day_id=day.id,
                leave_day_projection_id=synced.id,
                now=datetime.now(UTC),
            )

        # The actual balance deduction — skipped entirely for a LOP-style type (LD-02).
        if leave_type is not None and leave_type.requires_balance:
            await self._ledger_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": row.employee_id,
                    "leave_type_id": row.leave_type_id,
                    "entry_type": "APPLICATION",
                    "amount": -row.total_days,
                    "effective_date": row.start_date,
                    "reference_id": row.id,
                    "reason": f"Leave application {row.start_date} to {row.end_date}",
                    "created_by_user_id": actor_user_id,
                },
            )

        return await self._read(row, company_id=company_id)

    # -----------------------------------------------------------------
    # Cancel
    # -----------------------------------------------------------------

    async def cancel(
        self,
        company_id: UUID,
        application_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveApplicationRead:
        """`SUBMITTED` (pre-approval) mirrors `AttendanceRegularizationRequestService.cancel`
        exactly — only the original submitter, no side effects. `APPROVED` (post-approval) is
        new territory (LD-13, no Regularization precedent): same submitter-only rule, but also
        reverses the ledger debit and every synced `LeaveDayProjection`."""
        row = await self._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if row is None:
            raise LeaveApplicationNotFoundError()
        await self._ensure_employee_visible(
            company_id, row.employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        if row.submitted_by_user_id != actor_user_id:
            raise PermissionDeniedError("Only the original submitter may cancel this application")
        if row.status not in ("SUBMITTED", "APPROVED"):
            raise LeaveApplicationInvalidTransitionError()

        was_approved = row.status == "APPROVED"
        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            application_id=application_id,
            values={
                "status": "CANCELLED",
                "approval_stage": None,
                "cancelled_at": now,
                "cancelled_by_user_id": actor_user_id,
            },
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, application_id)

        await self._record_action(
            company_id=company_id,
            leave_application_id=application_id,
            action="CANCELLED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=None,
            comment=None,
        )

        if was_approved:
            await self._reverse_approval(
                company_id,
                updated,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        read = await self._read(updated, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_APPLICATION_CANCELLED",
            entity_type="leave_application",
            entity_id=application_id,
            before=leave_application_to_audit_dict(await self._read(row, company_id=company_id)),
            after=leave_application_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _reverse_approval(
        self,
        company_id: UUID,
        row: Any,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """LD-13: an offsetting `ADJUSTMENT` ledger entry (never mutates the original
        `APPLICATION` debit, ADR-0004) plus `LeaveProjectionService.cancel()` for every day that
        was actually synced."""
        from hrms.modules.attendance.schemas import LeaveProjectionCancelInput
        from hrms.modules.attendance.service import LeaveProjectionService

        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=row.leave_type_id
        )
        if leave_type is not None and leave_type.requires_balance:
            await self._ledger_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": row.employee_id,
                    "leave_type_id": row.leave_type_id,
                    "entry_type": "ADJUSTMENT",
                    "amount": row.total_days,
                    "effective_date": date.today(),
                    "reference_id": row.id,
                    "reason": "Reversal: leave application cancelled after approval",
                    "created_by_user_id": actor_user_id,
                },
            )

        days = await self._day_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=row.id
        )
        full_scope = DataScope(levels=frozenset({DataScopeLevel.COMPANY}))
        projection_service = LeaveProjectionService(self._session)
        for day in days:
            if day.leave_day_projection_id is None:
                continue
            projection = await projection_service.get_projection(
                company_id,
                day.leave_day_projection_id,
                scope=full_scope,
                caller_employee_id=None,
            )
            await projection_service.cancel(
                company_id,
                day.leave_day_projection_id,
                LeaveProjectionCancelInput(reason="Leave application cancelled after approval"),
                expected_version=projection.version,
                scope=full_scope,
                caller_employee_id=None,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

    # -----------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------

    async def list_applications(
        self,
        company_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> list[LeaveApplicationRead]:
        visible_ids = await self._resolve_visible_employee_ids(
            company_id, scope, caller_employee_id
        )
        rows = await self._repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        return [await self._read(r, company_id=company_id) for r in rows]

    async def get_application(
        self,
        company_id: UUID,
        application_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> LeaveApplicationRead:
        row = await self._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if row is None:
            raise LeaveApplicationNotFoundError()
        visible_ids = await self._resolve_visible_employee_ids(
            company_id, scope, caller_employee_id
        )
        if visible_ids is not None and row.employee_id not in visible_ids:
            raise LeaveApplicationNotFoundError()
        return await self._read(row, company_id=company_id)

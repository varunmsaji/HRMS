"""Business logic for the Leave module — the public interface for other modules (Module
Standard). L1 only: leave-type identity CRUD + leave-policy identity/version CRUD with the same
draft/publish/discard lifecycle every other policy family in this codebase uses. No accrual (L3),
application workflow (L4), or comp-off redemption (L5) yet — see LEAVE_DECISION_LOG.md LD-09."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import NotFoundError
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
from hrms.modules.leave.repository import LeavePolicyRepository, LeaveTypeRepository
from hrms.modules.leave.schemas import (
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
        now = datetime.now(UTC)
        policy_id = uuid4()
        try:
            row = await self._repo.insert_policy(
                self._session,
                data={
                    "id": policy_id,
                    "company_id": company_id,
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

"""Business logic for the Leave module — the public interface for other modules (Module
Standard). L1: leave-type identity CRUD + leave-policy identity/version CRUD with the same
draft/publish/discard lifecycle every other policy family in this codebase uses. L2: the
append-only leave ledger (ADR-0004) and balance computation. L3: the monthly accrual engine
(LEAVE_DECISION_LOG.md LD-06), invoked from `leave/tasks.py`. L4: application submission +
approval workflow (LD-02/LD-05/LD-12/LD-13). L5: comp-off credit + expiry sweep
(LD-07/LD-14), also invoked from `leave/tasks.py` — redemption itself is not new code, since it
reuses L4's generic application/ledger machinery against an `is_comp_off=true` `LeaveType`."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import get_settings
from hrms.core.db.locks import lock_attendance_period_close, lock_employee_leave_dates
from hrms.core.errors.base import NotFoundError, PermissionDeniedError
from hrms.core.observability.logging import get_logger, safe_error
from hrms.core.observability.operations import logged_operation
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.leave.approval_chain import effective_stage_sequence, next_approval_stage
from hrms.modules.leave.exceptions import (
    LeaveApplicationApproverMismatchError,
    LeaveApplicationAttachmentRequiredError,
    LeaveApplicationBalanceShortfallError,
    LeaveApplicationCalendarNotResolvedError,
    LeaveApplicationCancelReasonRequiredError,
    LeaveApplicationCombinationNotAllowedError,
    LeaveApplicationDateRangeInvalidError,
    LeaveApplicationHalfDayNotAllowedError,
    LeaveApplicationInsufficientBalanceError,
    LeaveApplicationInvalidTransitionError,
    LeaveApplicationLimitExceededError,
    LeaveApplicationMaxConsecutiveExceededError,
    LeaveApplicationNotAllowedDuringProbationError,
    LeaveApplicationNotFoundError,
    LeaveApplicationNotPermittedError,
    LeaveApplicationOverlapError,
    LeaveApplicationPeriodClosedError,
    LeaveApplicationPolicyNotResolvedError,
    LeaveApplicationReasonRequiredError,
    LeaveApplicationSelfApprovalNotAllowedError,
    LeaveApplicationWindowExceededError,
    LeaveApprovalOutsideEmploymentError,
    LeaveApproverReassignNotApplicableError,
    LeaveApproverStillEligibleError,
    LeaveCombinationRuleAlreadyExistsError,
    LeaveCombinationRuleNotFoundError,
    LeaveDateOutsideEmploymentError,
    LeaveEncashmentMaxDaysExceededError,
    LeaveEncashmentMinimumBalanceViolationError,
    LeaveEncashmentNotAllowedError,
    LeaveEncashmentPolicyNotResolvedError,
    LeaveLedgerPayrollFinalisedError,
    LeaveLedgerPeriodClosedError,
    LeavePolicyBelowStatutoryMinimumError,
    LeavePolicyCodeAlreadyExistsError,
    LeavePolicyDraftAlreadyExistsError,
    LeavePolicyPublishIncompleteError,
    LeavePolicyVersionNotDraftError,
    LeavePolicyVersionOverlapError,
    LeavePolicyVersionPreviousVersionRequiredError,
    LeaveReassignApproverNotEligibleError,
    LeaveStatutoryMinimumNotFoundError,
    LeaveTypeCodeAlreadyExistsError,
    LeaveTypeCompOffAlreadyExistsError,
    LeaveTypeInUseError,
    StaleLeaveResourceError,
)
from hrms.modules.leave.models import LeavePolicy
from hrms.modules.leave.repository import (
    LeaveApplicationActionRepository,
    LeaveApplicationDayRepository,
    LeaveApplicationRepository,
    LeaveCombinationRuleRepository,
    LeaveLedgerRepository,
    LeavePolicyRepository,
    LeaveTypeRepository,
    LeaveYearEndRunRepository,
    LeaveYearSettingRepository,
    StatutoryLeaveMinimumRepository,
)
from hrms.modules.leave.schemas import (
    LeaveApplicationCreate,
    LeaveApplicationRead,
    LeaveApplicationReassignInput,
    LeaveApplicationReviewInput,
    LeaveBalanceRead,
    LeaveCombinationRuleCreate,
    LeaveCombinationRuleRead,
    LeaveLedgerAdjustmentCreate,
    LeaveLedgerEncashmentCreate,
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
    LeaveYearSettingRead,
    LeaveYearSettingUpsert,
    StatutoryLeaveMinimumCreate,
    StatutoryLeaveMinimumRead,
    build_leave_policy_update_values,
    build_leave_policy_version_update_values,
    build_leave_type_update_values,
    leave_application_to_audit_dict,
    leave_application_to_read,
    leave_combination_rule_to_audit_dict,
    leave_combination_rule_to_read,
    leave_ledger_entry_to_audit_dict,
    leave_ledger_entry_to_read,
    leave_policy_to_audit_dict,
    leave_policy_to_read,
    leave_policy_version_to_audit_dict,
    leave_policy_version_to_read,
    leave_type_to_audit_dict,
    leave_type_to_read,
    leave_year_setting_to_audit_dict,
    leave_year_setting_to_read,
    statutory_leave_minimum_to_audit_dict,
    statutory_leave_minimum_to_read,
)
from hrms.modules.leave.year import LeaveYearSettingData, is_leave_year_start
from hrms.shared.auto_code import next_auto_code
from hrms.shared.business_time import business_month_start, business_today
from hrms.shared.pagination import PageParams
from hrms.shared.timezone import resolve_zoneinfo

if TYPE_CHECKING:
    from hrms.modules.attendance.repository import CompOffFactRow
    from hrms.modules.leave.models import LeavePolicyVersion

_logger = get_logger(__name__)

#: Decision 11 — the leave-type fields that define what historical applications and ledger entries
#: mean; frozen once the type has been used.
LEAVE_APPLICATION_APPROVE_CODE = "LEAVE.APPLICATION_APPROVE"
LEAVE_TYPE_SEMANTIC_FIELDS = ("requires_balance", "is_comp_off", "is_paid_default")


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
                    "is_comp_off": body.is_comp_off,
                    "statutory_category": body.statutory_category,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            if "leave_type_company_comp_off_idx" in str(exc.orig):
                raise LeaveTypeCompOffAlreadyExistsError() from exc
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
        # Decision 11 — what a leave type *means* (does it draw a balance, is it the comp-off
        # type, is it paid by default) may change only until something has used it. Afterwards the
        # historical applications and ledger entries keep the meaning they were written under.
        changed_semantics = sorted(
            name
            for name in LEAVE_TYPE_SEMANTIC_FIELDS
            if name in values and values[name] != getattr(row, name)
        )
        if changed_semantics and await self._repo.is_used(
            self._session, company_id=company_id, leave_type_id=leave_type_id
        ):
            raise LeaveTypeInUseError(changed_semantics)
        now = datetime.now(UTC)
        updated = row
        if values:
            try:
                result = await self._repo.update(
                    self._session,
                    company_id=company_id,
                    leave_type_id=leave_type_id,
                    values=values,
                    expected_version=expected_version,
                    now=now,
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise LeaveTypeCompOffAlreadyExistsError() from exc
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


class LeaveCombinationRuleService:
    """Client spec §7 (LD-16) — configurable pairwise leave-type exclusivity. Flat identity
    CRUD, no draft/publish lifecycle (unlike `LeavePolicyVersion`): changing a rule is
    delete-and-recreate, since there's no meaningful in-flight-draft state for a single
    boolean. Enforcement itself lives in `LeaveApplicationService.submit()`, not here — this
    class is purely the admin config surface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeaveCombinationRuleRepository()
        self._type_repo = LeaveTypeRepository()

    async def create(
        self,
        company_id: UUID,
        body: LeaveCombinationRuleCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveCombinationRuleRead:
        for leave_type_id in (body.leave_type_id_a, body.leave_type_id_b):
            leave_type = await self._type_repo.get(
                self._session, company_id=company_id, leave_type_id=leave_type_id
            )
            if leave_type is None:
                raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        rule_id = uuid4()
        try:
            row = await self._repo.insert(
                self._session,
                data={
                    "id": rule_id,
                    "company_id": company_id,
                    "leave_type_id_a": body.leave_type_id_a,
                    "leave_type_id_b": body.leave_type_id_b,
                    "allowed": body.allowed,
                    "reason": body.reason,
                    "created_by_user_id": actor_user_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise LeaveCombinationRuleAlreadyExistsError() from exc

        read = leave_combination_rule_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_COMBINATION_RULE_CREATED",
            entity_type="leave_combination_rule",
            entity_id=rule_id,
            after=leave_combination_rule_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list(self, company_id: UUID) -> list[LeaveCombinationRuleRead]:
        rows = await self._repo.list(self._session, company_id=company_id)
        return [leave_combination_rule_to_read(r) for r in rows]

    async def delete(
        self,
        company_id: UUID,
        rule_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        row = await self._repo.get(self._session, company_id=company_id, rule_id=rule_id)
        if row is None:
            raise LeaveCombinationRuleNotFoundError()
        before_read = leave_combination_rule_to_read(row)

        deleted = await self._repo.delete(self._session, company_id=company_id, rule_id=rule_id)
        if not deleted:
            raise LeaveCombinationRuleNotFoundError()

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_COMBINATION_RULE_DELETED",
            entity_type="leave_combination_rule",
            entity_id=rule_id,
            before=leave_combination_rule_to_audit_dict(before_read),
            ip=ip_address,
            user_agent=user_agent,
        )


class LeaveYearSettingService:
    """Client spec §10 (LD-20) — a singleton per-company setting, not a versioned/CRUD
    collection like `LeavePolicyVersion`. `get_effective` lazily materializes the `CALENDAR`
    default on first read rather than requiring HR to explicitly create a row before this
    setting "exists" — every company effectively already has a calendar leave year until told
    otherwise."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeaveYearSettingRepository()

    async def get_effective(self, company_id: UUID) -> LeaveYearSettingRead:
        row = await self._repo.get(self._session, company_id=company_id)
        if row is None:
            now = datetime.now(UTC)
            await self._repo.insert_default_if_absent(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "leave_year_type": "CALENDAR",
                    "start_month": None,
                    "start_day": None,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            row = await self._repo.get(self._session, company_id=company_id)
            assert row is not None  # inserted above, or by the concurrent caller we waited for
        return leave_year_setting_to_read(row)

    async def upsert(
        self,
        company_id: UUID,
        body: LeaveYearSettingUpsert,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveYearSettingRead:
        row = await self._repo.get(self._session, company_id=company_id)
        now = datetime.now(UTC)

        if row is None:
            created = await self._repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "leave_year_type": body.leave_year_type,
                    "start_month": body.start_month,
                    "start_day": body.start_day,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            read = leave_year_setting_to_read(created)
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="LEAVE_YEAR_SETTING_CREATED",
                entity_type="leave_year_setting",
                entity_id=created.id,
                after=leave_year_setting_to_audit_dict(read),
                ip=ip_address,
                user_agent=user_agent,
            )
            return read

        before_read = leave_year_setting_to_read(row)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            values={
                "leave_year_type": body.leave_year_type,
                "start_month": body.start_month,
                "start_day": body.start_day,
            },
            expected_version=row.version,
            now=now,
        )
        if updated is None:
            latest = await self._repo.get(self._session, company_id=company_id)
            current = (
                leave_year_setting_to_audit_dict(leave_year_setting_to_read(latest))
                if latest
                else {}
            )
            raise StaleLeaveResourceError(
                "This leave year setting has been modified by another request", current=current
            )

        after_read = leave_year_setting_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_YEAR_SETTING_UPDATED",
            entity_type="leave_year_setting",
            entity_id=updated.id,
            before=leave_year_setting_to_audit_dict(before_read),
            after=leave_year_setting_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read


class StatutoryLeaveMinimumService:
    """Client spec §16 (LD-22) — HR/compliance-entered legal compliance floor. Flat identity
    CRUD, no draft/publish lifecycle (mirrors `LeaveCombinationRuleService`): editing a minimum
    is delete-and-recreate. Enforcement lives in `LeavePolicyService.publish_version`, not here —
    this class is purely the admin config surface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = StatutoryLeaveMinimumRepository()

    async def create(
        self,
        company_id: UUID,
        body: StatutoryLeaveMinimumCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StatutoryLeaveMinimumRead:
        now = datetime.now(UTC)
        minimum_id = uuid4()
        row = await self._repo.insert(
            self._session,
            data={
                "id": minimum_id,
                "company_id": company_id,
                "state_code": body.state_code,
                "establishment_type": body.establishment_type,
                "leave_category": body.leave_category,
                "min_days_per_year": body.min_days_per_year,
                "note": body.note,
                "created_by_user_id": actor_user_id,
                "created_at": now,
                "updated_at": now,
            },
        )

        read = statutory_leave_minimum_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="STATUTORY_LEAVE_MINIMUM_CREATED",
            entity_type="statutory_leave_minimum",
            entity_id=minimum_id,
            after=statutory_leave_minimum_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list(self, company_id: UUID) -> list[StatutoryLeaveMinimumRead]:
        rows = await self._repo.list(self._session, company_id=company_id)
        return [statutory_leave_minimum_to_read(r) for r in rows]

    async def delete(
        self,
        company_id: UUID,
        minimum_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        row = await self._repo.get(self._session, company_id=company_id, minimum_id=minimum_id)
        if row is None:
            raise LeaveStatutoryMinimumNotFoundError()
        before_read = statutory_leave_minimum_to_read(row)

        deleted = await self._repo.delete(
            self._session, company_id=company_id, minimum_id=minimum_id
        )
        if not deleted:
            raise LeaveStatutoryMinimumNotFoundError()

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="STATUTORY_LEAVE_MINIMUM_DELETED",
            entity_type="statutory_leave_minimum",
            entity_id=minimum_id,
            before=statutory_leave_minimum_to_audit_dict(before_read),
            ip=ip_address,
            user_agent=user_agent,
        )


def _negative_floor(policy_version: Any) -> Decimal:
    """PAY-011 (decision 8) — how many days below zero this policy lets the balance go: its
    `negative_balance_floor` when `allow_negative_balance` is on, else 0 (NULL reads as 0)."""
    if policy_version is None or not policy_version.allow_negative_balance:
        return Decimal("0.00")
    return policy_version.negative_balance_floor or Decimal("0.00")


def _year_end_split(version: Any, balance: Decimal) -> tuple[Decimal, Decimal]:
    """Decision 11 — `(lapse, encash)` days out of the balance at leave-year start.
    `LAPSE` forfeits the whole positive balance. `CARRY_FORWARD` keeps up to
    `max_carry_forward_days` (no cap: keeps everything) and forfeits the rest. `ENCASH_EXCESS`
    keeps up to the cap and encashes the rest, at most `max_encashment_days` when set — anything
    above that still lapses. A negative balance is never touched (recovered in F&F, decision 8)."""
    zero = Decimal("0.00")
    if balance <= 0:
        return zero, zero
    if version.year_end_action == "LAPSE":
        return balance, zero
    if version.max_carry_forward_days is None:
        return zero, zero
    excess = max(balance - version.max_carry_forward_days, zero)
    if version.year_end_action != "ENCASH_EXCESS":
        return excess, zero
    encash = excess
    if version.max_encashment_days is not None:
        encash = min(excess, version.max_encashment_days)
    return excess - encash, encash


def _annual_entitlement_days(
    accrual_frequency: str, accrual_rate_per_cycle: Decimal | None
) -> Decimal:
    """LD-22 — the same two fields `LeaveAccrualService` already reads, converted to a per-year
    figure for comparison against a statutory minimum. `NONE`/unset accrual has no entitlement to
    compare, so it never trips the floor (nothing to publish-block on for a leave type with no
    accrual configured at all)."""
    if accrual_rate_per_cycle is None:
        return Decimal("0")
    if accrual_frequency == "MONTHLY":
        return accrual_rate_per_cycle * 12
    if accrual_frequency == "YEARLY":
        return accrual_rate_per_cycle
    return Decimal("0")


class LeavePolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._repo = LeavePolicyRepository()
        self._type_repo = LeaveTypeRepository()
        self._statutory_repo = StatutoryLeaveMinimumRepository()

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
                    "code": await next_auto_code(
                        self._session,
                        model=LeavePolicy,
                        company_id=company_id,
                        prefix="LVP",
                    ),
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

    async def list_policies(
        self, company_id: UUID, *, assignable_only: bool = False
    ) -> list[LeavePolicyRead]:
        rows = await self._repo.list_policies(
            self._session, company_id=company_id, assignable_only=assignable_only
        )
        return [leave_policy_to_read(r) for r in rows]

    async def list_policies_with_status(
        self, company_id: UUID, *, assignable_only: bool = False
    ) -> list[LeavePolicyRead]:
        from hrms.modules.organisation.repository import PolicyAssignmentRepository

        policies = await self.list_policies(company_id, assignable_only=assignable_only)
        versions = await self._repo.list_open_and_draft_versions(
            self._session, company_id=company_id
        )
        assignments = await PolicyAssignmentRepository().list_assignments(
            self._session, company_id=company_id, policy_kind="LEAVE_POLICY", current_only=True
        )
        for policy in policies:
            for version in versions:
                if version.policy_id != policy.id:
                    continue
                if version.status == "PUBLISHED":
                    policy.live_from = version.effective_from
                else:
                    policy.has_draft = True
            for assignment in assignments:
                if assignment.policy_id != policy.id:
                    continue
                if assignment.scope_type == "COMPANY":
                    policy.assigned_company_wide = True
                else:
                    policy.assigned_group_count += 1
        return policies

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
                "negative_balance_floor": body.negative_balance_floor,
                "year_end_action": body.year_end_action,
                "sandwich_rule_enabled": body.sandwich_rule_enabled,
                "reserve_balance_on_submission": body.reserve_balance_on_submission,
                "pre_delivery_days": body.pre_delivery_days,
                "post_delivery_days": body.post_delivery_days,
                "allowed_during_probation": body.allowed_during_probation,
                "accrue_during_probation": body.accrue_during_probation,
                "max_consecutive_days": body.max_consecutive_days,
                "max_encashment_days": body.max_encashment_days,
                "min_balance_after_encashment": body.min_balance_after_encashment,
                "encashment_frequency": body.encashment_frequency,
                "encashment_calculation_basis": body.encashment_calculation_basis,
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

    async def _enforce_statutory_minimum(
        self, company_id: UUID, draft: "LeavePolicyVersion"
    ) -> None:
        """LD-22 — client spec §16. Hard-blocks publishing when the draft's computed annual
        entitlement falls below the strictest `statutory_leave_minimum` configured for its leave
        type's `statutory_category`. A leave type with no `statutory_category`, or a company with
        no minimum configured for that category, has nothing to enforce — both valid, non-error
        states (same "not configured yet" posture every other optional policy field in this
        module already uses)."""
        policy = await self._repo.get_policy(
            self._session, company_id=company_id, policy_id=draft.policy_id
        )
        if policy is None:
            return
        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=policy.leave_type_id
        )
        if leave_type is None or leave_type.statutory_category is None:
            return

        floor = await self._statutory_repo.max_min_days_per_year(
            self._session, company_id=company_id, leave_category=leave_type.statutory_category
        )
        if floor is None:
            return

        entitlement = _annual_entitlement_days(
            draft.accrual_frequency, draft.accrual_rate_per_cycle
        )
        if entitlement < floor:
            raise LeavePolicyBelowStatutoryMinimumError(
                f"This policy's annual entitlement ({entitlement} days) is below the statutory "
                f"minimum for {leave_type.statutory_category} leave ({floor} days)"
            )

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
        # PAY-011 (decision 8) — negative balance is opt-in per leave type, and always bounded.
        if draft.allow_negative_balance and not draft.negative_balance_floor:
            raise LeavePolicyPublishIncompleteError(
                "negative_balance_floor (days below zero allowed) is required when "
                "allow_negative_balance is on"
            )
        # Decision 11 — "encash the excess" needs a cap to measure the excess against.
        if draft.year_end_action == "ENCASH_EXCESS" and draft.max_carry_forward_days is None:
            raise LeavePolicyPublishIncompleteError(
                "max_carry_forward_days is required when year_end_action is ENCASH_EXCESS"
            )
        await self._enforce_statutory_minimum(company_id, draft)

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

    async def policy_has_version_as_of(
        self, company_id: UUID, policy_id: UUID, as_of: date
    ) -> bool:
        version = await self._repo.find_effective_as_of(
            self._session, company_id=company_id, policy_id=policy_id, as_of=as_of
        )
        return version is not None

    async def policy_is_published(self, company_id: UUID, policy_id: UUID) -> bool:
        version = await self._repo.get_current_published(
            self._session, company_id=company_id, policy_id=policy_id
        )
        return version is not None


async def _ensure_within_employment(
    session: AsyncSession,
    company_id: UUID,
    employee_id: UUID,
    start_date: date,
    end_date: date | None = None,
    *,
    on_approval: bool = False,
    field: str = "start_date",
) -> None:
    """D0-D3 / D5 - every calendar date in the range (weekends, holidays and non-consuming days
    included) must be covered by ONE employment spell. The decision lives in
    `EmploymentService.check_employment_coverage`; this only maps the refusal to a Leave error.
    Callers hold the employee's `leave-dates` lock first, so an employment change cannot slip in
    between this check and the write that depends on it."""
    from hrms.modules.employee.service import EmploymentService

    coverage = await EmploymentService(session).check_employment_coverage(
        company_id, employee_id, start_date, end_date
    )
    if coverage.is_valid:
        return
    if on_approval:
        raise LeaveApprovalOutsideEmploymentError(
            reason=coverage.status.value, offending_date=coverage.offending_date
        )
    raise LeaveDateOutsideEmploymentError(
        reason=coverage.status.value, offending_date=coverage.offending_date, field=field
    )


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
        self._app_repo = LeaveApplicationRepository()
        self._policy_repo = LeavePolicyRepository()

    async def balances_as_of(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> list[tuple[str, str, Decimal]]:
        """Payroll 5.4 — `(leave type code, name, balance)` for every balance-tracked leave type,
        counting only ledger entries effective on or before `as_of` (the payslip's month end).
        Internal, unscoped cross-module fact query."""
        rows = await self._repo.get_balances(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        return [(row.leave_type_code, row.leave_type_name, row.balance) for row in rows]

    async def list_encashments_between(
        self, company_id: UUID, date_from: date, date_to: date
    ) -> list[tuple[UUID, UUID, UUID, Decimal, date]]:
        """Payroll 5.2 (decision 11, D4) — every `ENCASHMENT` entry effective in
        `[date_from, date_to]`, HR-entered and year-end system entries alike:
        `(entry_id, employee_id, leave_type_id, days, effective_date)` with `days` positive.
        Internal, unscoped cross-module fact query (the pay run is COMPANY-scoped)."""
        rows = await self._repo.list_encashments_between(
            self._session, company_id=company_id, date_from=date_from, date_to=date_to
        )
        return [
            (row.id, row.employee_id, row.leave_type_id, -row.amount, row.effective_date)
            for row in rows
        ]

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

    async def _ensure_employee_in_company(self, company_id: UUID, employee_id: UUID) -> None:
        """LM-07 - the ledger's employee FK is on `employee.id` alone (foreign-key checks do not
        go through row-level security), so a body-supplied `employee_id` from another tenant would
        otherwise be accepted and stored under this company. A foreign or unknown id is a plain
        404, identical either way, so existence elsewhere is not revealed."""
        from hrms.modules.employee.service import EmployeeService

        await EmployeeService(self._session).get_employee(company_id, employee_id)

    async def _ensure_ledger_date_open(
        self, company_id: UUID, employee_id: UUID, effective_date: date
    ) -> None:
        """Decision 14 - a manual adjustment or encashment never modifies a closed attendance
        period, nor one whose payroll is finalised (issued payroll history is not rewritten). The
        correction after closure is a new entry dated in an open period. A finalised pay run
        always sits on a CLOSED attendance period (reopening is refused while one exists), so the
        closed-period lookup finds it; Payroll is then asked which of the two it is, to give the
        caller the precise reason."""
        from hrms.modules.attendance.service import AttendanceService
        from hrms.modules.payroll.service import PayRunService

        closed = await AttendanceService(self._session).closed_period_details_overlapping(
            company_id, employee_id, effective_date, effective_date
        )
        if closed is None:
            return
        period_id, period_start, period_end = closed
        if await PayRunService(self._session).has_finalised_run_for_period(company_id, period_id):
            raise LeaveLedgerPayrollFinalisedError(period_start=period_start, period_end=period_end)
        raise LeaveLedgerPeriodClosedError(period_start=period_start, period_end=period_end)

    async def ensure_can_adjust_balance(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> None:
        """DEF-B10-01 - the target employee must lie inside the data scope `LEAVE.BALANCE_ADJUST`
        was granted with (`None` visible set = COMPANY). An out-of-scope, unknown or foreign
        employee is the same 404. Routers call this before the idempotency wrapper so a denied
        request leaves no idempotency record; the mutating methods call it again themselves."""
        await self._ensure_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

    @logged_operation("leave.ledger.adjust")
    async def create_adjustment(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: LeaveLedgerAdjustmentCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveLedgerEntryRead:
        """`scope` is the grant of `LEAVE.BALANCE_ADJUST` and is enforced against the target
        employee before any lock or write (DEF-B10-01). The shipped roles hold the permission
        at COMPANY, which resolves to "no filter". `scope` is required, never defaulted."""
        await self.ensure_can_adjust_balance(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=body.leave_type_id
        )
        if leave_type is None:
            raise NotFoundError("Resource not found")
        await self._ensure_employee_in_company(company_id, employee_id)
        # D5 - the effective date must sit inside an employment spell. The employee's leave-dates
        # lock (always the first lock) orders this against a termination that would move the
        # last working day underneath it.
        await lock_employee_leave_dates(self._session, company_id, employee_id)
        await _ensure_within_employment(
            self._session, company_id, employee_id, body.effective_date, field="effective_date"
        )
        await self._ensure_ledger_date_open(company_id, employee_id, body.effective_date)
        if body.amount < 0:
            # LM-02 - a debit must be ordered against the approval's check-then-debit on the same
            # balance, or an approval that checked a larger balance commits underneath it.
            await self._repo.lock_balance(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                leave_type_id=body.leave_type_id,
            )

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

    @logged_operation("leave.encashment.create")
    async def create_encashment(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: LeaveLedgerEncashmentCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveLedgerEntryRead:
        """L2.5 — client spec §12 (LD-19). Same scope enforcement as `create_adjustment`
        (DEF-B10-01 sibling): the target employee must be inside `scope`. Resolves the applicable
        published `LeavePolicyVersion` the same way `LeaveApplicationService.submit()` does, and
        validates against it before writing — the one real difference from a plain adjustment,
        which writes unconditionally."""
        await self.ensure_can_adjust_balance(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=body.leave_type_id
        )
        if leave_type is None:
            raise NotFoundError("Resource not found")
        await self._ensure_employee_in_company(company_id, employee_id)
        # D5 - the effective date must sit inside an employment spell. The employee's leave-dates
        # lock (always the first lock) orders this against a termination that would move the
        # last working day underneath it.
        await lock_employee_leave_dates(self._session, company_id, employee_id)
        await _ensure_within_employment(
            self._session, company_id, employee_id, body.effective_date, field="effective_date"
        )
        await self._ensure_ledger_date_open(company_id, employee_id, body.effective_date)

        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

        resolver = CalendarResolutionService(self._session)
        found = await resolver.resolve_policy_assignment(
            company_id,
            "LEAVE_POLICY",
            employee_id=employee_id,
            target_date=body.effective_date,
            leave_type_id=body.leave_type_id,
        )
        if found is None:
            raise LeaveEncashmentPolicyNotResolvedError()
        assignment, _scope_type = found

        policy_version = await self._policy_repo.find_effective_as_of(
            self._session,
            company_id=company_id,
            policy_id=assignment.policy_id,
            as_of=body.effective_date,
        )
        if policy_version is None:
            raise LeaveEncashmentPolicyNotResolvedError()

        if not policy_version.encashment_allowed:
            raise LeaveEncashmentNotAllowedError()
        if (
            policy_version.max_encashment_days is not None
            and body.days > policy_version.max_encashment_days
        ):
            raise LeaveEncashmentMaxDaysExceededError()

        # LM-02 - the same per-(employee, type) lock approval and expiry take, held from before
        # the balance is read until this transaction commits: two encashments (or an encashment
        # and an approval) can no longer both pass the minimum-balance check on one balance.
        await self._repo.lock_balance(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=body.leave_type_id,
        )
        current_balance = await self._repo.get_balance(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=body.leave_type_id,
        )
        remaining = current_balance - body.days
        min_required = policy_version.min_balance_after_encashment or Decimal("0.00")
        if remaining < min_required:
            raise LeaveEncashmentMinimumBalanceViolationError()

        entry_id = uuid4()
        row = await self._repo.insert(
            self._session,
            data={
                "id": entry_id,
                "company_id": company_id,
                "employee_id": employee_id,
                "leave_type_id": body.leave_type_id,
                "entry_type": "ENCASHMENT",
                "amount": -body.days,
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
            action="LEAVE_LEDGER_ENCASHMENT_CREATED",
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
        page: PageParams,
    ) -> tuple[list[LeaveLedgerEntryRead], int]:
        """`_ensure_employee_visible` raises before any ledger row is ever fetched — pagination
        only ever slides across one already-authorized employee's own ledger (API-01 §6/§10)."""
        await self._ensure_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        rows = await self._repo.list_for_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._repo.count_for_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
        )
        return [leave_ledger_entry_to_read(r) for r in rows], total

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
        # LD-15 — reserved balance is always derived live from open applications, shown
        # alongside `balance` regardless of whether reservation is actually enforced for that
        # type (client spec §8: "preferably show" both figures separately).
        pending_by_type = await self._app_repo.sum_pending_by_leave_type(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [
            LeaveBalanceRead(
                employee_id=employee_id,
                leave_type_id=r.leave_type_id,
                leave_type_code=r.leave_type_code,
                leave_type_name=r.leave_type_name,
                balance=r.balance,
                reserved_balance=pending_by_type.get(r.leave_type_id, Decimal("0.00")),
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


def _prorate_accrual_days(rate: Decimal, total_days: int, worked_days: int) -> Decimal:
    if worked_days >= total_days:
        return rate.quantize(Decimal("0.01"))
    prorated = (rate * worked_days) / total_days
    return prorated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _prorate_accrual(
    rate: Decimal, period_start: date, period_end: date, worked_start: date, worked_end: date
) -> Decimal:
    return _prorate_accrual_days(
        rate, (period_end - period_start).days + 1, (worked_end - worked_start).days + 1
    )


def _worked_days_in_period(
    spells: list[tuple[date, date | None]], period_start: date, period_end: date
) -> int:
    """Calendar days of `[period_start, period_end]` the employee was employed, summed over every
    employment spell (a rehire inside the same month has two). Spells cannot overlap each other."""
    total = 0
    for joining_date, last_working_day in spells:
        start = max(period_start, joining_date)
        end = min(period_end, last_working_day or period_end)
        if start <= end:
            total += (end - start).days + 1
    return total


class LeaveAccrualService:
    """L3 — the monthly accrual engine (LEAVE_DECISION_LOG.md LD-06). Invoked by the
    `leave.accrue_company` Celery task (`leave/tasks.py`), never from an HTTP route — this is
    background-job business logic, not a request-scoped one, so it takes no `DataScope`/caller
    and writes system-generated ledger rows (`created_by_user_id=None`).

    `run_for_company` handles `accrual_frequency == "MONTHLY"`. `run_year_end_for_company`
    (LD-21) handles `YEARLY` accrual and carry-forward cap enforcement together, both gated on
    `LeaveYearSetting` (LD-20) — the fiscal-year anchor LD-06/WD-21 originally left undecided."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ledger_repo = LeaveLedgerRepository()
        self._type_repo = LeaveTypeRepository()
        self._policy_repo = LeavePolicyRepository()
        self._year_setting_service = LeaveYearSettingService(session)

    @logged_operation("leave.accrual.run_company")
    async def run_for_company(self, company_id: UUID, *, as_of: date) -> int:
        """Accrue for the calendar month before `as_of`, for every employee whose employment
        span overlaps it and every active, balance-backed leave type that resolves to a
        `MONTHLY` published policy for them. Idempotent — safe to call more than once for the
        same `as_of` (a re-run, a retried task): already-written cycles are skipped via
        `LeaveLedgerRepository.exists_for_cycle`, never double-inserted (ADR-0004: corrections
        are new rows, but duplicates are not corrections)."""
        period_start, period_end = _previous_month_bounds(as_of)

        from hrms.modules.employee.service import EmployeeService, EmploymentService
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
        employee_service = EmployeeService(self._session)
        written = 0
        failed = 0
        spells_by_employee: dict[UUID, list[tuple[date, date | None]]] = {}
        for employee_id, joining_date, last_working_day in spans:
            spells_by_employee.setdefault(employee_id, []).append((joining_date, last_working_day))
        for employee_id, spells in spells_by_employee.items():
            # One SAVEPOINT per employee (PRA-07): a failure for one employee rolls back only their
            # own rows, is logged, and never stops the rest of the company. Re-running the task is
            # safe (the cycle keys make every write idempotent), so the missed employee is picked
            # up by the next run.
            try:
                async with self._session.begin_nested():
                    written += await self._accrue_employee_month(
                        company_id,
                        employee_id,
                        spells,
                        period_start=period_start,
                        period_end=period_end,
                        accrual_types=accrual_types,
                        resolver=resolver,
                        employee_service=employee_service,
                    )
            except SoftTimeLimitExceeded:
                raise  # the task's time limit — stop the run, not one employee's failure
            except Exception as exc:  # noqa: BLE001 - isolate one employee, see above
                failed += 1
                _logger.warning(
                    "leave_accrual_employee_failed",
                    company_id=str(company_id),
                    employee_id=str(employee_id),
                    period_end=period_end.isoformat(),
                    **safe_error(exc),
                )
        if failed:
            _logger.warning(
                "leave_accrual_incomplete",
                company_id=str(company_id),
                period_end=period_end.isoformat(),
                employees_failed=failed,
                entries_written=written,
            )
        return written

    async def _accrue_employee_month(
        self,
        company_id: UUID,
        employee_id: UUID,
        spells: list[tuple[date, date | None]],
        *,
        period_start: date,
        period_end: date,
        accrual_types: list[Any],
        resolver: Any,
        employee_service: Any,
    ) -> int:
        # Decision 20 - accrual is governed only by the configured accrual policy and the days
        # employed (summed over every spell). Unpaid-leave (LOP) days deliberately do NOT reduce
        # it; if the product ever wants that, it must arrive as an explicit policy capability, not
        # as a silent deduction here.
        written = 0
        worked_days = _worked_days_in_period(spells, period_start, period_end)
        if worked_days <= 0:
            return 0
        employee = await employee_service.get_employee(company_id, employee_id)

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
            if not version.accrue_during_probation and employee.status == "PROBATION":
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

            amount = _prorate_accrual_days(
                version.accrual_rate_per_cycle,
                (period_end - period_start).days + 1,
                worked_days,
            )
            if amount <= 0:
                continue

            if await self._ledger_repo.insert_if_absent(
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
            ):
                written += 1
        return written

    @logged_operation("leave.year_end.run_company")
    async def run_year_end_for_company(
        self, company_id: UUID, *, as_of: date, catchup_days: int | None = None
    ) -> int:
        """LD-21 / decision 16 - for every employee whose leave-year start falls on `as_of` or in
        the `catchup_days - 1` days before it (default `leave_year_end_catchup_days`, 5) and who
        was employed on that start date, applies the policy's year-end rule (decision 11,
        `_year_end_split`: lapse / carry-forward cap / encash the excess) against the balance **as
        it stands when this runs**, then credits `YEARLY` accrual - all per leave type.

        A year start is handled at most once per employee: `leave_year_end_run` is claimed inside
        the employee's savepoint, so a repeat run, a later day inside the window, or a concurrent
        second run skips them (a failed attempt rolls the claim back and is retried on the next
        run). Leave-year start dates are per `LeaveYearSetting` (LD-20) - one date for everyone
        under `CALENDAR`/`FINANCIAL`/`CUSTOM`, each spell's own `joining_date` anniversary under
        `ANNIVERSARY` - and ledger rows are dated on that start date, never on the catch-up day.
        `as_of` is the company-local business date (the caller's responsibility)."""
        window = (
            catchup_days if catchup_days is not None else get_settings().leave_year_end_catchup_days
        )
        window_start = as_of - timedelta(days=window - 1)
        setting_read = await self._year_setting_service.get_effective(company_id)
        setting = LeaveYearSettingData(
            leave_year_type=setting_read.leave_year_type,
            start_month=setting_read.start_month,
            start_day=setting_read.start_day,
        )

        from hrms.modules.employee.service import EmploymentService

        spans = await EmploymentService(self._session).list_spans_overlapping(
            company_id, date_from=window_start, date_to=as_of
        )
        if not spans:
            return 0

        leave_types = await self._type_repo.list(self._session, company_id=company_id)
        accrual_types = sorted(
            (t for t in leave_types if t.is_active and t.requires_balance), key=lambda t: t.id
        )
        if not accrual_types:
            return 0

        # (employee, year start) pairs due in the window. Sorted so that concurrent runs claim and
        # lock employees in the same order and cannot deadlock each other.
        due: set[tuple[UUID, date]] = set()
        for employee_id, joining_date, last_working_day in spans:
            for offset in range(window):
                day = as_of - timedelta(days=offset)
                if day < joining_date or (last_working_day is not None and day > last_working_day):
                    continue
                if is_leave_year_start(setting, as_of=day, joining_date=joining_date):
                    due.add((employee_id, day))

        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

        resolver = CalendarResolutionService(self._session)
        written = 0
        failed = 0
        for employee_id, year_start in sorted(due):
            # One SAVEPOINT per employee (PRA-07), as in the monthly accrual: one employee's
            # failure is logged and rolled back alone (claim included); a re-run completes the rest.
            try:
                async with self._session.begin_nested():
                    written += await self._year_end_for_employee(
                        company_id,
                        employee_id,
                        year_start=year_start,
                        accrual_types=accrual_types,
                        resolver=resolver,
                    )
            except SoftTimeLimitExceeded:
                raise  # the task's time limit — stop the run, not one employee's failure
            except Exception as exc:  # noqa: BLE001 - isolate one employee, see above
                failed += 1
                _logger.warning(
                    "leave_year_end_employee_failed",
                    company_id=str(company_id),
                    employee_id=str(employee_id),
                    year_start=year_start.isoformat(),
                    as_of=as_of.isoformat(),
                    **safe_error(exc),
                )
        if failed:
            _logger.warning(
                "leave_year_end_incomplete",
                company_id=str(company_id),
                as_of=as_of.isoformat(),
                employees_failed=failed,
                entries_written=written,
            )
        return written

    async def _year_end_for_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        year_start: date,
        accrual_types: list[Any],
        resolver: Any,
    ) -> int:
        written = 0
        run_repo = LeaveYearEndRunRepository()
        if await run_repo.has_prior_year_end_entries(
            self._session, company_id=company_id, employee_id=employee_id, year_start=year_start
        ):
            # Processed by the pre-marker engine - record it so later window days skip it.
            await run_repo.claim(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                year_start=year_start,
            )
            return 0
        if not await run_repo.claim(
            self._session, company_id=company_id, employee_id=employee_id, year_start=year_start
        ):
            return 0  # already processed, or being processed by a concurrent run

        for leave_type in accrual_types:
            found = await resolver.resolve_policy_assignment(
                company_id,
                "LEAVE_POLICY",
                employee_id=employee_id,
                target_date=year_start,
                leave_type_id=leave_type.id,
            )
            if found is None:
                continue
            assignment, _scope_type = found

            version = await self._policy_repo.find_effective_as_of(
                self._session,
                company_id=company_id,
                policy_id=assignment.policy_id,
                as_of=year_start,
            )
            if version is None:
                continue

            # LM-08 - the lapse is computed from the balance read here, so it is read under the
            # same per-(employee, type) lock approval, encashment and expiry take. Without it an
            # approval committing between this read and the lapse insert left a lapse larger than
            # the real excess.
            await self._ledger_repo.lock_balance(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                leave_type_id=leave_type.id,
            )
            balance = await self._ledger_repo.get_balance(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                leave_type_id=leave_type.id,
            )
            lapse, encash = _year_end_split(version, balance)
            if lapse > 0:
                already_forfeited = await self._ledger_repo.exists_for_cycle(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    leave_type_id=leave_type.id,
                    entry_type="CARRY_FORWARD",
                    effective_date=year_start,
                )
                if not already_forfeited:
                    reason = (
                        f"Balance lapsed at leave year start {year_start}"
                        if version.year_end_action == "LAPSE"
                        else (
                            f"Carry-forward cap ({version.max_carry_forward_days} "
                            f"days) exceeded at leave year start {year_start}"
                        )
                    )
                    if await self._ledger_repo.insert_if_absent(
                        self._session,
                        data={
                            "id": uuid4(),
                            "company_id": company_id,
                            "employee_id": employee_id,
                            "leave_type_id": leave_type.id,
                            "entry_type": "CARRY_FORWARD",
                            "amount": -lapse,
                            "effective_date": year_start,
                            "reference_id": version.id,
                            "reason": reason,
                            "created_by_user_id": None,
                        },
                    ):
                        written += 1
            # Decision 11 — idempotent through `uq_leave_ledger_year_end_encashment`; payroll
            # pays every system-written (`reference_id` set) ENCASHMENT entry.
            if encash > 0:
                if await self._ledger_repo.insert_if_absent(
                    self._session,
                    data={
                        "id": uuid4(),
                        "company_id": company_id,
                        "employee_id": employee_id,
                        "leave_type_id": leave_type.id,
                        "entry_type": "ENCASHMENT",
                        "amount": -encash,
                        "effective_date": year_start,
                        "reference_id": version.id,
                        "reason": (
                            f"Encashed above the carry-forward cap "
                            f"({version.max_carry_forward_days} days) at leave year start "
                            f"{year_start}"
                        ),
                        "created_by_user_id": None,
                    },
                ):
                    written += 1

            if (
                version.accrual_frequency == "YEARLY"
                and version.accrual_rate_per_cycle
                and version.accrual_rate_per_cycle > 0
            ):
                already_accrued = await self._ledger_repo.exists_for_cycle(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    leave_type_id=leave_type.id,
                    entry_type="ACCRUAL",
                    effective_date=year_start,
                )
                if not already_accrued:
                    if await self._ledger_repo.insert_if_absent(
                        self._session,
                        data={
                            "id": uuid4(),
                            "company_id": company_id,
                            "employee_id": employee_id,
                            "leave_type_id": leave_type.id,
                            "entry_type": "ACCRUAL",
                            "amount": version.accrual_rate_per_cycle,
                            "effective_date": year_start,
                            "reference_id": version.id,
                            "reason": f"Yearly accrual for leave year starting {year_start}",
                            "created_by_user_id": None,
                        },
                    ):
                        written += 1
        return written


class LeaveCompOffService:
    """L5 — comp-off credit + expiry (LEAVE_DECISION_LOG.md LD-07/LD-14). Invoked by the
    `leave.credit_comp_off`/`leave.sweep_comp_off_expiry` Celery tasks (`leave/tasks.py`),
    mirroring `LeaveAccrualService`'s background-job posture: no `DataScope`/caller, system-
    generated ledger rows (`created_by_user_id=None`).

    Redemption itself needs no new code here — per LD-07's "explicit spend" UX, an employee
    applies for leave against the `is_comp_off=true` `LeaveType` exactly like any other
    `requires_balance` leave type; the existing generic `LeaveApplicationService`/ledger
    machinery already debits it on approval."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ledger_repo = LeaveLedgerRepository()
        self._type_repo = LeaveTypeRepository()

    @logged_operation("leave.comp_off.credit_company")
    async def credit_company(self, company_id: UUID) -> int:
        """Reads Attendance's terminal, comp-off-bearing `OvertimeRecord`s as a read-only fact
        (LD-07 — Leave never writes to Attendance tables) and writes one `COMP_OFF_CREDIT`
        ledger row per record not yet credited (idempotency keyed on
        `reference_id=overtime_record_id`, mirrors `exists_for_cycle`'s role for accrual).
        Skips entirely if the company hasn't designated a comp-off leave type yet (LD-14), or
        for any individual record whose policy version has no `comp_off_day_length_minutes`
        configured — never guesses a conversion basis.

        Also keeps earlier credits in line with leave approved afterwards (BUS-011): a credit
        whose day is now a full-day leave is reversed, and restored if that leave is cancelled.
        Returns how many credits it wrote; reversals are not counted."""
        comp_off_type = await self._type_repo.get_comp_off_type(
            self._session, company_id=company_id
        )
        if comp_off_type is None:
            return 0

        from hrms.modules.attendance.service import OvertimeRecordService

        overtime = OvertimeRecordService(self._session)
        facts = await overtime.list_comp_off_facts(company_id)
        for fact in await overtime.list_comp_off_facts_on_full_day_leave(company_id):
            await self._reverse_credit_for_leave(company_id, comp_off_type.id, fact)

        written = 0
        for fact in facts:
            if fact.comp_off_day_length_minutes is None or fact.comp_off_day_length_minutes <= 0:
                continue
            already_credited = await self._ledger_repo.exists_with_reference(
                self._session,
                company_id=company_id,
                entry_type="COMP_OFF_CREDIT",
                reference_id=fact.overtime_record_id,
            )
            if already_credited:
                await self._restore_reversed_credit(company_id, comp_off_type.id, fact)
                continue

            amount = (
                Decimal(fact.comp_off_minutes) / Decimal(fact.comp_off_day_length_minutes)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if amount <= 0:
                continue

            if await self._ledger_repo.insert_if_absent(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": fact.employee_id,
                    "leave_type_id": comp_off_type.id,
                    "entry_type": "COMP_OFF_CREDIT",
                    "amount": amount,
                    "effective_date": fact.attendance_date,
                    "reference_id": fact.overtime_record_id,
                    "reason": f"Comp-off earned for {fact.attendance_date:%d %b %Y}",
                    "created_by_user_id": None,
                },
            ):
                written += 1
        return written

    async def _reversed_amount(self, company_id: UUID, fact: "CompOffFactRow") -> Decimal:
        """How much of a credit is currently reversed for leave. Reversals point at the overtime
        record, while expiry points at the credit, so the two can never be mistaken for each
        other."""
        return -await self._ledger_repo.sum_for_reference(
            self._session,
            company_id=company_id,
            employee_id=fact.employee_id,
            entry_type="ADJUSTMENT",
            reference_id=fact.overtime_record_id,
        )

    async def _reverse_credit_for_leave(
        self, company_id: UUID, leave_type_id: UUID, fact: "CompOffFactRow"
    ) -> None:
        """Takes back a credit whose day is now a full-day leave. Like expiry, this never drives
        the balance negative: if the employee has already spent it, nothing is taken and the next
        sweep tries again."""
        await self._ledger_repo.lock_balance(
            self._session,
            company_id=company_id,
            employee_id=fact.employee_id,
            leave_type_id=leave_type_id,
        )
        credited = await self._ledger_repo.sum_for_reference(
            self._session,
            company_id=company_id,
            employee_id=fact.employee_id,
            entry_type="COMP_OFF_CREDIT",
            reference_id=fact.overtime_record_id,
        )
        if credited <= 0 or await self._reversed_amount(company_id, fact) > 0:
            return
        credit_id = await self._ledger_repo.get_id_with_reference(
            self._session,
            company_id=company_id,
            entry_type="COMP_OFF_CREDIT",
            reference_id=fact.overtime_record_id,
        )
        if credit_id is not None and await self._ledger_repo.exists_with_reference(
            self._session, company_id=company_id, entry_type="ADJUSTMENT", reference_id=credit_id
        ):
            return  # already expired, so there is nothing left to take back
        balance = await self._ledger_repo.get_balance(
            self._session,
            company_id=company_id,
            employee_id=fact.employee_id,
            leave_type_id=leave_type_id,
        )
        if balance < credited:
            return
        await self._ledger_repo.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "employee_id": fact.employee_id,
                "leave_type_id": leave_type_id,
                "entry_type": "ADJUSTMENT",
                "amount": -credited,
                "effective_date": fact.attendance_date,
                "reference_id": fact.overtime_record_id,
                "reason": f"Comp-off reversed: on leave {fact.attendance_date:%d %b %Y}",
                "created_by_user_id": None,
            },
        )

    async def _restore_reversed_credit(
        self, company_id: UUID, leave_type_id: UUID, fact: "CompOffFactRow"
    ) -> None:
        """Gives a reversed credit back once the leave that caused it has been cancelled."""
        await self._ledger_repo.lock_balance(
            self._session,
            company_id=company_id,
            employee_id=fact.employee_id,
            leave_type_id=leave_type_id,
        )
        reversed_amount = await self._reversed_amount(company_id, fact)
        if reversed_amount <= 0:
            return
        await self._ledger_repo.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "employee_id": fact.employee_id,
                "leave_type_id": leave_type_id,
                "entry_type": "ADJUSTMENT",
                "amount": reversed_amount,
                "effective_date": fact.attendance_date,
                "reference_id": fact.overtime_record_id,
                "reason": f"Comp-off restored: leave cancelled {fact.attendance_date:%d %b %Y}",
                "created_by_user_id": None,
            },
        )

    @logged_operation("leave.comp_off.expire_company")
    async def expire_company(self, company_id: UUID, *, as_of: date) -> int:
        """LD-14's simple expiry heuristic — no FIFO lot-tracking against the pooled balance
        (LD-03: balance is always a derived `SUM`, with no per-entry "remaining" concept). For
        every `COMP_OFF_CREDIT` entry whose source `OvertimeRecord.comp_off_expiry_date` has
        passed and that hasn't already been offset (idempotency keyed on
        `reference_id=credit.id`), writes one offsetting `ADJUSTMENT` for the credit's full
        original amount — but only if the employee's *current* comp-off balance still covers
        it. If the balance has already fallen below the credit's amount (some of it was spent
        since), nothing is expired for that credit — this never drives a balance negative, at
        the cost of being generous in the edge case where a newer credit was drawn down first.

        Each credit's check-then-offset runs under the employee's comp-off balance lock (the
        one leave approval takes, PAY-010), so a concurrent sweep waits and then sees this
        one's offset instead of expiring the same credit twice, and an approval spending the
        balance can't slip between the balance check and the offset. Credits come back ordered
        by employee, so two sweeps take the locks in the same order."""
        comp_off_type = await self._type_repo.get_comp_off_type(
            self._session, company_id=company_id
        )
        if comp_off_type is None:
            return 0

        from hrms.modules.attendance.service import OvertimeRecordService

        facts_by_id = {
            f.overtime_record_id: f
            for f in await OvertimeRecordService(self._session).list_comp_off_facts(company_id)
        }

        credits = await self._ledger_repo.list_credits_for_expiry(
            self._session, company_id=company_id, leave_type_id=comp_off_type.id
        )

        expired = 0
        for credit in credits:
            fact = facts_by_id.get(credit.reference_id) if credit.reference_id else None
            expiry_date = fact.comp_off_expiry_date if fact else None
            if expiry_date is None or expiry_date > as_of:
                continue
            await self._ledger_repo.lock_balance(
                self._session,
                company_id=company_id,
                employee_id=credit.employee_id,
                leave_type_id=comp_off_type.id,
            )
            already_expired = await self._ledger_repo.exists_with_reference(
                self._session,
                company_id=company_id,
                entry_type="ADJUSTMENT",
                reference_id=credit.id,
            )
            if already_expired:
                continue

            current_balance = await self._ledger_repo.get_balance(
                self._session,
                company_id=company_id,
                employee_id=credit.employee_id,
                leave_type_id=comp_off_type.id,
            )
            if current_balance < credit.amount:
                continue

            await self._ledger_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": credit.employee_id,
                    "leave_type_id": comp_off_type.id,
                    "entry_type": "ADJUSTMENT",
                    "amount": -credit.amount,
                    "effective_date": as_of,
                    "reference_id": credit.id,
                    "reason": f"Comp-off expired (earned {credit.effective_date:%d %b %Y})",
                    "created_by_user_id": None,
                },
            )
            expired += 1
        return expired


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
        self._combination_rule_repo = LeaveCombinationRuleRepository()

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

    async def _read_many(self, rows: list[Any], *, company_id: UUID) -> list[LeaveApplicationRead]:
        """Bulk form of `_read` (API-01 §5) — 1 query for `days` + 1 for `actions` across the
        whole page, instead of 2 queries per row. `rows` is expected to already be one bounded
        page (`list_applications`), so the `IN (...)` batch stays small regardless of how large
        the overall filtered result set is."""
        if not rows:
            return []
        application_ids = [r.id for r in rows]
        days = await self._day_repo.list_for_applications(
            self._session, company_id=company_id, leave_application_ids=application_ids
        )
        actions = await self._action_repo.list_for_applications(
            self._session, company_id=company_id, leave_application_ids=application_ids
        )
        days_by_application: dict[Any, list[Any]] = {aid: [] for aid in application_ids}
        for day in days:
            days_by_application[day.leave_application_id].append(day)
        actions_by_application: dict[Any, list[Any]] = {aid: [] for aid in application_ids}
        for action in actions:
            actions_by_application[action.leave_application_id].append(action)
        return [
            leave_application_to_read(
                row,
                days=days_by_application[row.id],
                actions=actions_by_application[row.id],
            )
            for row in rows
        ]

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

        WORKING/SPECIAL_WORKING days (and the working half of a half-day weekly off) are
        leave-consuming by default; full WEEKLY_OFF/HOLIDAY/SHUTDOWN days are not, unless the
        sandwich rule brackets a run of them (a Saturday and Sunday, say) between two consuming
        days *within this same application's range* (no cross-application look-back — a separate,
        earlier application on an adjacent date is not consulted here)."""
        from hrms.modules.organisation.calendar_resolution import (
            CalendarResolutionService,
            working_fraction_of,
        )

        resolver = CalendarResolutionService(self._session)
        span_days = (body.end_date - body.start_date).days + 1
        dates = [body.start_date + timedelta(days=i) for i in range(span_days)]

        # Work Calendar policy A: how much of each date can be taken as leave is the day's working
        # share, from the same calendar rule attendance reads - 1.00 on a working day, 0.50 on a
        # half-day weekly off (the off half is already a paid day off), 0.00 on a full weekly off,
        # holiday or shutdown.
        working: dict[date, Decimal] = {}
        for one_date in dates:
            resolved = await resolver.resolve_for_employee(company_id, employee_id, one_date)
            if resolved.config_incomplete or resolved.day_type is None:
                raise LeaveApplicationCalendarNotResolvedError()
            working[one_date] = working_fraction_of(resolved.day_type)

        consuming: dict[date, bool] = {d: working[d] > Decimal("0.00") for d in dates}

        if sandwich_rule_enabled:
            consuming_positions = [i for i, d in enumerate(dates) if working[d] > Decimal("0.00")]
            for before, after in zip(consuming_positions, consuming_positions[1:], strict=False):
                for d in dates[before + 1 : after]:
                    consuming[d] = True

        breakdown: list[dict[str, Any]] = []
        for d in dates:
            if not consuming[d]:
                continue
            is_sandwich = working[d] == Decimal("0.00")
            # A sandwich-generated off day is a whole day; otherwise the day's working share.
            fraction = Decimal("1.00") if is_sandwich else working[d]
            half = None
            if body.half_day is not None and d == body.start_date and d == body.end_date:
                fraction = min(fraction, Decimal("0.50"))
                half = body.half_day
            breakdown.append(
                {
                    "date": d,
                    "fraction": fraction,
                    "half": half,
                    "is_sandwich_generated": is_sandwich,
                    "cap": Decimal("1.00") if is_sandwich else working[d],
                }
            )

        if not breakdown:
            raise LeaveApplicationDateRangeInvalidError(
                "This date range has no leave-consuming days"
            )
        return breakdown

    @logged_operation("leave.application.submit")
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
        # LM-07 - a company-scoped on-behalf caller passes visibility for any UUID; the target
        # must also be an employee of THIS company.
        from hrms.modules.employee.service import EmployeeService

        await EmployeeService(self._session).get_employee(company_id, employee_id)

        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=body.leave_type_id
        )
        if leave_type is None:
            raise NotFoundError("Resource not found")
        # PRA-15: serialise the overlap check + insert below against a concurrent submission or
        # approval for this employee (held until the transaction ends). Also orders this
        # submission against a termination (LM-15), so it is taken before anything is validated.
        await self._repo.lock_employee_leave_dates(
            self._session, company_id=company_id, employee_id=employee_id
        )
        # D0-D3 - checked before the period lock so the caller sees "outside employment", not an
        # unrelated period error, for dates that were never theirs to book.
        await _ensure_within_employment(
            self._session, company_id, employee_id, body.start_date, body.end_date
        )
        await self._ensure_period_open(company_id, employee_id, body.start_date, body.end_date)

        # LD-16: reject if another leave type this employee already has an active (SUBMITTED or
        # APPROVED) application for, overlapping this date range, has an explicit
        # allowed=False combination rule against the type being submitted. No rule for a pair
        # means allowed — matches today's behavior, where nothing blocks any combination.
        other_active_types = await self._repo.list_active_overlapping_other_types(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=body.leave_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        for other_type_id in other_active_types:
            rule = await self._combination_rule_repo.get_by_pair(
                self._session,
                company_id=company_id,
                leave_type_id_a=body.leave_type_id,
                leave_type_id_b=other_type_id,
            )
            if rule is not None and not rule.allowed:
                raise LeaveApplicationCombinationNotAllowedError()

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

        # Decision 15 - the policy's cap on one application's calendar span (default 30), checked
        # before any per-day calendar resolution below.
        requested_span = (body.end_date - body.start_date).days + 1
        if requested_span > policy_version.max_consecutive_days:
            raise LeaveApplicationMaxConsecutiveExceededError(
                limit=policy_version.max_consecutive_days, requested=requested_span
            )

        # LD-18: reads the existing Employee.status fact (no new Employee-module schema) — only
        # blocks when the policy explicitly opts out (default True preserves the prior
        # no-such-check behavior for every existing policy version).
        if not policy_version.allowed_during_probation:
            from hrms.modules.employee.service import EmployeeService

            employee = await EmployeeService(self._session).get_employee(company_id, employee_id)
            if employee.status == "PROBATION":
                raise LeaveApplicationNotAllowedDuringProbationError()

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
            # Company-local business date (PRA-14): the server clock's own date is a day behind in
            # India between 00:00 and 05:29.
            backdated_days = (await self._business_today(company_id) - body.start_date).days
            if backdated_days > policy_version.max_backdated_days:
                raise LeaveApplicationWindowExceededError()

        if policy_version.reason_required and not body.reason:
            raise LeaveApplicationReasonRequiredError()
        if policy_version.attachment_required and not body.attachment_reference:
            raise LeaveApplicationAttachmentRequiredError()

        now = datetime.now(UTC)
        if policy_version.max_requests_per_month is not None:
            # "This month" is the company's calendar month, not the UTC one (PRA-14).
            company = await self._company_profile(company_id)
            local_month_start = business_month_start(company.timezone)
            month_start = datetime(
                local_month_start.year,
                local_month_start.month,
                1,
                tzinfo=resolve_zoneinfo(company.timezone),
            )
            count = await self._repo.count_since(
                self._session, company_id=company_id, employee_id=employee_id, since=month_start
            )
            if count >= policy_version.max_requests_per_month:
                raise LeaveApplicationLimitExceededError()

        day_breakdown = await self._compute_day_breakdown(
            company_id, employee_id, body, policy_version.sandwich_rule_enabled
        )
        total_days = sum((d["fraction"] for d in day_breakdown), Decimal("0.00"))

        # PRA-15: leave of one type on one date cannot exceed one day in total (a second full-day
        # request, or a retried/double-clicked submission, for the same type and date). Different
        # types are left to the combination rules and the approval-time per-date total.
        booked = await self._repo.sum_active_fraction_by_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=body.leave_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        if any(
            booked.get(d["date"], Decimal("0.00")) + d["fraction"] > d["cap"] for d in day_breakdown
        ):
            raise LeaveApplicationOverlapError()

        if leave_type.requires_balance:
            balances = await self._ledger_repo.get_balances(
                self._session, company_id=company_id, employee_id=employee_id
            )
            current_balance = next(
                (b.balance for b in balances if b.leave_type_id == leave_type.id), Decimal("0.00")
            )
            # LD-15: when this leave type's policy reserves balance on submission, other still-
            # SUBMITTED applications for it block further balance too — derived live from
            # leave_application, never a stored figure. Default (reserve_balance_on_submission=
            # False) preserves the original LD-06 behavior exactly: only the ledger's own balance
            # is checked, pending applications don't count against it.
            if policy_version.reserve_balance_on_submission:
                reserved = await self._repo.sum_pending_for_type(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    leave_type_id=leave_type.id,
                )
                current_balance -= reserved
            # LD-06 / PAY-011 (decision 8): never below the policy's negative floor — 0 unless
            # the policy opts in with `allow_negative_balance` + `negative_balance_floor`.
            if current_balance + _negative_floor(policy_version) < total_days:
                raise LeaveApplicationInsufficientBalanceError()

        approval_chain = policy_version.approval_chain
        resolved_manager_id: UUID | None = None
        resolved_department_head_id: UUID | None = None
        approval_stage: str | None
        if approval_chain == "AUTO":
            approval_stage = None
        elif approval_chain == "HR":
            approval_stage = "HR"
        else:  # MANAGER, MANAGER_THEN_HR, or MANAGER_THEN_HOD_THEN_HR
            from hrms.modules.employee.service import EmployeeAssignmentService

            assignment_service = EmployeeAssignmentService(self._session)
            employee_assignment = await assignment_service.get_assignment_as_of(
                company_id, employee_id, body.start_date
            )
            resolved_manager_id = (
                employee_assignment.reporting_manager_id if employee_assignment else None
            )
            if (
                approval_chain == "MANAGER_THEN_HOD_THEN_HR"
                and employee_assignment is not None
                and employee_assignment.department_id is not None
            ):
                from hrms.modules.organisation.repository import OrganisationRepository

                department = await OrganisationRepository().get_department(
                    self._session,
                    company_id=company_id,
                    department_id=employee_assignment.department_id,
                )
                head_id = department.head_employee_id if department else None
                # An employee who is their own department's head can't review their own
                # application (self-approval is always blocked, no escape hatch) — treating this
                # as "no HOD resolved" for this application lets it fall through to HR instead of
                # getting permanently stuck (LD-23), same posture as any other resolution gap.
                resolved_department_head_id = head_id if head_id != employee_id else None

            # LD-05/LD-23: resolution failure never blocks submission and never auto-approves —
            # it drops that stage from this application's effective sequence, HR is always the
            # guaranteed backstop.
            sequence = effective_stage_sequence(
                approval_chain,
                manager_id=resolved_manager_id,
                department_head_id=resolved_department_head_id,
            )
            approval_stage = sequence[0]

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
            "expected_delivery_date": body.expected_delivery_date,
            "status": "SUBMITTED",
            "approval_chain": approval_chain,
            "approval_stage": approval_stage,
            "resolved_approver_manager_id": resolved_manager_id,
            "resolved_department_head_id": resolved_department_head_id,
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
        manager_stage_chains = ("MANAGER", "MANAGER_THEN_HR", "MANAGER_THEN_HOD_THEN_HR")
        if approval_chain in manager_stage_chains and resolved_manager_id is None:
            await self._record_action(
                company_id=company_id,
                leave_application_id=application_id,
                action="APPROVER_UNRESOLVED",
                actor_user_id=None,
                actor_employee_id=None,
                stage="MANAGER",
                comment="No manager resolved as of the start date; routed to the next stage",
            )
        if approval_chain == "MANAGER_THEN_HOD_THEN_HR" and resolved_department_head_id is None:
            await self._record_action(
                company_id=company_id,
                leave_application_id=application_id,
                action="APPROVER_UNRESOLVED",
                actor_user_id=None,
                actor_employee_id=None,
                stage="HOD",
                comment=(
                    "No department head resolved as of the start date; routed to the next stage"
                ),
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
        elif row.approval_stage == "HOD":
            if caller_employee_id is None or caller_employee_id != row.resolved_department_head_id:
                raise LeaveApplicationApproverMismatchError()
        else:  # HR
            if DataScopeLevel.COMPANY not in scope.levels:
                raise LeaveApplicationApproverMismatchError(
                    "HR-stage approval requires a company-wide LEAVE.APPLICATION_APPROVE grant"
                )
        return row

    @logged_operation("leave.application.approve")
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
        await self._ensure_period_open(company_id, row.employee_id, row.start_date, row.end_date)
        return await self._approve_internal(
            company_id,
            row,
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            reviewer_comment=body.reviewer_comment,
            expected_version=expected_version,
            excess_as_lop=body.excess_as_lop,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @logged_operation("leave.application.reject")
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
        before_read = await self._read(row, company_id=company_id)
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
            before=leave_application_to_audit_dict(before_read),
            after=leave_application_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_active_leave_after(
        self, company_id: UUID, employee_id: UUID, after_date: date
    ) -> list[dict[str, str]]:
        """LM-15 - submitted or approved leave with a date after `after_date`, as plain
        id/date/status facts for the employment module's termination guard."""
        rows = await self._repo.list_active_ending_after(
            self._session, company_id=company_id, employee_id=employee_id, after_date=after_date
        )
        return [
            {
                "leave_application_id": str(row.id),
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "status": row.status,
            }
            for row in rows
        ]

    async def list_pending_manager_stage_ids(
        self, company_id: UUID, employee_id: UUID, *, excluding_manager_id: UUID | None
    ) -> list[UUID]:
        """Ids of this employee's applications that are waiting on a manager's decision and are
        snapshotted to someone other than `excluding_manager_id` - what the employment module
        warns about before a reporting-manager change. Plain ids, no application data."""
        return await self._repo.list_pending_manager_stage_ids(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            excluding_manager_id=excluding_manager_id,
        )

    async def _approver_ineligibility(self, company_id: UUID, employee_id: UUID) -> str | None:
        """Why this employee cannot act as an approver today, or `None` when they can. The same
        facts the approve route itself relies on: an employee record, an employment covering
        today, a linked login whose company membership is active, and the
        `LEAVE.APPLICATION_APPROVE` grant (the permission query only counts an ACTIVE membership,
        so a deactivated account holds no codes)."""
        from hrms.core.rbac.service import RbacService
        from hrms.modules.employee.service import EmployeeService, EmploymentService

        employee_service = EmployeeService(self._session)
        try:
            employee = await employee_service.get_employee(company_id, employee_id)
        except NotFoundError:
            return "APPROVER_NOT_FOUND"
        if not employee.is_active:
            return "APPROVER_INACTIVE"
        today = await self._business_today(company_id)
        if (
            await EmploymentService(self._session).get_employment_as_of(
                company_id, employee_id, today
            )
            is None
        ):
            return "APPROVER_NOT_EMPLOYED"
        user_id = await employee_service.get_user_id_for_employee(company_id, employee_id)
        if user_id is None:
            return "APPROVER_HAS_NO_LOGIN"
        if LEAVE_APPLICATION_APPROVE_CODE not in await RbacService(
            self._session
        ).get_permission_codes(user_id, company_id):
            return "APPROVER_CANNOT_APPROVE_LEAVE"
        return None

    async def reassign_approver(
        self,
        company_id: UUID,
        application_id: UUID,
        body: LeaveApplicationReassignInput,
        *,
        scope: DataScope,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveApplicationRead:
        """Decision 13 - HR (company-wide `LEAVE.APPLICATION_REASSIGN`) hands a pending MANAGER or
        HOD stage to another approver when the current one can no longer act. Changes only who
        the stage waits for: leave dates, balance and ledger are untouched, no automatic
        re-resolution from the org chart happens, and afterwards only the newly assigned person
        can act on that stage (the stage check compares the caller to the snapshotted id this
        rewrites). Version-guarded, so a stale client gets the normal 409."""
        if DataScopeLevel.COMPANY not in scope.levels:
            raise PermissionDeniedError(
                "Reassigning an approver requires a company-wide LEAVE.APPLICATION_REASSIGN grant"
            )
        row = await self._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if row is None:
            raise LeaveApplicationNotFoundError()
        if row.status != "SUBMITTED" or row.approval_stage not in ("MANAGER", "HOD"):
            raise LeaveApproverReassignNotApplicableError()
        if row.version != expected_version:
            raise await self._stale_error(company_id, application_id)

        stage = row.approval_stage
        field = (
            "resolved_approver_manager_id" if stage == "MANAGER" else "resolved_department_head_id"
        )
        current_approver_id = getattr(row, field)
        new_approver_id = body.new_approver_employee_id
        if current_approver_id is not None and (
            await self._approver_ineligibility(company_id, current_approver_id) is None
        ):
            raise LeaveApproverStillEligibleError()
        if new_approver_id == row.employee_id:
            raise LeaveApplicationSelfApprovalNotAllowedError()
        if new_approver_id == current_approver_id:
            raise LeaveReassignApproverNotEligibleError("APPROVER_UNCHANGED")
        problem = await self._approver_ineligibility(company_id, new_approver_id)
        if problem is not None:
            raise LeaveReassignApproverNotEligibleError(problem)

        before_read = await self._read(row, company_id=company_id)
        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            application_id=application_id,
            values={field: new_approver_id},
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, application_id)

        await self._record_action(
            company_id=company_id,
            leave_application_id=application_id,
            action="APPROVER_REASSIGNED",
            actor_user_id=actor_user_id,
            actor_employee_id=None,
            stage=stage,
            comment=body.reason,
        )
        read = await self._read(updated, company_id=company_id)
        # Structured only (decision 19): the reason lives on the action timeline entry above.
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_APPLICATION_APPROVER_REASSIGNED",
            entity_type="leave_application",
            entity_id=application_id,
            before={
                **leave_application_to_audit_dict(before_read),
                "stage": stage,
                "approver_employee_id": str(current_approver_id) if current_approver_id else None,
            },
            after={
                **leave_application_to_audit_dict(read),
                "stage": stage,
                "approver_employee_id": str(new_approver_id),
            },
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
        excess_as_lop: bool = False,
    ) -> LeaveApplicationRead:
        # D3 - employment may have changed since submission. Lock first (the same lock a
        # termination takes), then re-validate the whole range; a failure rolls this transaction
        # back, so nothing is approved or debited.
        await self._repo.lock_employee_leave_dates(
            self._session, company_id=company_id, employee_id=row.employee_id
        )
        await _ensure_within_employment(
            self._session,
            company_id,
            row.employee_id,
            row.start_date,
            row.end_date,
            on_approval=True,
        )
        now = datetime.now(UTC)
        # LD-23: generalizes the old hardcoded "MANAGER_THEN_HR + at MANAGER stage -> not final"
        # check into a lookup against this application's own effective stage sequence
        # (recomputed from its snapshotted resolved_approver_manager_id/
        # resolved_department_head_id — deterministic, no re-resolution against current
        # org-chart state).
        next_stage = next_approval_stage(
            row.approval_chain,
            row.approval_stage,
            manager_id=row.resolved_approver_manager_id,
            department_head_id=row.resolved_department_head_id,
        )
        is_final_stage = next_stage is None
        values: dict[str, Any] = (
            {
                "status": "APPROVED",
                "approval_stage": None,
                "reviewed_by_user_id": actor_user_id,
                "reviewed_at": now,
                "reviewer_comment": reviewer_comment,
            }
            if is_final_stage
            else {"approval_stage": next_stage}
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
                stage=row.approval_stage,
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
            excess_as_lop=excess_as_lop,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _cover_from_balance(
        self, company_id: UUID, row: Any, days: list[Any], *, excess_as_lop: bool
    ) -> list[Any]:
        """PAY-010 / decision 9 — re-checks the balance at final approval, under a lock held
        until this transaction commits, so two approvals can never both spend the same balance.
        Returns the days that cannot be covered (empty when the balance suffices). Uncovered
        days are the *latest* ones, whole days only: a day the remaining balance only partly
        covers is LOP in full and the partial balance stays unused."""
        await self._ledger_repo.lock_balance(
            self._session,
            company_id=company_id,
            employee_id=row.employee_id,
            leave_type_id=row.leave_type_id,
        )
        balance = await self._ledger_repo.get_balance(
            self._session,
            company_id=company_id,
            employee_id=row.employee_id,
            leave_type_id=row.leave_type_id,
        )
        policy_version = await self._policy_repo.get_version_by_id(
            self._session, company_id=company_id, version_id=row.leave_policy_version_id
        )
        available = balance + _negative_floor(policy_version)
        if row.total_days <= available:
            return []
        if not excess_as_lop:
            raise LeaveApplicationBalanceShortfallError(
                balance=balance,
                available=available,
                requested=row.total_days,
                shortfall=row.total_days - max(available, Decimal("0.00")),
            )
        remaining = max(available, Decimal("0.00"))
        uncovered: list[Any] = []
        for day in days:
            if not uncovered and day.fraction <= remaining:
                remaining -= day.fraction
            else:
                uncovered.append(day)
        return uncovered

    async def _apply_approval(
        self,
        company_id: UUID,
        row: Any,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        excess_as_lop: bool = False,
    ) -> LeaveApplicationRead:
        """LD-12: runs inside the same transaction as the approval write that preceded it — if
        `LeaveProjectionService.sync()` refuses any single day (its attendance period is
        already closed), the whole transaction (including the `status='APPROVED'` write) rolls
        back with the exception, mirroring
        `AttendanceRegularizationRequestService._apply_correction`'s exact posture. Never a
        partially-approved, partially-synced application."""
        from hrms.modules.attendance.schemas import LeaveProjectionSync
        from hrms.modules.attendance.service import LeaveProjectionService

        # PRA-15: the projection sync below is read-then-insert per date. Two approvals for the
        # same employee (typically different leave types, which the per-type balance lock does not
        # order) could both read an empty date and both insert. Same lock as submission.
        await self._repo.lock_employee_leave_dates(
            self._session, company_id=company_id, employee_id=row.employee_id
        )
        # Attendance finalisation freezes days from what it read; take the shared side of its lock
        # so it cannot run between this approval's recalculation and its commit (and so a
        # finalisation already running finishes first, after which the period check in the
        # projection sync sees the period closed). Always AFTER the per-employee date lock, so
        # that every path (submit with an AUTO chain, approve) acquires them in one order.
        await lock_attendance_period_close(self._session, company_id, exclusive=False)
        leave_type = await self._type_repo.get(
            self._session, company_id=company_id, leave_type_id=row.leave_type_id
        )
        days = await self._day_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=row.id
        )
        lop_day_ids: set[UUID] = set()
        if leave_type is not None and leave_type.requires_balance:
            uncovered = await self._cover_from_balance(
                company_id, row, days, excess_as_lop=excess_as_lop
            )
            if uncovered:
                lop_day_ids = {day.id for day in uncovered}
                lop_days = sum((day.fraction for day in uncovered), Decimal("0.00"))
                now = datetime.now(UTC)
                await self._day_repo.mark_lop(
                    self._session, company_id=company_id, day_ids=list(lop_day_ids), now=now
                )
                # Same version-free follow-up posture as `set_projection_id`: this transaction
                # already owns the row (it just wrote `status='APPROVED'` under `If-Match`).
                row = await self._repo.set_lop_days(
                    self._session, company_id=company_id, application_id=row.id, lop_days=lop_days
                )
                await self._record_action(
                    company_id=company_id,
                    leave_application_id=row.id,
                    action="EXCESS_AS_LOP",
                    actor_user_id=actor_user_id,
                    actor_employee_id=None,
                    stage=None,
                    comment=f"{lop_days} day(s) approved as loss of pay (balance shortfall)",
                )
        # LEAVE.APPLICATION_APPROVE already gated this action — this cross-module call is not
        # re-deriving Attendance's own RBAC, just satisfying `sync()`'s required scope param
        # (mirrors L2's `create_adjustment` "the permission grant itself is the gate" posture).
        full_scope = DataScope(levels=frozenset({DataScopeLevel.COMPANY}))
        projection_service = LeaveProjectionService(self._session)

        for day in days:
            synced = await projection_service.sync(
                company_id,
                # LM-14: identifiers only; the projection derives type/fraction/half/paid from
                # this application's own approved day rows (is_lop was written just above).
                LeaveProjectionSync(
                    employee_id=row.employee_id,
                    attendance_date=day.calendar_date,
                    leave_application_id=row.id,
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

        # The actual balance deduction — skipped entirely for a LOP-style type (LD-02), and
        # never for days approved as LOP (PAY-010).
        if (
            leave_type is not None
            and leave_type.requires_balance
            and row.total_days - row.lop_days > 0
        ):
            await self._ledger_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": row.employee_id,
                    "leave_type_id": row.leave_type_id,
                    "entry_type": "APPLICATION",
                    "amount": -(row.total_days - row.lop_days),
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

    @logged_operation("leave.application.cancel")
    async def cancel(
        self,
        company_id: UUID,
        application_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        reason: str | None = None,
        can_cancel_approved: bool = False,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveApplicationRead:
        """`SUBMITTED` (pre-approval) mirrors `AttendanceRegularizationRequestService.cancel`
        — the original submitter (or the employee it is for) withdraws it, no side effects.
        `APPROVED` (LD-13) also reverses the ledger debit and every synced `LeaveDayProjection`,
        and follows decision 10 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`): the employee may
        cancel their own approved leave only before it starts; after that only a holder of
        `LEAVE.APPLICATION_CANCEL_APPROVED` (company scope, HR) may, with a mandatory reason.
        Managers never cancel approved leave."""
        row = await self._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if row is None:
            raise LeaveApplicationNotFoundError()
        await self._ensure_employee_visible(
            company_id, row.employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        if row.status not in ("SUBMITTED", "APPROVED"):
            raise LeaveApplicationInvalidTransitionError()
        reason = reason.strip() if reason and reason.strip() else None
        is_own = caller_employee_id is not None and caller_employee_id == row.employee_id
        if row.status == "SUBMITTED":
            if row.submitted_by_user_id != actor_user_id and not is_own:
                raise PermissionDeniedError(
                    "Only the submitter or the employee may withdraw this application"
                )
        else:
            started = await self._business_today(company_id) >= row.start_date
            if can_cancel_approved:
                if started and reason is None:
                    raise LeaveApplicationCancelReasonRequiredError()
            elif not is_own:
                raise PermissionDeniedError("Only HR may cancel another employee's approved leave")
            elif started:
                raise PermissionDeniedError("This leave has already started — ask HR to cancel it")
            # PD-3 — withdrawing a still-pending application is always allowed (it never
            # touched attendance); reversing an approved one inside a closed period is not.
            await self._ensure_period_open(
                company_id, row.employee_id, row.start_date, row.end_date
            )

        before_read = await self._read(row, company_id=company_id)
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
                "cancellation_reason": reason,
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
            comment=reason,
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
            before=leave_application_to_audit_dict(before_read),
            after=leave_application_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _ensure_period_open(
        self, company_id: UUID, employee_id: UUID, start_date: date, end_date: date
    ) -> None:
        """PD-3 — closing the attendance period locks leave for its dates. Checked up front so
        the caller gets a leave-specific error rather than `LeaveProjectionService`'s
        per-day `ATTENDANCE_PERIOD_CLOSED` halfway through the write. Decision 14 — only the
        employee's own legal entity's period counts."""
        from hrms.modules.attendance.service import AttendanceService

        closed = await AttendanceService(self._session).closed_period_overlapping(
            company_id, employee_id, start_date, end_date
        )
        if closed is not None:
            raise LeaveApplicationPeriodClosedError(period_start=closed[0], period_end=closed[1])

    async def _company_profile(self, company_id: UUID) -> Any:
        from hrms.modules.organisation.service import OrganisationService

        return await OrganisationService(self._session).get_company_profile(company_id)

    async def _business_today(self, company_id: UUID) -> date:
        return business_today((await self._company_profile(company_id)).timezone)

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

        # Same ordering against attendance finalisation as `_apply_approval`.
        await lock_attendance_period_close(self._session, company_id, exclusive=False)
        # LM-04 / decision 11 — credits back exactly what the ledger shows this application
        # debited (`_apply_approval` never debits the LOP days, PAY-010). Whether a debit happened
        # is a fact about the ledger, not about the leave type's *current* `requires_balance`,
        # which says nothing about what the application did when it was approved. An application
        # that never debited (a LOP-style type, all days LOP, a pre-approval-era row) credits
        # nothing, and one that did debit is always made whole.
        debited = -await self._ledger_repo.sum_for_reference(
            self._session,
            company_id=company_id,
            employee_id=row.employee_id,
            entry_type="APPLICATION",
            reference_id=row.id,
        )
        already_reversed = await self._ledger_repo.exists_with_reference(
            self._session,
            company_id=company_id,
            entry_type="ADJUSTMENT",
            reference_id=row.id,
        )
        if debited > 0 and not already_reversed:
            await self._ledger_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": row.employee_id,
                    "leave_type_id": row.leave_type_id,
                    "entry_type": "ADJUSTMENT",
                    "amount": debited,
                    "effective_date": await self._business_today(company_id),
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
        page: PageParams,
    ) -> tuple[list[LeaveApplicationRead], int]:
        """Pagination happens *after* `DataScope` narrows `visible_ids` (API-01 §5/§10) — the
        `LIMIT`/`OFFSET` only ever slides across rows already inside the caller's own scope, so
        `page`/`per_page` can't be used to reach applications the caller couldn't otherwise see.
        Day/action records are then batch-loaded for just this page's application IDs
        (`_read_many`), not per-row — the N+1 fix (API-01 §5)."""
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
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._repo.count_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        reads = await self._read_many(rows, company_id=company_id)
        return reads, total

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

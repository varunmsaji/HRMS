"""Business logic for the attendance module — the public interface for other modules.

One service class per Module Standard, covering all three policy families (Attendance/Overtime/
Regularization — WD-03 locked as separate identities, not one mega-policy) since they share
identical CRUD/versioning/publish mechanics. Mirrors `organisation.service.OrganisationService`'s
`ShiftVersion` methods (create/list/get/update/discard/publish/resolve_as_of) three times over,
plus policy-resolution delegation (§16/§19 step 7)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import get_settings
from hrms.core.db.locks import lock_attendance_period_close, lock_employee_leave_dates
from hrms.core.db.session import session_scope
from hrms.core.db.timeouts import bounded_waits, is_wait_timeout
from hrms.core.errors.base import NotFoundError, PermissionDeniedError, ValidationError
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.observability.operations import logged_operation
from hrms.core.observability.security_events import security_event
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.attendance import calculation as calc
from hrms.modules.attendance.break_repository import BreakEventRepository
from hrms.modules.attendance.exceptions import (
    AttendanceDayLockedError,
    AttendancePeriodClosedError,
    AttendancePeriodFinalizationBlockedError,
    AttendancePeriodInvalidTransitionError,
    AttendancePeriodLegalEntityInvalidError,
    AttendancePeriodNotFoundError,
    AttendancePeriodOverlapError,
    AttendancePeriodPayrollFinalisedError,
    AttendanceQueueUnavailableError,
    AttendanceRangeInFutureError,
    AttendanceSummaryReconciliationError,
    DuplicatePunchIdempotencyKeyError,
    EmployeeTerminatedError,
    FaceVerificationRequiredError,
    FuturePunchTimeError,
    InvalidPolicyBandError,
    InvalidPolicyRateRowError,
    InvalidRegularizationAllowedTypeError,
    LeaveProjectionApplicationNotApprovedError,
    LeaveProjectionApplicationNotFoundError,
    LeaveProjectionDateNotInApplicationError,
    LeaveProjectionNotFoundError,
    LeaveProjectionOutsideEmploymentError,
    LeaveProjectionOverlapError,
    OutsideShiftWindowError,
    OvertimeApproverMismatchError,
    OvertimeInvalidTransitionError,
    OvertimeRecordNotFoundError,
    OvertimeSelfApprovalNotAllowedError,
    PolicyCodeAlreadyExistsError,
    PolicyDraftAlreadyExistsError,
    PolicyPublishIncompleteError,
    PolicyVersionNotDraftError,
    PolicyVersionNotFoundForDateError,
    PolicyVersionOverlapError,
    PolicyVersionPreviousVersionRequiredError,
    PunchAlreadyRecordedError,
    PunchTimeBeforeEmploymentError,
    PunchTooSoonError,
    RegularizationApproverMismatchError,
    RegularizationAttachmentRequiredError,
    RegularizationBlockedByLockError,
    RegularizationDuplicateActiveRequestError,
    RegularizationInvalidTransitionError,
    RegularizationNotPermittedError,
    RegularizationPolicyNotResolvedError,
    RegularizationReasonRequiredError,
    RegularizationRequestLimitExceededError,
    RegularizationRequestNotFoundError,
    RegularizationSelfApprovalNotAllowedError,
    RegularizationTypeNotAllowedError,
    RegularizationWindowExceededError,
    ShiftRosterDateConflictError,
    ShiftRosterNotFoundError,
    StaleAttendancePeriodResourceError,
    StaleLeaveProjectionResourceError,
    StaleOvertimeRecordResourceError,
    StalePolicyResourceError,
    StaleRegularizationRequestResourceError,
    StaleShiftRosterResourceError,
    WorkOnLeaveNotFlaggedError,
)
from hrms.modules.attendance.geofence_service import (
    GEOFENCED_SOURCES,
    GeofenceEvaluation,
    GeofenceService,
)
from hrms.modules.attendance.models import (
    AttendanceDay,
    AttendancePeriod,
    AttendancePolicy,
    AttendanceRegularizationRequest,
    LeaveDayProjection,
    OvertimePolicy,
    OvertimePolicyRateRow,
    OvertimePolicyVersion,
    OvertimeRecord,
    Punch,
    RegularizationPolicy,
)
from hrms.modules.attendance.repository import (
    AttendanceBreakRepository,
    AttendanceDayRepository,
    AttendancePeriodActionRepository,
    AttendancePeriodRepository,
    AttendancePeriodSummaryRepository,
    AttendancePolicyRepository,
    AttendanceRegularizationActionRepository,
    AttendanceRegularizationRequestedPunchRepository,
    AttendanceRegularizationRequestRepository,
    CompOffFactRow,
    FaceProfileRepository,
    LeaveDayProjectionRepository,
    OvertimeActionRepository,
    OvertimePolicyRepository,
    OvertimeRecordRepository,
    PunchRepository,
    RegularizationPolicyRepository,
    ShiftRosterRepository,
)
from hrms.modules.attendance.resolution import PolicyResolutionService
from hrms.modules.attendance.schemas import (
    AttendanceDayRead,
    AttendancePeriodBlockingReason,
    AttendancePeriodCreate,
    AttendancePeriodRead,
    AttendancePeriodReopenInput,
    AttendancePeriodSummaryRead,
    AttendancePeriodValidationRead,
    AttendancePolicyCreate,
    AttendancePolicyFormContext,
    AttendancePolicyRead,
    AttendancePolicyUpdate,
    AttendancePolicyVersionCreate,
    AttendancePolicyVersionPublishRequest,
    AttendancePolicyVersionRead,
    AttendancePolicyVersionUpdate,
    AttendanceRangeCalculateInput,
    AttendanceRangeCalculateQueued,
    LeaveDayProjectionRead,
    LeaveProjectionCancelInput,
    LeaveProjectionSync,
    OvertimePolicyCreate,
    OvertimePolicyRead,
    OvertimePolicyUpdate,
    OvertimePolicyVersionCreate,
    OvertimePolicyVersionPublishRequest,
    OvertimePolicyVersionRead,
    OvertimePolicyVersionUpdate,
    OvertimeRecordRead,
    OvertimeReviewInput,
    PolicyResolutionRead,
    PunchLocation,
    PunchRead,
    RegularizationPolicyCreate,
    RegularizationPolicyRead,
    RegularizationPolicyUpdate,
    RegularizationPolicyVersionCreate,
    RegularizationPolicyVersionPublishRequest,
    RegularizationPolicyVersionRead,
    RegularizationPolicyVersionUpdate,
    RegularizationRequestCreate,
    RegularizationRequestRead,
    RegularizationReviewInput,
    ShiftRosterBulkCreate,
    ShiftRosterCreate,
    ShiftRosterRead,
    ShiftRosterUpdate,
    WorkOnLeaveKeepLeaveInput,
    _format_timestamp,
    _parse_time,
    attendance_day_to_audit_dict,
    attendance_day_to_read,
    attendance_period_summary_to_read,
    attendance_period_to_audit_dict,
    attendance_period_to_read,
    attendance_policy_to_audit_dict,
    attendance_policy_to_read,
    attendance_policy_version_to_audit_dict,
    attendance_policy_version_to_read,
    build_attendance_policy_update_values,
    build_attendance_policy_version_update_values,
    build_overtime_policy_update_values,
    build_overtime_policy_version_update_values,
    build_regularization_policy_update_values,
    build_regularization_policy_version_update_values,
    build_shift_roster_update_values,
    leave_day_projection_to_audit_dict,
    leave_day_projection_to_read,
    overtime_policy_to_audit_dict,
    overtime_policy_to_read,
    overtime_policy_version_to_audit_dict,
    overtime_policy_version_to_read,
    overtime_record_to_audit_dict,
    overtime_record_to_read,
    punch_to_audit_dict,
    punch_to_read,
    regularization_policy_to_audit_dict,
    regularization_policy_to_read,
    regularization_policy_version_to_audit_dict,
    regularization_policy_version_to_read,
    regularization_request_to_audit_dict,
    regularization_request_to_read,
    shift_roster_to_audit_dict,
    shift_roster_to_read,
)
from hrms.modules.attendance.shift_window import (
    ShiftSpan,
    ShiftWindowDecision,
    combine_shift_window_decisions,
    evaluate_shift_window,
)
from hrms.shared.auto_code import next_auto_code
from hrms.shared.business_time import business_today
from hrms.shared.pagination import PageParams
from hrms.shared.timezone import TimezoneConfigurationError, resolve_zoneinfo

_logger = get_logger(__name__)

# Decision 13 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — comp-off lifetime when the overtime
# policy leaves `comp_off_expiry_days` unset.
DEFAULT_COMP_OFF_EXPIRY_DAYS = 60


def _validate_bands(bands: list[Any], *, required: bool, field: str) -> None:
    """Ordered, non-overlapping (architecture §11.1) — validated here at publish time, not a DB
    GiST constraint, so a draft's full-replace PATCH transaction is never mid-transaction-invalid
    (see `models.py` module docstring)."""
    if required and not bands:
        raise InvalidPolicyBandError(
            f"At least one {field[:-1]} is required to publish", field=field
        )
    ordered = sorted(bands, key=lambda b: b.min_minutes)
    for index, band in enumerate(ordered):
        if index + 1 >= len(ordered):
            continue
        next_band = ordered[index + 1]
        this_upper = band.max_minutes
        if this_upper is not None and this_upper >= next_band.min_minutes:
            raise InvalidPolicyBandError(
                f"{field} must not overlap: band starting at {band.min_minutes} overlaps the "
                f"band starting at {next_band.min_minutes}",
                field=field,
            )
        if this_upper is None and index != len(ordered) - 1:
            raise InvalidPolicyBandError(
                f"Only the last {field[:-1]} may leave max_minutes open-ended", field=field
            )


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()
        self._attendance_repo = AttendancePolicyRepository()
        self._overtime_repo = OvertimePolicyRepository()
        self._regularization_repo = RegularizationPolicyRepository()
        self._resolution = PolicyResolutionService(session)

    # -----------------------------------------------------------------
    # Attendance Policy — identity
    # -----------------------------------------------------------------

    async def create_attendance_policy(
        self,
        company_id: UUID,
        body: AttendancePolicyCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicyRead:
        now = datetime.now(UTC)
        policy_id = uuid4()
        try:
            row = await self._attendance_repo.insert_policy(
                self._session,
                data={
                    "id": policy_id,
                    "company_id": company_id,
                    "name": body.name,
                    "code": await next_auto_code(
                        self._session,
                        model=AttendancePolicy,
                        company_id=company_id,
                        prefix="ATTP",
                    ),
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise PolicyCodeAlreadyExistsError() from exc

        read = attendance_policy_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_POLICY_CREATED",
            entity_type="attendance_policy",
            entity_id=policy_id,
            after=attendance_policy_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_attendance_policies(
        self, company_id: UUID, *, assignable_only: bool = False
    ) -> list[AttendancePolicyRead]:
        rows = await self._attendance_repo.list_policies(
            self._session, company_id=company_id, assignable_only=assignable_only
        )
        return [attendance_policy_to_read(r) for r in rows]

    async def list_attendance_policies_with_status(
        self, company_id: UUID, *, assignable_only: bool = False
    ) -> list[AttendancePolicyRead]:
        from hrms.modules.organisation.repository import PolicyAssignmentRepository

        policies = await self.list_attendance_policies(company_id, assignable_only=assignable_only)
        versions = await self._attendance_repo.list_open_and_draft_versions(
            self._session, company_id=company_id
        )
        assignments = await PolicyAssignmentRepository().list_assignments(
            self._session,
            company_id=company_id,
            policy_kind="ATTENDANCE_POLICY",
            current_only=True,
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

    async def attendance_policy_form_context(self, company_id: UUID) -> AttendancePolicyFormContext:
        from hrms.modules.organisation.repository import ShiftVersionRepository

        return AttendancePolicyFormContext(
            shift_types_in_use=await ShiftVersionRepository().list_open_shift_types(
                self._session, company_id=company_id
            )
        )

    async def get_attendance_policy(
        self, company_id: UUID, policy_id: UUID
    ) -> AttendancePolicyRead:
        row = await self._attendance_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return attendance_policy_to_read(row)

    async def update_attendance_policy(
        self,
        company_id: UUID,
        policy_id: UUID,
        patch: AttendancePolicyUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicyRead:
        row = await self._attendance_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = attendance_policy_to_read(row)

        values = build_attendance_policy_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            try:
                result = await self._attendance_repo.update_policy(
                    self._session,
                    company_id=company_id,
                    policy_id=policy_id,
                    values=values,
                    expected_version=expected_version,
                    now=now,
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise PolicyCodeAlreadyExistsError() from exc
            if result is None:
                latest = await self._attendance_repo.get_policy(
                    self._session, company_id=company_id, policy_id=policy_id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                raise StalePolicyResourceError(
                    "This policy has been modified by another request",
                    current=attendance_policy_to_audit_dict(attendance_policy_to_read(latest)),
                )
            updated = result

        after_read = attendance_policy_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_POLICY_UPDATED",
            entity_type="attendance_policy",
            entity_id=policy_id,
            before=attendance_policy_to_audit_dict(before_read),
            after=attendance_policy_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    # -----------------------------------------------------------------
    # Attendance Policy — versions
    # -----------------------------------------------------------------

    async def create_attendance_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        body: AttendancePolicyVersionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicyVersionRead:
        policy = await self._attendance_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        existing_draft = await self._attendance_repo.get_open_draft(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if existing_draft is not None:
            raise PolicyDraftAlreadyExistsError()

        now = datetime.now(UTC)
        version_id = uuid4()
        row = await self._attendance_repo.insert_version(
            self._session,
            data={
                "id": version_id,
                "company_id": company_id,
                "policy_id": policy_id,
                "status": "DRAFT",
                "version": 1,
                "effective_from": body.effective_from,
                "effective_to": None,
                "grace_in_minutes": body.grace_in_minutes,
                "grace_out_minutes": body.grace_out_minutes,
                "early_in_allowance_minutes": body.early_in_allowance_minutes,
                "punch_rounding": body.punch_rounding,
                "rounding_minutes": body.rounding_minutes,
                "missing_punch_behaviour": body.missing_punch_behaviour,
                "auto_close_after_minutes": body.auto_close_after_minutes,
                "auto_close_uses_shift_end": body.auto_close_uses_shift_end,
                "missing_shift_behaviour": body.missing_shift_behaviour,
                "half_day_split": body.half_day_split,
                "half_day_boundary_minutes": body.half_day_boundary_minutes,
                "multi_punch_mode": body.multi_punch_mode,
                "duplicate_punch_window_seconds": body.duplicate_punch_window_seconds,
                "core_hours_breach_behaviour": body.core_hours_breach_behaviour,
                "early_out_uses_core_end": body.early_out_uses_core_end,
                "split_shift_block_mandatory": body.split_shift_block_mandatory,
                "split_shift_missed_block_behaviour": body.split_shift_missed_block_behaviour,
                "split_shift_allow_hours_compensation": body.split_shift_allow_hours_compensation,
                "wfh_requires_punch": body.wfh_requires_punch,
                "on_duty_requires_punch": body.on_duty_requires_punch,
                "wfh_uses_shift_hours": body.wfh_uses_shift_hours,
                "work_on_leave_behaviour": body.work_on_leave_behaviour,
                "excess_break_behaviour": body.excess_break_behaviour,
                "late_count_window": body.late_count_window,
                "lates_to_half_day_count": body.lates_to_half_day_count,
                "early_departure_requires_approval": body.early_departure_requires_approval,
                "excess_break_count_window": body.excess_break_count_window,
                "excess_break_days_to_half_day_count": body.excess_break_days_to_half_day_count,
                "incomplete_at_lock_behaviour": body.incomplete_at_lock_behaviour,
                "geofence_mode": body.geofence_mode,
                "geofence_max_accuracy_m": body.geofence_max_accuracy_m,
                "geofence_max_age_seconds": body.geofence_max_age_seconds,
                "publish_reason": None,
                "published_at": None,
                "published_by": None,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
        )

        hour_bands = await self._attendance_repo.replace_hour_bands(
            self._session,
            company_id=company_id,
            policy_version_id=version_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "policy_version_id": version_id,
                    "min_minutes": b.min_minutes,
                    "max_minutes": b.max_minutes,
                    "result_status": b.result_status,
                    "sort_order": b.sort_order,
                }
                for b in body.hour_bands
            ],
        )
        late_bands = await self._attendance_repo.replace_late_bands(
            self._session,
            company_id=company_id,
            policy_version_id=version_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "policy_version_id": version_id,
                    "min_minutes": b.min_minutes,
                    "max_minutes": b.max_minutes,
                    "classification": b.classification,
                    "counts_toward_cap": b.counts_toward_cap,
                    "sort_order": b.sort_order,
                }
                for b in body.late_bands
            ],
        )
        early_bands = await self._attendance_repo.replace_early_departure_bands(
            self._session,
            company_id=company_id,
            policy_version_id=version_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "policy_version_id": version_id,
                    "min_minutes": b.min_minutes,
                    "max_minutes": b.max_minutes,
                    "classification": b.classification,
                    "counts_toward_cap": b.counts_toward_cap,
                    "sort_order": b.sort_order,
                }
                for b in body.early_departure_bands
            ],
        )

        read = attendance_policy_version_to_read(row, hour_bands, late_bands, early_bands)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_POLICY_VERSION_CREATED",
            entity_type="attendance_policy_version",
            entity_id=version_id,
            after=attendance_policy_version_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_attendance_policy_versions(
        self, company_id: UUID, policy_id: UUID
    ) -> list[AttendancePolicyVersionRead]:
        policy = await self._attendance_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        versions = await self._attendance_repo.list_versions(
            self._session, company_id=company_id, policy_id=policy_id
        )
        result = []
        for v in versions:
            hour_bands = await self._attendance_repo.list_hour_bands(
                self._session, company_id=company_id, policy_version_id=v.id
            )
            late_bands = await self._attendance_repo.list_late_bands(
                self._session, company_id=company_id, policy_version_id=v.id
            )
            early_bands = await self._attendance_repo.list_early_departure_bands(
                self._session, company_id=company_id, policy_version_id=v.id
            )
            result.append(attendance_policy_version_to_read(v, hour_bands, late_bands, early_bands))
        return result

    async def _get_attendance_version_read(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> tuple[Any, AttendancePolicyVersionRead]:
        version = await self._attendance_repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        hour_bands = await self._attendance_repo.list_hour_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        late_bands = await self._attendance_repo.list_late_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        early_bands = await self._attendance_repo.list_early_departure_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        read = attendance_policy_version_to_read(version, hour_bands, late_bands, early_bands)
        return version, read

    async def get_attendance_policy_version(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> AttendancePolicyVersionRead:
        _, read = await self._get_attendance_version_read(company_id, policy_id, version_id)
        return read

    async def update_attendance_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        patch: AttendancePolicyVersionUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicyVersionRead:
        version, before_read = await self._get_attendance_version_read(
            company_id, policy_id, version_id
        )
        if version.status != "DRAFT":
            raise PolicyVersionNotDraftError()

        values = build_attendance_policy_version_update_values(patch)
        now = datetime.now(UTC)
        updated = version
        if values:
            result = await self._attendance_repo.update_version(
                self._session,
                company_id=company_id,
                policy_id=policy_id,
                version_id=version_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                _, latest_read = await self._get_attendance_version_read(
                    company_id, policy_id, version_id
                )
                raise StalePolicyResourceError(
                    "This policy version has been modified by another request",
                    current=attendance_policy_version_to_audit_dict(latest_read),
                )
            updated = result

        hour_bands = await self._attendance_repo.list_hour_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        if patch.hour_bands is not None:
            hour_bands = await self._attendance_repo.replace_hour_bands(
                self._session,
                company_id=company_id,
                policy_version_id=version_id,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "policy_version_id": version_id,
                        "min_minutes": b.min_minutes,
                        "max_minutes": b.max_minutes,
                        "result_status": b.result_status,
                        "sort_order": b.sort_order,
                    }
                    for b in patch.hour_bands
                ],
            )
        late_bands = await self._attendance_repo.list_late_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        if patch.late_bands is not None:
            late_bands = await self._attendance_repo.replace_late_bands(
                self._session,
                company_id=company_id,
                policy_version_id=version_id,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "policy_version_id": version_id,
                        "min_minutes": b.min_minutes,
                        "max_minutes": b.max_minutes,
                        "classification": b.classification,
                        "counts_toward_cap": b.counts_toward_cap,
                        "sort_order": b.sort_order,
                    }
                    for b in patch.late_bands
                ],
            )
        early_bands = await self._attendance_repo.list_early_departure_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        if patch.early_departure_bands is not None:
            early_bands = await self._attendance_repo.replace_early_departure_bands(
                self._session,
                company_id=company_id,
                policy_version_id=version_id,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "policy_version_id": version_id,
                        "min_minutes": b.min_minutes,
                        "max_minutes": b.max_minutes,
                        "classification": b.classification,
                        "counts_toward_cap": b.counts_toward_cap,
                        "sort_order": b.sort_order,
                    }
                    for b in patch.early_departure_bands
                ],
            )

        after_read = attendance_policy_version_to_read(updated, hour_bands, late_bands, early_bands)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_POLICY_VERSION_UPDATED",
            entity_type="attendance_policy_version",
            entity_id=version_id,
            before=attendance_policy_version_to_audit_dict(before_read),
            after=attendance_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def discard_attendance_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicyVersionRead:
        version, before_read = await self._get_attendance_version_read(
            company_id, policy_id, version_id
        )
        if version.status != "DRAFT":
            raise PolicyVersionNotDraftError()

        now = datetime.now(UTC)
        result = await self._attendance_repo.discard_version(
            self._session,
            company_id=company_id,
            policy_id=policy_id,
            version_id=version_id,
            expected_version=expected_version,
            now=now,
        )
        if result is None:
            _, latest_read = await self._get_attendance_version_read(
                company_id, policy_id, version_id
            )
            raise StalePolicyResourceError(
                "This policy version has been modified by another request",
                current=attendance_policy_version_to_audit_dict(latest_read),
            )

        after_read = attendance_policy_version_to_read(
            result,
            await self._attendance_repo.list_hour_bands(
                self._session, company_id=company_id, policy_version_id=version_id
            ),
            await self._attendance_repo.list_late_bands(
                self._session, company_id=company_id, policy_version_id=version_id
            ),
            await self._attendance_repo.list_early_departure_bands(
                self._session, company_id=company_id, policy_version_id=version_id
            ),
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_POLICY_VERSION_DISCARDED",
            entity_type="attendance_policy_version",
            entity_id=version_id,
            before=attendance_policy_version_to_audit_dict(before_read),
            after=attendance_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def publish_attendance_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        body: AttendancePolicyVersionPublishRequest,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicyVersionRead:
        """Insert-new/close-previous — mirrors `publish_shift_version` exactly (two concurrency
        tokens: the draft's own `If-Match`, and `expected_previous_version` for the currently
        open published row, required only when one exists)."""
        draft = await self._attendance_repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if draft is None:
            raise NotFoundError("Resource not found")
        if draft.status != "DRAFT":
            raise PolicyVersionNotDraftError()
        if draft.effective_from is None:
            raise PolicyPublishIncompleteError("effective_from is required to publish")

        hour_bands = await self._attendance_repo.list_hour_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        late_bands = await self._attendance_repo.list_late_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        early_bands = await self._attendance_repo.list_early_departure_bands(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        before_read = attendance_policy_version_to_read(draft, hour_bands, late_bands, early_bands)

        _validate_bands(hour_bands, required=True, field="hour_bands")
        _validate_bands(late_bands, required=False, field="late_bands")
        _validate_bands(early_bands, required=False, field="early_departure_bands")

        current = await self._attendance_repo.get_current_published(
            self._session, company_id=company_id, policy_id=policy_id
        )
        now = datetime.now(UTC)
        if current is not None:
            assert current.effective_from is not None
            if draft.effective_from <= current.effective_from:
                raise PolicyPublishIncompleteError(
                    "effective_from must be after the currently published version's effective_from"
                )
            if body.expected_previous_version is None:
                raise PolicyVersionPreviousVersionRequiredError()
            closed = await self._attendance_repo.close_version(
                self._session,
                company_id=company_id,
                version_id=current.id,
                effective_to=draft.effective_from - timedelta(days=1),
                expected_version=body.expected_previous_version,
                now=now,
            )
            if closed is None:
                raise StalePolicyResourceError(
                    "The currently published policy version has been modified by another request",
                    current={},
                )

        try:
            updated = await self._attendance_repo.update_version(
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
            raise PolicyVersionOverlapError() from exc

        if updated is None:
            _, latest_read = await self._get_attendance_version_read(
                company_id, policy_id, version_id
            )
            raise StalePolicyResourceError(
                "This policy version has been modified by another request",
                current=attendance_policy_version_to_audit_dict(latest_read),
            )

        after_read = attendance_policy_version_to_read(updated, hour_bands, late_bands, early_bands)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_POLICY_VERSION_PUBLISHED",
            entity_type="attendance_policy_version",
            entity_id=version_id,
            before=attendance_policy_version_to_audit_dict(before_read),
            after=attendance_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def resolve_attendance_policy_version_as_of(
        self, company_id: UUID, policy_id: UUID, as_of: date
    ) -> AttendancePolicyVersionRead:
        policy = await self._attendance_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        version = await self._attendance_repo.find_effective_as_of(
            self._session, company_id=company_id, policy_id=policy_id, as_of=as_of
        )
        if version is None:
            raise PolicyVersionNotFoundForDateError()
        hour_bands = await self._attendance_repo.list_hour_bands(
            self._session, company_id=company_id, policy_version_id=version.id
        )
        late_bands = await self._attendance_repo.list_late_bands(
            self._session, company_id=company_id, policy_version_id=version.id
        )
        early_bands = await self._attendance_repo.list_early_departure_bands(
            self._session, company_id=company_id, policy_version_id=version.id
        )
        return attendance_policy_version_to_read(version, hour_bands, late_bands, early_bands)

    # -----------------------------------------------------------------
    # Overtime Policy — identity
    # -----------------------------------------------------------------

    async def create_overtime_policy(
        self,
        company_id: UUID,
        body: OvertimePolicyCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicyRead:
        now = datetime.now(UTC)
        policy_id = uuid4()
        try:
            row = await self._overtime_repo.insert_policy(
                self._session,
                data={
                    "id": policy_id,
                    "company_id": company_id,
                    "name": body.name,
                    "code": await next_auto_code(
                        self._session,
                        model=OvertimePolicy,
                        company_id=company_id,
                        prefix="OTP",
                    ),
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise PolicyCodeAlreadyExistsError() from exc

        read = overtime_policy_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_POLICY_CREATED",
            entity_type="overtime_policy",
            entity_id=policy_id,
            after=overtime_policy_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_overtime_policies(
        self, company_id: UUID, *, assignable_only: bool = False
    ) -> list[OvertimePolicyRead]:
        rows = await self._overtime_repo.list_policies(
            self._session, company_id=company_id, assignable_only=assignable_only
        )
        return [overtime_policy_to_read(r) for r in rows]

    async def get_overtime_policy(self, company_id: UUID, policy_id: UUID) -> OvertimePolicyRead:
        row = await self._overtime_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return overtime_policy_to_read(row)

    async def update_overtime_policy(
        self,
        company_id: UUID,
        policy_id: UUID,
        patch: OvertimePolicyUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicyRead:
        row = await self._overtime_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = overtime_policy_to_read(row)

        values = build_overtime_policy_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            try:
                result = await self._overtime_repo.update_policy(
                    self._session,
                    company_id=company_id,
                    policy_id=policy_id,
                    values=values,
                    expected_version=expected_version,
                    now=now,
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise PolicyCodeAlreadyExistsError() from exc
            if result is None:
                latest = await self._overtime_repo.get_policy(
                    self._session, company_id=company_id, policy_id=policy_id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                raise StalePolicyResourceError(
                    "This policy has been modified by another request",
                    current=overtime_policy_to_audit_dict(overtime_policy_to_read(latest)),
                )
            updated = result

        after_read = overtime_policy_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_POLICY_UPDATED",
            entity_type="overtime_policy",
            entity_id=policy_id,
            before=overtime_policy_to_audit_dict(before_read),
            after=overtime_policy_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    # -----------------------------------------------------------------
    # Overtime Policy — versions
    # -----------------------------------------------------------------

    async def create_overtime_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        body: OvertimePolicyVersionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicyVersionRead:
        policy = await self._overtime_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        existing_draft = await self._overtime_repo.get_open_draft(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if existing_draft is not None:
            raise PolicyDraftAlreadyExistsError()

        now = datetime.now(UTC)
        version_id = uuid4()
        row = await self._overtime_repo.insert_version(
            self._session,
            data={
                "id": version_id,
                "company_id": company_id,
                "policy_id": policy_id,
                "status": "DRAFT",
                "version": 1,
                "effective_from": body.effective_from,
                "effective_to": None,
                "eligibility": body.eligibility,
                "min_ot_minutes": body.min_ot_minutes,
                "rounding_minutes": body.rounding_minutes,
                "rounding_mode": body.rounding_mode,
                "requires_pre_approval": body.requires_pre_approval,
                "requires_post_approval": body.requires_post_approval,
                "daily_cap_minutes": body.daily_cap_minutes,
                "weekly_cap_minutes": body.weekly_cap_minutes,
                "monthly_cap_minutes": body.monthly_cap_minutes,
                "comp_off_instead_of_pay": body.comp_off_instead_of_pay,
                "comp_off_expiry_days": body.comp_off_expiry_days,
                "comp_off_day_length_minutes": body.comp_off_day_length_minutes,
                "night_ot_mode": body.night_ot_mode,
                "night_window_start": _parse_time(body.night_window_start)
                if body.night_window_start
                else None,
                "night_window_end": _parse_time(body.night_window_end)
                if body.night_window_end
                else None,
                "approval_chain": body.approval_chain,
                "publish_reason": None,
                "published_at": None,
                "published_by": None,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
        )

        _validate_rate_rows(body.rate_rows)
        rate_rows = await self._overtime_repo.replace_rate_rows(
            self._session,
            company_id=company_id,
            policy_version_id=version_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "policy_version_id": version_id,
                    "day_class": r.day_class,
                    "classification_code": r.classification_code,
                    "multiplier_decimal": r.multiplier_decimal,
                    "sort_order": r.sort_order,
                }
                for r in body.rate_rows
            ],
        )

        read = overtime_policy_version_to_read(row, rate_rows)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_POLICY_VERSION_CREATED",
            entity_type="overtime_policy_version",
            entity_id=version_id,
            after=overtime_policy_version_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_overtime_policy_versions(
        self, company_id: UUID, policy_id: UUID
    ) -> list[OvertimePolicyVersionRead]:
        policy = await self._overtime_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        versions = await self._overtime_repo.list_versions(
            self._session, company_id=company_id, policy_id=policy_id
        )
        result = []
        for v in versions:
            rate_rows = await self._overtime_repo.list_rate_rows(
                self._session, company_id=company_id, policy_version_id=v.id
            )
            result.append(overtime_policy_version_to_read(v, rate_rows))
        return result

    async def _get_overtime_version_read(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> tuple[Any, OvertimePolicyVersionRead]:
        version = await self._overtime_repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        rate_rows = await self._overtime_repo.list_rate_rows(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        return version, overtime_policy_version_to_read(version, rate_rows)

    async def get_overtime_policy_version(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> OvertimePolicyVersionRead:
        _, read = await self._get_overtime_version_read(company_id, policy_id, version_id)
        return read

    async def update_overtime_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        patch: OvertimePolicyVersionUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicyVersionRead:
        version, before_read = await self._get_overtime_version_read(
            company_id, policy_id, version_id
        )
        if version.status != "DRAFT":
            raise PolicyVersionNotDraftError()

        values = build_overtime_policy_version_update_values(patch)
        now = datetime.now(UTC)
        updated = version
        if values:
            result = await self._overtime_repo.update_version(
                self._session,
                company_id=company_id,
                policy_id=policy_id,
                version_id=version_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                _, latest_read = await self._get_overtime_version_read(
                    company_id, policy_id, version_id
                )
                raise StalePolicyResourceError(
                    "This policy version has been modified by another request",
                    current=overtime_policy_version_to_audit_dict(latest_read),
                )
            updated = result

        rate_rows = await self._overtime_repo.list_rate_rows(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        if patch.rate_rows is not None:
            _validate_rate_rows(patch.rate_rows)
            rate_rows = await self._overtime_repo.replace_rate_rows(
                self._session,
                company_id=company_id,
                policy_version_id=version_id,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "policy_version_id": version_id,
                        "day_class": r.day_class,
                        "classification_code": r.classification_code,
                        "multiplier_decimal": r.multiplier_decimal,
                        "sort_order": r.sort_order,
                    }
                    for r in patch.rate_rows
                ],
            )

        after_read = overtime_policy_version_to_read(updated, rate_rows)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_POLICY_VERSION_UPDATED",
            entity_type="overtime_policy_version",
            entity_id=version_id,
            before=overtime_policy_version_to_audit_dict(before_read),
            after=overtime_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def discard_overtime_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicyVersionRead:
        version, before_read = await self._get_overtime_version_read(
            company_id, policy_id, version_id
        )
        if version.status != "DRAFT":
            raise PolicyVersionNotDraftError()

        now = datetime.now(UTC)
        result = await self._overtime_repo.discard_version(
            self._session,
            company_id=company_id,
            policy_id=policy_id,
            version_id=version_id,
            expected_version=expected_version,
            now=now,
        )
        if result is None:
            _, latest_read = await self._get_overtime_version_read(
                company_id, policy_id, version_id
            )
            raise StalePolicyResourceError(
                "This policy version has been modified by another request",
                current=overtime_policy_version_to_audit_dict(latest_read),
            )

        rate_rows = await self._overtime_repo.list_rate_rows(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        after_read = overtime_policy_version_to_read(result, rate_rows)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_POLICY_VERSION_DISCARDED",
            entity_type="overtime_policy_version",
            entity_id=version_id,
            before=overtime_policy_version_to_audit_dict(before_read),
            after=overtime_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def publish_overtime_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        body: OvertimePolicyVersionPublishRequest,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicyVersionRead:
        draft = await self._overtime_repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if draft is None:
            raise NotFoundError("Resource not found")
        if draft.status != "DRAFT":
            raise PolicyVersionNotDraftError()
        if draft.effective_from is None:
            raise PolicyPublishIncompleteError("effective_from is required to publish")

        rate_rows = await self._overtime_repo.list_rate_rows(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        before_read = overtime_policy_version_to_read(draft, rate_rows)

        current = await self._overtime_repo.get_current_published(
            self._session, company_id=company_id, policy_id=policy_id
        )
        now = datetime.now(UTC)
        if current is not None:
            assert current.effective_from is not None
            if draft.effective_from <= current.effective_from:
                raise PolicyPublishIncompleteError(
                    "effective_from must be after the currently published version's effective_from"
                )
            if body.expected_previous_version is None:
                raise PolicyVersionPreviousVersionRequiredError()
            closed = await self._overtime_repo.close_version(
                self._session,
                company_id=company_id,
                version_id=current.id,
                effective_to=draft.effective_from - timedelta(days=1),
                expected_version=body.expected_previous_version,
                now=now,
            )
            if closed is None:
                raise StalePolicyResourceError(
                    "The currently published policy version has been modified by another request",
                    current={},
                )

        try:
            updated = await self._overtime_repo.update_version(
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
            raise PolicyVersionOverlapError() from exc

        if updated is None:
            _, latest_read = await self._get_overtime_version_read(
                company_id, policy_id, version_id
            )
            raise StalePolicyResourceError(
                "This policy version has been modified by another request",
                current=overtime_policy_version_to_audit_dict(latest_read),
            )

        after_read = overtime_policy_version_to_read(updated, rate_rows)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_POLICY_VERSION_PUBLISHED",
            entity_type="overtime_policy_version",
            entity_id=version_id,
            before=overtime_policy_version_to_audit_dict(before_read),
            after=overtime_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def resolve_overtime_policy_version_as_of(
        self, company_id: UUID, policy_id: UUID, as_of: date
    ) -> OvertimePolicyVersionRead:
        policy = await self._overtime_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        version = await self._overtime_repo.find_effective_as_of(
            self._session, company_id=company_id, policy_id=policy_id, as_of=as_of
        )
        if version is None:
            raise PolicyVersionNotFoundForDateError()
        rate_rows = await self._overtime_repo.list_rate_rows(
            self._session, company_id=company_id, policy_version_id=version.id
        )
        return overtime_policy_version_to_read(version, rate_rows)

    # -----------------------------------------------------------------
    # Regularization Policy — identity
    # -----------------------------------------------------------------

    async def create_regularization_policy(
        self,
        company_id: UUID,
        body: RegularizationPolicyCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicyRead:
        now = datetime.now(UTC)
        policy_id = uuid4()
        try:
            row = await self._regularization_repo.insert_policy(
                self._session,
                data={
                    "id": policy_id,
                    "company_id": company_id,
                    "name": body.name,
                    "code": await next_auto_code(
                        self._session,
                        model=RegularizationPolicy,
                        company_id=company_id,
                        prefix="REGP",
                    ),
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise PolicyCodeAlreadyExistsError() from exc

        read = regularization_policy_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_POLICY_CREATED",
            entity_type="regularization_policy",
            entity_id=policy_id,
            after=regularization_policy_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_regularization_policies(
        self, company_id: UUID, *, assignable_only: bool = False
    ) -> list[RegularizationPolicyRead]:
        rows = await self._regularization_repo.list_policies(
            self._session, company_id=company_id, assignable_only=assignable_only
        )
        return [regularization_policy_to_read(r) for r in rows]

    async def get_regularization_policy(
        self, company_id: UUID, policy_id: UUID
    ) -> RegularizationPolicyRead:
        row = await self._regularization_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return regularization_policy_to_read(row)

    async def update_regularization_policy(
        self,
        company_id: UUID,
        policy_id: UUID,
        patch: RegularizationPolicyUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicyRead:
        row = await self._regularization_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = regularization_policy_to_read(row)

        values = build_regularization_policy_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            try:
                result = await self._regularization_repo.update_policy(
                    self._session,
                    company_id=company_id,
                    policy_id=policy_id,
                    values=values,
                    expected_version=expected_version,
                    now=now,
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise PolicyCodeAlreadyExistsError() from exc
            if result is None:
                latest = await self._regularization_repo.get_policy(
                    self._session, company_id=company_id, policy_id=policy_id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                raise StalePolicyResourceError(
                    "This policy has been modified by another request",
                    current=regularization_policy_to_audit_dict(
                        regularization_policy_to_read(latest)
                    ),
                )
            updated = result

        after_read = regularization_policy_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_POLICY_UPDATED",
            entity_type="regularization_policy",
            entity_id=policy_id,
            before=regularization_policy_to_audit_dict(before_read),
            after=regularization_policy_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    # -----------------------------------------------------------------
    # Regularization Policy — versions
    # -----------------------------------------------------------------

    async def create_regularization_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        body: RegularizationPolicyVersionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicyVersionRead:
        policy = await self._regularization_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        existing_draft = await self._regularization_repo.get_open_draft(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if existing_draft is not None:
            raise PolicyDraftAlreadyExistsError()

        now = datetime.now(UTC)
        version_id = uuid4()
        row = await self._regularization_repo.insert_version(
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
                "allow_manager_request": body.allow_manager_request,
                "allow_hr_request": body.allow_hr_request,
                "max_backdated_days": body.max_backdated_days,
                "max_requests_per_month": body.max_requests_per_month,
                "reason_required": body.reason_required,
                "attachment_required": body.attachment_required,
                "approval_chain": body.approval_chain,
                "auto_approve_within_minutes": body.auto_approve_within_minutes,
                "blocked_when_locked": body.blocked_when_locked,
                "publish_reason": None,
                "published_at": None,
                "published_by": None,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
        )

        _validate_allowed_types(body.allowed_types)
        allowed_types = await self._regularization_repo.replace_allowed_types(
            self._session,
            company_id=company_id,
            policy_version_id=version_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "policy_version_id": version_id,
                    "regularization_type": a.regularization_type,
                    "sort_order": a.sort_order,
                }
                for a in body.allowed_types
            ],
        )

        read = regularization_policy_version_to_read(row, allowed_types)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_POLICY_VERSION_CREATED",
            entity_type="regularization_policy_version",
            entity_id=version_id,
            after=regularization_policy_version_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_regularization_policy_versions(
        self, company_id: UUID, policy_id: UUID
    ) -> list[RegularizationPolicyVersionRead]:
        policy = await self._regularization_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        versions = await self._regularization_repo.list_versions(
            self._session, company_id=company_id, policy_id=policy_id
        )
        result = []
        for v in versions:
            allowed_types = await self._regularization_repo.list_allowed_types(
                self._session, company_id=company_id, policy_version_id=v.id
            )
            result.append(regularization_policy_version_to_read(v, allowed_types))
        return result

    async def _get_regularization_version_read(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> tuple[Any, RegularizationPolicyVersionRead]:
        version = await self._regularization_repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        allowed_types = await self._regularization_repo.list_allowed_types(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        return version, regularization_policy_version_to_read(version, allowed_types)

    async def get_regularization_policy_version(
        self, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> RegularizationPolicyVersionRead:
        _, read = await self._get_regularization_version_read(company_id, policy_id, version_id)
        return read

    async def update_regularization_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        patch: RegularizationPolicyVersionUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicyVersionRead:
        version, before_read = await self._get_regularization_version_read(
            company_id, policy_id, version_id
        )
        if version.status != "DRAFT":
            raise PolicyVersionNotDraftError()

        values = build_regularization_policy_version_update_values(patch)
        now = datetime.now(UTC)
        updated = version
        if values:
            result = await self._regularization_repo.update_version(
                self._session,
                company_id=company_id,
                policy_id=policy_id,
                version_id=version_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                _, latest_read = await self._get_regularization_version_read(
                    company_id, policy_id, version_id
                )
                raise StalePolicyResourceError(
                    "This policy version has been modified by another request",
                    current=regularization_policy_version_to_audit_dict(latest_read),
                )
            updated = result

        allowed_types = await self._regularization_repo.list_allowed_types(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        if patch.allowed_types is not None:
            _validate_allowed_types(patch.allowed_types)
            allowed_types = await self._regularization_repo.replace_allowed_types(
                self._session,
                company_id=company_id,
                policy_version_id=version_id,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "policy_version_id": version_id,
                        "regularization_type": a.regularization_type,
                        "sort_order": a.sort_order,
                    }
                    for a in patch.allowed_types
                ],
            )

        after_read = regularization_policy_version_to_read(updated, allowed_types)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_POLICY_VERSION_UPDATED",
            entity_type="regularization_policy_version",
            entity_id=version_id,
            before=regularization_policy_version_to_audit_dict(before_read),
            after=regularization_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def discard_regularization_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicyVersionRead:
        version, before_read = await self._get_regularization_version_read(
            company_id, policy_id, version_id
        )
        if version.status != "DRAFT":
            raise PolicyVersionNotDraftError()

        now = datetime.now(UTC)
        result = await self._regularization_repo.discard_version(
            self._session,
            company_id=company_id,
            policy_id=policy_id,
            version_id=version_id,
            expected_version=expected_version,
            now=now,
        )
        if result is None:
            _, latest_read = await self._get_regularization_version_read(
                company_id, policy_id, version_id
            )
            raise StalePolicyResourceError(
                "This policy version has been modified by another request",
                current=regularization_policy_version_to_audit_dict(latest_read),
            )

        allowed_types = await self._regularization_repo.list_allowed_types(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        after_read = regularization_policy_version_to_read(result, allowed_types)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_POLICY_VERSION_DISCARDED",
            entity_type="regularization_policy_version",
            entity_id=version_id,
            before=regularization_policy_version_to_audit_dict(before_read),
            after=regularization_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def publish_regularization_policy_version(
        self,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        body: RegularizationPolicyVersionPublishRequest,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicyVersionRead:
        draft = await self._regularization_repo.get_version(
            self._session, company_id=company_id, policy_id=policy_id, version_id=version_id
        )
        if draft is None:
            raise NotFoundError("Resource not found")
        if draft.status != "DRAFT":
            raise PolicyVersionNotDraftError()
        if draft.effective_from is None:
            raise PolicyPublishIncompleteError("effective_from is required to publish")

        allowed_types = await self._regularization_repo.list_allowed_types(
            self._session, company_id=company_id, policy_version_id=version_id
        )
        before_read = regularization_policy_version_to_read(draft, allowed_types)

        current = await self._regularization_repo.get_current_published(
            self._session, company_id=company_id, policy_id=policy_id
        )
        now = datetime.now(UTC)
        if current is not None:
            assert current.effective_from is not None
            if draft.effective_from <= current.effective_from:
                raise PolicyPublishIncompleteError(
                    "effective_from must be after the currently published version's effective_from"
                )
            if body.expected_previous_version is None:
                raise PolicyVersionPreviousVersionRequiredError()
            closed = await self._regularization_repo.close_version(
                self._session,
                company_id=company_id,
                version_id=current.id,
                effective_to=draft.effective_from - timedelta(days=1),
                expected_version=body.expected_previous_version,
                now=now,
            )
            if closed is None:
                raise StalePolicyResourceError(
                    "The currently published policy version has been modified by another request",
                    current={},
                )

        try:
            updated = await self._regularization_repo.update_version(
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
            raise PolicyVersionOverlapError() from exc

        if updated is None:
            _, latest_read = await self._get_regularization_version_read(
                company_id, policy_id, version_id
            )
            raise StalePolicyResourceError(
                "This policy version has been modified by another request",
                current=regularization_policy_version_to_audit_dict(latest_read),
            )

        after_read = regularization_policy_version_to_read(updated, allowed_types)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_POLICY_VERSION_PUBLISHED",
            entity_type="regularization_policy_version",
            entity_id=version_id,
            before=regularization_policy_version_to_audit_dict(before_read),
            after=regularization_policy_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def resolve_regularization_policy_version_as_of(
        self, company_id: UUID, policy_id: UUID, as_of: date
    ) -> RegularizationPolicyVersionRead:
        policy = await self._regularization_repo.get_policy(
            self._session, company_id=company_id, policy_id=policy_id
        )
        if policy is None:
            raise NotFoundError("Resource not found")
        version = await self._regularization_repo.find_effective_as_of(
            self._session, company_id=company_id, policy_id=policy_id, as_of=as_of
        )
        if version is None:
            raise PolicyVersionNotFoundForDateError()
        allowed_types = await self._regularization_repo.list_allowed_types(
            self._session, company_id=company_id, policy_version_id=version.id
        )
        return regularization_policy_version_to_read(version, allowed_types)

    # -----------------------------------------------------------------
    # Policy resolution (§16, §19 step 7)
    # -----------------------------------------------------------------

    async def resolve_policy(
        self, company_id: UUID, policy_kind: str, *, employee_id: UUID, target_date: date
    ) -> PolicyResolutionRead:
        return await self._resolution.resolve(
            company_id, policy_kind, employee_id=employee_id, target_date=target_date
        )

    # -----------------------------------------------------------------
    # Cross-module hook — called from `organisation.service._validate_policy_reference`
    # -----------------------------------------------------------------

    async def find_policy(self, company_id: UUID, policy_kind: str, policy_id: UUID) -> Any:
        if policy_kind == "ATTENDANCE_POLICY":
            return await self._attendance_repo.get_policy(
                self._session, company_id=company_id, policy_id=policy_id
            )
        if policy_kind == "OVERTIME_POLICY":
            return await self._overtime_repo.get_policy(
                self._session, company_id=company_id, policy_id=policy_id
            )
        if policy_kind == "REGULARIZATION_POLICY":
            return await self._regularization_repo.get_policy(
                self._session, company_id=company_id, policy_id=policy_id
            )
        return None

    async def policy_exists(self, company_id: UUID, policy_kind: str, policy_id: UUID) -> bool:
        return await self.find_policy(company_id, policy_kind, policy_id) is not None

    async def policy_is_published(
        self, company_id: UUID, policy_kind: str, policy_id: UUID
    ) -> bool:
        repo: Any
        if policy_kind == "ATTENDANCE_POLICY":
            repo = self._attendance_repo
        elif policy_kind == "OVERTIME_POLICY":
            repo = self._overtime_repo
        elif policy_kind == "REGULARIZATION_POLICY":
            repo = self._regularization_repo
        else:
            return False
        version = await repo.get_current_published(
            self._session, company_id=company_id, policy_id=policy_id
        )
        return version is not None

    async def policy_has_version_as_of(
        self, company_id: UUID, policy_kind: str, policy_id: UUID, as_of: date
    ) -> bool:
        repo: Any
        if policy_kind == "ATTENDANCE_POLICY":
            repo = self._attendance_repo
        elif policy_kind == "OVERTIME_POLICY":
            repo = self._overtime_repo
        elif policy_kind == "REGULARIZATION_POLICY":
            repo = self._regularization_repo
        else:
            return False
        version = await repo.find_effective_as_of(
            self._session, company_id=company_id, policy_id=policy_id, as_of=as_of
        )
        return version is not None

    async def has_computed_attendance_blocking_timezone_change(
        self, company_id: UUID, *, employee_ids: list[UUID] | None = None
    ) -> bool:
        """The single cross-module seam `organisation.service._assert_timezone_change_allowed`
        calls (`TZ-01`/`DEC-TZ-04`, execution gate §12) — mirrors the established reverse-
        direction precedent (`organisation.service` already imports `AttendanceService` locally
        for `policy_exists`, above).

        `employee_ids=None` means a company-scope change (every employee counts);
        `employee_ids=[...]` means a branch-scope change, already resolved by the caller from
        `EmployeeAssignment` history (`ED-12`) — this method does not know what a "branch" is,
        keeping the module boundary the same shape as `policy_exists`'s own polymorphic-by-caller
        design.

        The `CLOSED`-period check runs first and unconditionally (`ED-12`'s point 3): a period
        can be `CLOSED` with zero `AttendanceDay` rows underneath it if no employment spans
        overlapped it, which the plain attendance-day check alone would miss."""
        period_repo = AttendancePeriodRepository()
        if await period_repo.has_any_closed(self._session, company_id=company_id):
            return True
        day_repo = AttendanceDayRepository()
        if employee_ids is None:
            return await day_repo.exists_for_company(self._session, company_id=company_id)
        return await day_repo.exists_for_employees(
            self._session, company_id=company_id, employee_ids=employee_ids
        )

    async def assert_date_open(self, company_id: UUID, target_date: date) -> None:
        """`SR-11` (execution gate §12.4) — the cross-module seam for the narrow CLOSED-period
        check added to shift-version publish (`organisation.service.publish_shift_version`):
        a backdated version whose `effective_from` falls inside an already-`CLOSED` period must
        be refused, the same way punch ingestion, roster writes, and regularization submission
        already are. Reuses `_ensure_date_open` rather than a second implementation — raises
        `AttendancePeriodClosedError` unchanged, so the API surface gains no new error shape.

        Deliberately narrow: this is **not** the general case of "any backdated policy publish
        reaching a closed period" — that is recorded as debt against the policy-versioning
        workstream (§12.4), not absorbed here. Only `ShiftVersion` publish gets this check,
        because it is the one the Phase 2/3 timezone work already touches in the same file."""
        await _ensure_date_open(self._session, company_id, target_date, employee_id=None)

    async def closed_period_overlapping(
        self, company_id: UUID, employee_id: UUID, date_from: date, date_to: date
    ) -> tuple[date, date] | None:
        """PD-3 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — the cross-module seam Leave uses
        to refuse apply/approve/cancel on dates inside a closed period: closing the attendance
        period locks leave for those dates too. Decision 14 — only a period of the legal entity
        owning each of the employee's dates counts. Returns the first such `CLOSED` period's
        bounds, or `None` when every date is open."""
        found = await self.closed_period_details_overlapping(
            company_id, employee_id, date_from, date_to
        )
        return (found[1], found[2]) if found is not None else None

    async def closed_period_details_overlapping(
        self, company_id: UUID, employee_id: UUID, date_from: date, date_to: date
    ) -> tuple[UUID, date, date] | None:
        """Same lookup as `closed_period_overlapping`, but also returns the period's id
        (`(period_id, period_start, period_end)`) so a caller can ask Payroll whether a run over
        that period is already finalised (Leave decision 14)."""
        closed = await AttendancePeriodRepository().list_closed_overlapping(
            self._session, company_id=company_id, date_from=date_from, date_to=date_to
        )
        if not closed:
            return None
        spans = await _employee_entity_spans(self._session, company_id, employee_id)
        for period in closed:
            day = max(period.period_start, date_from)
            last = min(period.period_end, date_to)
            while day <= last:
                owner = _owning_legal_entity(spans, day)
                if owner is None or owner == period.legal_entity_id:
                    return (period.id, period.period_start, period.period_end)
                day += timedelta(days=1)
        return None


async def _resolve_visible_employee_ids(
    session: AsyncSession,
    company_id: UUID,
    scope: DataScope | None,
    caller_employee_id: UUID | None,
) -> frozenset[UUID] | None:
    """Local, function-scoped import — same cross-module-seam convention as
    `_check_seat_limit`/`_validate_legal_entity_ownership` elsewhere in this codebase.
    `scope=None` preserves unfiltered (COMPANY-equivalent) behavior for internal callers,
    mirroring `EmployeeService.resolve_visible_employee_ids`'s own `scope=None` convention."""
    if scope is None:
        return None
    from hrms.modules.employee.service import EmployeeService

    employee_service = EmployeeService(session)
    return await employee_service.resolve_visible_employee_ids(
        company_id, scope, caller_employee_id
    )


async def _ensure_employee_visible(
    session: AsyncSession,
    company_id: UUID,
    target_employee_id: UUID,
    scope: DataScope | None,
    caller_employee_id: UUID | None,
) -> None:
    """Confirms the caller may act *on* `target_employee_id` — not just that they hold some
    grant for the permission in question. Reuses `EmployeeService.get_employee`
    (`resolve_visible_employee_ids` under the hood) rather than re-deriving scope logic, same
    cross-module-seam convention as `_resolve_visible_employee_ids` above. Raises `NotFoundError`
    (-> 404) for both a nonexistent/cross-tenant employee id and an out-of-scope one — identical
    shapes, so the response never reveals which case applies."""
    from hrms.modules.employee.service import EmployeeService

    employee_service = EmployeeService(session)
    await employee_service.ensure_employee_visible(
        company_id, target_employee_id, scope=scope, caller_employee_id=caller_employee_id
    )


#: One employment spell as `(legal_entity_id, joining_date, last_working_day)`.
_EntitySpan = tuple[UUID, date, date | None]


def _owning_legal_entity(spans: list[_EntitySpan], target_date: date) -> UUID | None:
    """Decision 14 (`PAYROLL_BUSINESS_DECISIONS.md`) — the legal entity whose attendance period
    owns one employee's `target_date`: the entity of the employment covering it. A date no
    employment covers belongs to the most recent spell that ended before it (post-exit, or a gap
    between spells), else to the first spell starting after it (pre-joining) — so every such
    not-employed day is accounted for by exactly one entity's period. `None` only when the
    employee has no employment at all; callers then fail closed."""
    for legal_entity_id, joining_date, last_working_day in spans:
        if joining_date <= target_date and (
            last_working_day is None or target_date <= last_working_day
        ):
            return legal_entity_id
    preceding = [s for s in spans if s[2] is not None and s[2] < target_date]
    if preceding:
        return max(preceding, key=lambda s: s[2] or date.min)[0]
    following = [s for s in spans if s[1] > target_date]
    if following:
        return min(following, key=lambda s: s[1])[0]
    return None


async def _employee_entity_spans(
    session: AsyncSession, company_id: UUID, employee_id: UUID
) -> list[_EntitySpan]:
    from hrms.modules.employee.service import EmploymentService

    spans = await EmploymentService(session).list_legal_entity_spans(
        company_id, employee_id=employee_id
    )
    return [(legal_entity_id, joining, last) for _, legal_entity_id, joining, last in spans]


async def _is_date_closed(
    session: AsyncSession, company_id: UUID, target_date: date, *, employee_id: UUID | None
) -> bool:
    """Whether a `CLOSED` period owns `target_date` — for `employee_id`, only a period of the
    legal entity that owns that employee-date (decision 14); with `employee_id=None` (a
    company-wide change such as a shift-version publish) any legal entity's closed period
    counts."""
    closed = await AttendancePeriodRepository().list_closed_overlapping(
        session, company_id=company_id, date_from=target_date, date_to=target_date
    )
    if not closed:
        return False
    if employee_id is None:
        return True
    owner = _owning_legal_entity(
        await _employee_entity_spans(session, company_id, employee_id), target_date
    )
    return owner is None or any(p.legal_entity_id == owner for p in closed)


async def _ensure_date_open(
    session: AsyncSession, company_id: UUID, target_date: date, *, employee_id: UUID | None
) -> None:
    """W8 (WD-30) — the authoritative period-lock check every mutating service in this module
    consults before writing anything that could affect a date's attendance facts: punch
    ingestion, roster writes, regularization submission, and overtime approve/reject all call
    this. Deliberately independent of `AttendanceDay.is_locked` — that flag only exists on a
    row that has already been computed, so it cannot protect a date that has no `AttendanceDay`
    row yet (a new joiner backdated into an already-closed period, for instance).
    `AttendanceDayService.calculate()` additionally keeps its own pre-existing `is_locked`
    check (`AttendanceDayLockedError`) for the already-computed-row case, so a locked day is
    refused by two independent, defence-in-depth paths, not one.

    Decision 14 — periods are per legal entity, so the check is per employee-date
    (`_is_date_closed`); pass `employee_id=None` only for a genuinely company-wide change."""
    if await _is_date_closed(session, company_id, target_date, employee_id=employee_id):
        raise AttendancePeriodClosedError()


async def _ensure_shift_in_company(
    session: AsyncSession, company_id: UUID, shift_id: UUID | None
) -> None:
    """A client-supplied `shift_id` is only stored once a company-scoped lookup has found it. The
    foreign keys that point at `shift` are not tenant-composite and a foreign-key check ignores RLS,
    so without this a shift of another company is accepted. A foreign and a non-existent id both
    raise the same `NotFoundError`, so the response does not reveal which tenant owns an id."""
    if shift_id is None:
        return
    from hrms.modules.organisation.service import OrganisationService

    await OrganisationService(session).get_shift(company_id, shift_id)


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Only a unique-constraint violation (SQLSTATE 23505) is a date conflict; any other integrity
    error (a foreign key, a check) must surface as what it is."""
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    return str(getattr(cause, "sqlstate", None) or "") == "23505"


async def _ensure_not_after_last_working_day(
    session: AsyncSession, company_id: UUID, employee_id: UUID, punch_time: datetime
) -> None:
    """A punch cannot land after the employee's last working day. The comparison is on the
    company-local calendar date of the instant (the same business-date basis the rest of the punch
    path uses), never the server's or the UTC date: with a last working day of the 15th, a punch at
    23:59 local on the 15th is accepted and one at 00:00 local on the 16th is not."""
    from hrms.modules.organisation.service import OrganisationService

    company = await OrganisationService(session).get_company_profile(company_id)
    local_date = punch_time.astimezone(resolve_zoneinfo(company.timezone)).date()
    await _ensure_date_within_employment(session, company_id, employee_id, local_date)


async def _ensure_date_within_employment(
    session: AsyncSession, company_id: UUID, employee_id: UUID, local_date: date
) -> None:
    """Rejects a company-local date that falls after the employee's last working day.

    The governing episode is the latest one that had started by that date. A date in a rehire gap
    therefore resolves to the earlier, terminated episode and is rejected, while a date inside the
    new episode resolves to it and is accepted. An employee with no employment record at all is
    left to the existing rules (the calculation engine classifies that as `NOT_JOINED`)."""
    from hrms.modules.employee.service import EmploymentService

    governing = await EmploymentService(session).get_latest_employment_on_or_before(
        company_id, employee_id, local_date
    )
    if (
        governing is not None
        and governing.status == "TERMINATED"
        and governing.last_working_day is not None
        and local_date > governing.last_working_day
    ):
        raise EmployeeTerminatedError(governing.last_working_day)


async def _ensure_punch_date_open(
    session: AsyncSession, company_id: UUID, employee_id: UUID, punch_time: datetime
) -> None:
    """The period-lock gate for *punch ingestion specifically* (`DEC-TZ-05`/`CD-1` ⭐, SELECTED,
    execution gate §10) — split out from `_ensure_date_open` so this basis can differ from the
    roster/regularization/overtime basis (all three keep the plain attendance-date check
    unchanged) without touching those three.

    **Never permanently refuse at ingestion.** Accept the punch if EITHER its business-timezone
    local date OR the previous local date is not `CLOSED`; refuse only when BOTH are closed. This
    replaces the previous UTC-calendar-date basis, whose defect was asymmetric (§10.5): a false
    rejection destroys a fact permanently (no orphan row exists to find later, and a
    regularization request checks the same closed period and is also refused), while a false
    acceptance is inert and recoverable — `AttendanceDayService.calculate()` keeps its own
    separate, unconditional refusal to write into a locked day, so an over-eagerly-accepted punch
    can never actually change a finalized figure; it becomes, at worst, an orphan row for the
    Phase 8 report to surface.

    Only ever tightens in one direction relative to the old basis: every case the UTC basis
    accepted, this basis also accepts (the local-date leg alone reproduces it, since the two
    bases can only disagree when the UTC date is CLOSED and the local date is not — the local
    date is exactly the one that was being wrongly evaluated). The only NEW acceptances are the
    early-morning IST punches (00:00-05:29) the UTC basis wrongly refused."""
    from hrms.modules.organisation.service import OrganisationService

    company = await OrganisationService(session).get_company_profile(company_id)
    tz = resolve_zoneinfo(company.timezone)
    local_date = punch_time.astimezone(tz).date()
    previous_local_date = local_date - timedelta(days=1)

    if not await _is_date_closed(session, company_id, local_date, employee_id=employee_id):
        return
    if await _is_date_closed(session, company_id, previous_local_date, employee_id=employee_id):
        raise AttendancePeriodClosedError()


class ShiftRosterService:
    """Per-employee-per-date schedule override CRUD (W5 — architecture §4.2/§9.7, WD-27). The
    calculation engine's *read* of a resolved roster shift goes straight through
    `ShiftRosterRepository.get_published_for_date` in `AttendanceDayService`, not through this
    service — this class is the `ATTENDANCE.ROSTER_MANAGE` write surface plus the
    `ATTENDANCE.VIEW`-gated list/get.

    Every mutation checks `_ensure_employee_visible` on the *target* `employee_id`, not just
    that the caller holds `ATTENDANCE.ROSTER_MANAGE` at all — the same DataScope-resolved-then-
    discarded bug class fixed for punches in commit `fecb740` (see `PunchService.record_punch`'s
    docstring); a COMPANY-scoped grant is the common case per architecture §23.2, but nothing
    here assumes it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ShiftRosterRepository()
        self._audit = AuditService()

    async def create_roster_entry(
        self,
        company_id: UUID,
        body: ShiftRosterCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRosterRead:
        await _ensure_employee_visible(
            self._session, company_id, body.employee_id, scope, caller_employee_id
        )
        return await self._insert(
            company_id,
            employee_id=body.employee_id,
            roster_date=body.roster_date,
            shift_id=body.shift_id,
            is_week_off_override=body.is_week_off_override,
            is_holiday_working_override=body.is_holiday_working_override,
            reason=body.reason,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def bulk_create(
        self,
        company_id: UUID,
        body: ShiftRosterBulkCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[ShiftRosterRead]:
        """architecture §25 `/rosters bulk + per employee/date` — an explicit per-date list,
        not a rotation-pattern generator (WD-27 — `ShiftRotationPattern` stays deferred to
        optional W11). A fixed roster (same shift every day) or a rotating/monthly pattern is
        expanded into concrete `(date, shift_id)` entries by the caller before this is called;
        the backend only ever persists dated rows, matching WD-12's typed/no-generic-engine
        posture. Entries are inserted one at a time so a single conflicting date fails with a
        precise `ShiftRosterDateConflictError` rather than aborting the whole batch opaquely."""
        await _ensure_employee_visible(
            self._session, company_id, body.employee_id, scope, caller_employee_id
        )
        created: list[ShiftRosterRead] = []
        for entry in body.entries:
            created.append(
                await self._insert(
                    company_id,
                    employee_id=body.employee_id,
                    roster_date=entry.roster_date,
                    shift_id=entry.shift_id,
                    is_week_off_override=entry.is_week_off_override,
                    is_holiday_working_override=entry.is_holiday_working_override,
                    reason=body.reason,
                    actor_user_id=actor_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
        return created

    async def _insert(
        self,
        company_id: UUID,
        *,
        employee_id: UUID,
        roster_date: date,
        shift_id: UUID | None,
        is_week_off_override: bool,
        is_holiday_working_override: bool,
        reason: str | None,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ShiftRosterRead:
        await _ensure_date_open(self._session, company_id, roster_date, employee_id=employee_id)
        await _ensure_shift_in_company(self._session, company_id, shift_id)
        now = datetime.now(UTC)
        roster_id = uuid4()
        data = {
            "id": roster_id,
            "company_id": company_id,
            "employee_id": employee_id,
            "roster_date": roster_date,
            "shift_id": shift_id,
            "is_week_off_override": is_week_off_override,
            "is_holiday_working_override": is_holiday_working_override,
            "status": "DRAFT",
            "reason": reason,
            "created_by": actor_user_id,
            "updated_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        try:
            row = await self._repo.insert(self._session, data=data)
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise ShiftRosterDateConflictError() from exc

        read = shift_roster_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_ROSTER_CREATED",
            entity_type="shift_roster",
            entity_id=roster_id,
            after=shift_roster_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def update_roster_entry(
        self,
        company_id: UUID,
        roster_id: UUID,
        patch: ShiftRosterUpdate,
        *,
        expected_version: int,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRosterRead:
        row = await self._repo.get(self._session, company_id=company_id, roster_id=roster_id)
        if row is None:
            raise ShiftRosterNotFoundError()
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        await _ensure_date_open(
            self._session, company_id, row.roster_date, employee_id=row.employee_id
        )
        before_read = shift_roster_to_read(row)

        values = build_shift_roster_update_values(patch)
        if not values:
            return before_read
        await _ensure_shift_in_company(self._session, company_id, values.get("shift_id"))

        now = datetime.now(UTC)
        try:
            updated = await self._repo.update(
                self._session,
                company_id=company_id,
                roster_id=roster_id,
                values={**values, "updated_by": actor_user_id},
                expected_version=expected_version,
                now=now,
            )
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise ShiftRosterDateConflictError() from exc
        if updated is None:
            updated = await self._repo.get(
                self._session, company_id=company_id, roster_id=roster_id
            )
            if updated is None:
                raise ShiftRosterNotFoundError()
            raise StaleShiftRosterResourceError(
                "This roster entry has been modified by another request",
                current=shift_roster_to_audit_dict(shift_roster_to_read(updated)),
            )

        after_read = shift_roster_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_ROSTER_UPDATED",
            entity_type="shift_roster",
            entity_id=roster_id,
            before=shift_roster_to_audit_dict(before_read),
            after=shift_roster_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def publish_roster_entry(
        self,
        company_id: UUID,
        roster_id: UUID,
        *,
        expected_version: int,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRosterRead:
        """DRAFT -> PUBLISHED (WD-27). Only a `PUBLISHED` row is visible to the calculation
        engine (`ShiftRosterRepository.get_published_for_date`) — publishing is the moment a
        staged roster actually goes live for attendance. Idempotent: publishing an
        already-PUBLISHED row is a no-op, not an error or a pointless version bump."""
        row = await self._repo.get(self._session, company_id=company_id, roster_id=roster_id)
        if row is None:
            raise ShiftRosterNotFoundError()
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        await _ensure_date_open(
            self._session, company_id, row.roster_date, employee_id=row.employee_id
        )
        before_read = shift_roster_to_read(row)
        if before_read.status == "PUBLISHED":
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            roster_id=roster_id,
            values={"status": "PUBLISHED", "updated_by": actor_user_id},
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get(
                self._session, company_id=company_id, roster_id=roster_id
            )
            if current is None:
                raise ShiftRosterNotFoundError()
            raise StaleShiftRosterResourceError(
                "This roster entry has been modified by another request",
                current=shift_roster_to_audit_dict(shift_roster_to_read(current)),
            )

        after_read = shift_roster_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_ROSTER_PUBLISHED",
            entity_type="shift_roster",
            entity_id=roster_id,
            before=shift_roster_to_audit_dict(before_read),
            after=shift_roster_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def delete_roster_entry(
        self,
        company_id: UUID,
        roster_id: UUID,
        *,
        expected_version: int,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRosterRead:
        row = await self._repo.get(self._session, company_id=company_id, roster_id=roster_id)
        if row is None:
            raise ShiftRosterNotFoundError()
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        await _ensure_date_open(
            self._session, company_id, row.roster_date, employee_id=row.employee_id
        )
        before_read = shift_roster_to_read(row)

        now = datetime.now(UTC)
        deleted = await self._repo.soft_delete(
            self._session,
            company_id=company_id,
            roster_id=roster_id,
            expected_version=expected_version,
            now=now,
        )
        if deleted is None:
            current = await self._repo.get(
                self._session, company_id=company_id, roster_id=roster_id
            )
            if current is None:
                raise ShiftRosterNotFoundError()
            raise StaleShiftRosterResourceError(
                "This roster entry has been modified by another request",
                current=shift_roster_to_audit_dict(shift_roster_to_read(current)),
            )

        after_read = shift_roster_to_read(deleted)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_ROSTER_DELETED",
            entity_type="shift_roster",
            entity_id=roster_id,
            before=shift_roster_to_audit_dict(before_read),
            after=shift_roster_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def get_roster_entry(
        self,
        company_id: UUID,
        roster_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> ShiftRosterRead:
        row = await self._repo.get(self._session, company_id=company_id, roster_id=roster_id)
        if row is None:
            raise ShiftRosterNotFoundError()
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        return shift_roster_to_read(row)

    async def list_roster_entries(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> tuple[list[ShiftRosterRead], int]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        return [shift_roster_to_read(r) for r in rows], total


def _ensure_same_logical_punch(existing: Punch, *, direction: str, source: str) -> None:
    """A key replays only the request that created it. The same key carrying a different
    direction or source is a *different* logical punch; replaying would silently drop it."""
    if existing.direction != direction or existing.source != source:
        raise DuplicatePunchIdempotencyKeyError(
            "This idempotency_key was already used for a different punch"
        )


@dataclass(frozen=True)
class _ResolvedShiftSchedule:
    shift_inputs: calc.ShiftInputs | None
    shift_version_id: UUID | None
    tz_name: str
    window: calc.ScheduleWindow


def _zone_or_none(tz_name: str | None) -> ZoneInfo | None:
    """A stored timezone, or None when it is missing or no longer resolvable.

    `None` is not a guess at UTC: the shift-window check fails open when the date it would
    judge cannot be resolved (`TimezoneConfigurationError`), rather than refusing a punch
    against the wrong day or failing the request."""
    if not tz_name:
        return None
    try:
        return resolve_zoneinfo(tz_name)
    except TimezoneConfigurationError:
        return None


async def _resolve_shift_schedule(
    organisation_service: Any,
    *,
    company_id: UUID,
    shift_id: UUID | None,
    target_date: date,
    branch_timezone: str | None,
    company_timezone: str,
) -> _ResolvedShiftSchedule:
    """The shift version, timezone and schedule window of `shift_id` on one date. The single
    resolution both the calculation input and the self-service punch shift-window check use."""
    from hrms.modules.organisation.exceptions import ShiftVersionNotFoundForDateError

    shift_inputs: calc.ShiftInputs | None = None
    shift_version_timezone: str | None = None
    shift_version_id: UUID | None = None
    raw_start_time = raw_end_time = raw_window_start = raw_window_end = None
    if shift_id is not None:
        try:
            shift_version = await organisation_service.resolve_shift_version_as_of(
                company_id, shift_id, target_date
            )
        except ShiftVersionNotFoundForDateError:
            shift_version = None
        if shift_version is not None:
            shift_version_id = shift_version.id
            shift_version_timezone = shift_version.timezone
            raw_start_time = (
                _parse_time(shift_version.start_time) if shift_version.start_time else None
            )
            raw_end_time = _parse_time(shift_version.end_time) if shift_version.end_time else None
            raw_window_start = (
                _parse_time(shift_version.window_start) if shift_version.window_start else None
            )
            raw_window_end = (
                _parse_time(shift_version.window_end) if shift_version.window_end else None
            )
            shift_inputs = calc.ShiftInputs(
                shift_type=shift_version.shift_type,
                is_ot_eligible=shift_version.is_ot_eligible,
                operates_on_holiday=shift_version.operates_on_holiday,
                operates_on_weekly_off=shift_version.operates_on_weekly_off,
                is_cross_midnight=shift_version.is_cross_midnight,
                is_night_shift=shift_version.is_night_shift,
                breaks=[
                    calc.ShiftBreakData(
                        id=b.id,
                        break_kind=b.break_kind,
                        start_time=_parse_time(b.start_time) if b.start_time else None,
                        end_time=_parse_time(b.end_time) if b.end_time else None,
                        window_start=_parse_time(b.window_start) if b.window_start else None,
                        window_end=_parse_time(b.window_end) if b.window_end else None,
                        min_minutes=b.min_minutes,
                        max_minutes=b.max_minutes,
                        is_paid=b.is_paid,
                        is_mandatory=b.is_mandatory,
                        name=b.name,
                        break_type=b.break_type,
                        mode=b.mode,
                        scheduled_minutes=b.scheduled_minutes,
                        crosses_midnight=b.crosses_midnight,
                        excess_outcome=b.excess_outcome,
                        auto_deduct_full=b.auto_deduct_full,
                        optional_recorded_deducts=b.optional_recorded_deducts,
                        optional_scheduled_fallback=b.optional_scheduled_fallback,
                        is_enabled=b.is_enabled,
                        sort_order=b.sort_order,
                        allows_split=b.allows_split,
                    )
                    for b in shift_version.breaks
                ],
                duty_blocks=[
                    calc.ShiftDutyBlockData(
                        sequence=d.sequence,
                        start_time=_parse_time(d.start_time),
                        end_time=_parse_time(d.end_time),
                        crosses_midnight=d.crosses_midnight,
                    )
                    for d in shift_version.duty_blocks
                ],
                core_start=(
                    _parse_time(shift_version.core_start) if shift_version.core_start else None
                ),
                core_end=(_parse_time(shift_version.core_end) if shift_version.core_end else None),
                required_minutes=shift_version.required_minutes,
            )

    tz_name = calc.resolve_timezone(
        shift_version_timezone=shift_version_timezone,
        branch_timezone=branch_timezone,
        company_timezone=company_timezone,
    )

    window = calc.resolve_schedule_window(
        attendance_date=target_date,
        tz_name=tz_name,
        shift=shift_inputs,
        start_time=raw_start_time,
        end_time=raw_end_time,
        window_start=raw_window_start,
        window_end=raw_window_end,
    )
    return _ResolvedShiftSchedule(
        shift_inputs=shift_inputs,
        shift_version_id=shift_version_id,
        tz_name=tz_name,
        window=window,
    )


class PunchService:
    """Punch ingestion (architecture §19.1 step 9, WD-11 — punches are immutable, append-only
    once written; corrections are new punches, never an UPDATE/DELETE of this row)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PunchRepository()
        self._roster_repo = ShiftRosterRepository()
        self._audit = AuditService()

    async def record_punch(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        requested_punch_time: datetime | None,
        source: str,
        reference: str | None,
        idempotency_key: str | None,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        location: PunchLocation | None = None,
        location_error: str | None = None,
    ) -> PunchRead:
        """`record_punch_outcome` without the replay flag — see it for the full contract."""
        read, _replayed = await self.record_punch_outcome(
            company_id,
            employee_id,
            direction=direction,
            requested_punch_time=requested_punch_time,
            source=source,
            reference=reference,
            idempotency_key=idempotency_key,
            scope=scope,
            caller_employee_id=caller_employee_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            location=location,
            location_error=location_error,
        )
        return read

    @logged_operation("attendance.punch.record", result_fields=lambda r: {"replayed": r[1]})
    async def record_punch_outcome(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        requested_punch_time: datetime | None,
        source: str,
        reference: str | None,
        idempotency_key: str | None,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        location: PunchLocation | None = None,
        location_error: str | None = None,
    ) -> tuple[PunchRead, bool]:
        """Returns `(punch, replayed)`: `replayed` is True when an earlier row with the same
        `idempotency_key` was returned instead of writing a new one (callers that attach
        further records to a *new* punch must not do so for a replay).

        Idempotent on `idempotency_key` when the caller supplies one — a resubmission with
        the same key replays the original row rather than erroring or duplicating (the DB
        partial unique index is the concurrency backstop, not the primary check). The
        *load-bearing* dedup mechanism for W4 sources is calculation-time duplicate collapsing
        (`calculation.collapse_duplicate_punches`), not this — see the module note in
        `models.Punch`.

        `scope`/`caller_employee_id` gate the *target* employee, not just whether the caller
        holds the `ATTENDANCE.PUNCH`/`ATTENDANCE.PUNCH_ON_BEHALF` permission at all — the router
        resolving a non-empty `DataScope` only proves the caller has *some* grant; without this,
        a `REPORTEES`/`REPORTEE_TREE`/`SELF`-scoped `PUNCH_ON_BEHALF` grant could be used to punch
        an employee entirely outside the caller's visible set. Checked first, before the
        idempotency lookup, so a forged/out-of-scope `employee_id` never touches punch state.

        **`requested_punch_time` is the one parameter that decides which clock is authoritative
        (`DEC-TZ-01`, SELECTED).** `None` means *"self-service — use the server's clock"*, and is
        what the `/attendance/punches/me` route always passes, because its schema has no
        `punch_time` field to pass. A value means *"on-behalf correction"*, is only reachable from
        the `ATTENDANCE.PUNCH_ON_BEHALF` route, and is validated rather than trusted.

        This is deliberately an explicit parameter list rather than a request model: the previous
        signature took a single `PunchCreate` whose `punch_time`/`source` the caller controlled,
        and the router then decided the permission from that same body. Passing the decided values
        in means the service cannot be handed a self-service punch that carries a client instant —
        it is not expressible."""
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        if source == "WEB" and direction == "IN":
            # Face verification gates check-in only; a plain check-out is always allowed.
            await self._ensure_plain_punch_allowed(
                company_id,
                employee_id,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        if idempotency_key:
            existing = await self._repo.get_by_idempotency_key(
                self._session, company_id=company_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                if existing.employee_id != employee_id:
                    # The key is unique per company, not per employee. Replaying another
                    # employee's punch would drop this one silently and hand that employee's
                    # record back to the caller, so a cross-employee reuse is refused instead.
                    raise DuplicatePunchIdempotencyKeyError()
                _ensure_same_logical_punch(existing, direction=direction, source=source)
                return punch_to_read(existing), True

        if source in GEOFENCED_SOURCES:
            await self._ensure_punch_sequence_and_gap(company_id, employee_id, direction)

        # Geofence — after the idempotency replay (an already-recorded punch is returned as it
        # was, never re-judged against a new location) and before anything is written. Only
        # self-service sources are checked; HR corrections (`ADMIN`) and regularizations are not.
        geofence: GeofenceEvaluation | None = None
        if source in GEOFENCED_SOURCES:
            geofence = await GeofenceService(self._session).enforce(
                company_id,
                employee_id,
                direction=direction,
                source=source,
                location=location,
                location_error=location_error,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        now = datetime.now(UTC)
        punch_time = now if requested_punch_time is None else requested_punch_time

        # Shift window — right after the geofence, before anything is written. A rejection here
        # records no punch; only self-service sources are checked.
        await self.enforce_shift_window(
            company_id,
            employee_id,
            direction=direction,
            source=source,
            punch_time=punch_time,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if requested_punch_time is not None:
            # On-behalf only. The self path cannot reach any of these bounds because it has no
            # client instant to bound — `punch_time` is `now` by construction above.
            if punch_time > now:
                # DEC-TZ-03 (SELECTED): unconditional floor, no tolerance window. An on-behalf
                # punch is a correction about the past, so "slightly ahead" is never legitimate
                # drift to absorb here.
                raise FuturePunchTimeError()
            await self._ensure_within_employment(company_id, employee_id, punch_time)

        # WD-30 — the UTC calendar date of the punch is the only date knowable *before* shift
        # resolution (which itself depends on the date), so this is a deliberate, documented
        # approximation: an overnight shift's punch a few minutes into the *next* UTC day, whose
        # attendance actually attributes to the *previous* shift-start date (FR-ATT-005), could
        # in principle land just outside this check's window at a period boundary. The backstop
        # that never allows a locked historical fact to actually change is unconditional
        # regardless: `AttendanceDayService.calculate()` refuses a locked day outright, so a
        # stray punch here is at worst an inert, orphaned row (WD-11 — additive, never mutates
        # facts), never a silent rewrite.
        await _ensure_not_after_last_working_day(self._session, company_id, employee_id, punch_time)
        await _ensure_punch_date_open(self._session, company_id, employee_id, punch_time)
        punch_id = uuid4()
        data = {
            "id": punch_id,
            "company_id": company_id,
            "employee_id": employee_id,
            "punch_time": punch_time,
            "direction": direction,
            # F-11 — server-assigned from the authenticated route, never a request field. There
            # is no `or` fallback here on purpose: the caller has no say left to fall back to.
            "source": source,
            "idempotency_key": idempotency_key,
            "recorded_by_user_id": actor_user_id,
            "reference": reference,
            "created_at": now,
        }
        try:
            # SAVEPOINT: a lost race on the unique index must not poison the outer transaction,
            # so the winner's row can be read back and replayed below.
            async with self._session.begin_nested():
                row = await self._repo.insert(self._session, data=data)
        except IntegrityError as exc:
            if idempotency_key:
                winner = await self._repo.get_by_idempotency_key(
                    self._session, company_id=company_id, idempotency_key=idempotency_key
                )
                if winner is not None and winner.employee_id == employee_id:
                    _ensure_same_logical_punch(winner, direction=direction, source=source)
                    return punch_to_read(winner), True
            raise DuplicatePunchIdempotencyKeyError() from exc

        read = punch_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PUNCH_CREATED",
            entity_type="punch",
            entity_id=punch_id,
            after=punch_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        if geofence is not None:
            await GeofenceService(self._session).record_accepted(
                company_id,
                employee_id,
                direction=direction,
                source=source,
                evaluation=geofence,
                location=location,
                location_error=location_error,
                punch_id=punch_id,
            )
            read = read.model_copy(update={"geofence": geofence.to_read()})
        await self._try_immediate_calculate(
            company_id,
            employee_id,
            punch_time,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return read, False

    async def enforce_shift_window(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        source: str,
        punch_time: datetime,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Refuses a self-service punch-IN earlier than the policy's `early_in_allowance_minutes`
        before the employee's shift (`OutsideShiftWindowError`, after an audit event written in
        its own transaction — the request transaction rolls back with the error, and no punch is
        ever created). Everything else is recorded: lateness stays the calculation engine's job,
        and a punch after shift end + grace-out is only logged. No resolvable shift or policy, or
        no allowance set, never refuses — those skips are logged (`punch_shift_window_skipped`)
        so a missing shift or policy stays visible. Only `GEOFENCED_SOURCES` (WEB, FACE) are
        checked, so HR corrections, regularizations, imports and device/API punches are untouched.

        The shift comes from `_resolve_shift_schedule`, the same resolution the calculation uses
        (published roster entry, else the assignment's shift). Both the punch's local date and the
        day before are resolved so a punch just after midnight is not judged "too early" against
        today's shift while yesterday's overnight shift is still running.

        The local date is the branch date (company date when the branch has none). The schedule
        window itself is in the shift timezone (WD-06). When those two calendar dates differ, both
        are judged and the punch is refused only if every candidate is too early; a date that
        cannot be resolved, or that still disagrees after one re-resolution, fails open.
        Calendar day type is not consulted: a weekly off, a holiday, or an authorized rostered
        shift does not bypass the window of the shift this resolution returns."""
        if source not in GEOFENCED_SOURCES:
            return
        from hrms.modules.employee.service import EmployeeAssignmentService
        from hrms.modules.organisation.service import OrganisationService

        def skip(reason: str) -> None:
            _logger.info(
                "punch_shift_window_skipped",
                reason=reason,
                company_id=str(company_id),
                employee_id=str(employee_id),
                direction=direction,
                source=source,
            )

        organisation_service = OrganisationService(self._session)
        assignment_service = EmployeeAssignmentService(self._session)
        company = await organisation_service.get_company_profile(company_id)
        resolved: dict[date, tuple[_ResolvedShiftSchedule, str | None]] = {}

        async def schedule_for(target_date: date) -> tuple[_ResolvedShiftSchedule, str | None]:
            cached = resolved.get(target_date)
            if cached is not None:
                return cached
            assignment = await assignment_service.get_assignment_as_of(
                company_id, employee_id, target_date
            )
            branch_timezone: str | None = None
            if assignment is not None and assignment.branch_id is not None:
                branch_timezone = (
                    await organisation_service.get_branch(company_id, assignment.branch_id)
                ).timezone
            roster_entry = await self._roster_repo.get_published_for_date(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                roster_date=target_date,
            )
            shift_id = (
                roster_entry.shift_id
                if roster_entry is not None
                else (assignment.shift_id if assignment else None)
            )
            schedule = await _resolve_shift_schedule(
                organisation_service,
                company_id=company_id,
                shift_id=shift_id,
                target_date=target_date,
                branch_timezone=branch_timezone,
                company_timezone=company.timezone,
            )
            resolved[target_date] = (schedule, branch_timezone)
            return schedule, branch_timezone

        try:
            company_zone = _zone_or_none(company.timezone)
            # A bad company zone must not pick the date. UTC is only a probe so the placement
            # (and therefore the branch zone) can still be loaded; the branch zone decides.
            probe_date = (
                punch_time.astimezone(company_zone).date()
                if company_zone is not None
                else punch_time.date()
            )
            _probe, branch_tz_name = await schedule_for(probe_date)
            if branch_tz_name:
                branch_zone = _zone_or_none(branch_tz_name)
                if branch_zone is None:
                    skip("unresolvable_timezone")
                    return
            else:
                branch_zone = company_zone
            if branch_zone is None:
                skip("unresolvable_timezone")
                return
            local_date = punch_time.astimezone(branch_zone).date()
            anchor, _ = await schedule_for(local_date)
            shift_zone = _zone_or_none(anchor.tz_name)
            if shift_zone is None:
                skip("unresolvable_timezone")
                return
            shift_date = punch_time.astimezone(shift_zone).date()
            dates = [local_date]
            if shift_date != local_date:
                dates.append(shift_date)
                alternate, _ = await schedule_for(shift_date)
                alternate_zone = _zone_or_none(alternate.tz_name)
                if alternate_zone is None:
                    skip("unresolvable_timezone")
                    return
                alternate_date = punch_time.astimezone(alternate_zone).date()
                if alternate_date not in {local_date, shift_date}:
                    # Still ambiguous after re-resolving. Do not refuse.
                    skip("timezone_date_disagreement")
                    return
            for target in list(dates):
                await schedule_for(target)
                await schedule_for(target - timedelta(days=1))
        except (TimezoneConfigurationError, ZoneInfoNotFoundError):
            skip("unresolvable_timezone")
            return

        def span(schedule: _ResolvedShiftSchedule) -> ShiftSpan | None:
            w = schedule.window
            if (
                schedule.shift_inputs is None
                or w.scheduled_start is None
                or w.scheduled_end is None
            ):
                return None
            return ShiftSpan(start=w.scheduled_start, end=w.scheduled_end)

        async def version_for(target_date: date) -> Any:
            resolution = await PolicyResolutionService(self._session).resolve(
                company_id, "ATTENDANCE_POLICY", employee_id=employee_id, target_date=target_date
            )
            if (
                resolution.config_incomplete
                or resolution.resolved_policy_id is None
                or resolution.resolved_version_id is None
            ):
                return None
            return await AttendancePolicyRepository().get_version(
                self._session,
                company_id=company_id,
                policy_id=resolution.resolved_policy_id,
                version_id=resolution.resolved_version_id,
            )

        versions: dict[date, Any] = {}
        decisions: list[ShiftWindowDecision] = []
        for target in dates:
            version = await version_for(target)
            versions[target] = version
            if version is None:
                # No policy on this candidate: nothing may be refused from it.
                decisions.append(ShiftWindowDecision("ALLOWED"))
                continue
            current_schedule, _ = resolved[target]
            previous_schedule, _ = resolved[target - timedelta(days=1)]
            decisions.append(
                evaluate_shift_window(
                    direction=direction,
                    punch_time=punch_time,
                    current=span(current_schedule),
                    previous=span(previous_schedule),
                    early_in_allowance_minutes=version.early_in_allowance_minutes,
                    grace_out_minutes=version.grace_out_minutes,
                )
            )
        if all(item is None for item in versions.values()):
            skip("no_policy")
            return
        decision = combine_shift_window_decisions(decisions)
        disagreed = len(dates) > 1 and any(item.outcome == "TOO_EARLY" for item in decisions)
        if decision.outcome != "TOO_EARLY" and disagreed:
            skip("timezone_date_disagreement")
        elif decision.outcome == "NO_SHIFT":
            skip("no_shift")
        if decision.outcome == "AFTER_SHIFT":
            security_event(
                "punch.outside_shift_window",
                level="info",
                reason="AFTER_SHIFT_END",
                direction=direction,
                company_id=str(company_id),
                employee_id=str(employee_id),
            )
            return
        primary = versions.get(local_date)
        if (
            decision.outcome != "TOO_EARLY"
            or decision.shift is None
            or decision.earliest_punch_in is None
            or primary is None
            or primary.early_in_allowance_minutes is None
        ):
            return
        async with session_scope(company_id=str(company_id)) as audit_session:
            await self._audit.record(
                audit_session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="PUNCH_REJECTED_OUTSIDE_SHIFT_WINDOW",
                entity_type="employee",
                entity_id=employee_id,
                after={
                    "reason": "BEFORE_EARLIEST_PUNCH_IN",
                    "direction": direction,
                    "source": source,
                    "earliest_punch_in": decision.earliest_punch_in.isoformat(),
                },
                ip=ip_address,
                user_agent=user_agent,
            )
        security_event(
            "punch.rejected",
            level="warning",
            reason="OUTSIDE_SHIFT_WINDOW",
            company_id=str(company_id),
            employee_id=str(employee_id),
        )
        raise OutsideShiftWindowError(
            shift_start=decision.shift.start,
            shift_end=decision.shift.end,
            grace_in_minutes=primary.grace_in_minutes,
            grace_out_minutes=primary.grace_out_minutes,
            early_in_allowance_minutes=primary.early_in_allowance_minutes,
            earliest_punch_in=decision.earliest_punch_in,
        )

    async def _ensure_punch_sequence_and_gap(
        self, company_id: UUID, employee_id: UUID, direction: str
    ) -> None:
        """Self-service punches only (HR corrections and regularizations are exempt): no two
        punches closer than the minimum gap, and no repeat of the latest punch's direction
        (in after in, out after out). Only a recent latest punch counts, so a forgotten
        punch-out from a previous day never locks the employee out of today's punch-in."""
        settings = get_settings()
        now = datetime.now(UTC)
        latest = await PunchRepository().latest_for_employee_since(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            since=now - timedelta(hours=settings.attendance_punch_order_lookback_hours),
        )
        if latest is None:
            return
        gap = settings.attendance_punch_min_gap_seconds
        elapsed = (now - latest.punch_time).total_seconds()
        if gap and 0 <= elapsed < gap:
            raise PunchTooSoonError(
                retry_after_seconds=int(gap - elapsed) + 1,
                min_gap_seconds=gap,
                last_punch_time=latest.punch_time,
                last_direction=latest.direction,
            )
        if settings.attendance_punch_order_check_enabled and latest.direction == direction:
            raise PunchAlreadyRecordedError(direction=direction, last_punch_time=latest.punch_time)

    async def _ensure_plain_punch_allowed(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Mandatory face verification (check-in only; the caller skips check-outs): an
        employee whose face profile is ENROLLED may not self-punch in without it. `WEB` is the
        source only the plain self-service route assigns; face punches (`FACE`) have already
        been verified and HR corrections (`ADMIN`) are the approved recovery path. Employees with
        no profile, PENDING_APPROVAL or a rejected / revoked profile keep the plain punch. The
        profile is read in the caller's tenant (RLS + explicit company filter), and the refusal
        is audited in its own transaction
        because the request transaction rolls back with the error."""
        profile = await FaceProfileRepository().get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if profile is None or profile.status != "ENROLLED":
            return
        async with session_scope(company_id=str(company_id)) as audit_session:
            await self._audit.record(
                audit_session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="PUNCH_REJECTED_FACE_REQUIRED",
                entity_type="employee",
                entity_id=employee_id,
                after={"reason": "FACE_VERIFICATION_REQUIRED", "source": "WEB"},
                ip=ip_address,
                user_agent=user_agent,
            )
        security_event(
            "punch.rejected",
            level="warning",
            reason="FACE_VERIFICATION_REQUIRED",
            company_id=str(company_id),
            employee_id=str(employee_id),
        )
        raise FaceVerificationRequiredError()

    async def _try_immediate_calculate(
        self,
        company_id: UUID,
        employee_id: UUID,
        punch_time: datetime,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Execution gate §16.2's "immediate trigger" — best-effort, non-blocking, failure-
        tolerant. **Must never fail the punch write.** The punch is a fact; a calculation is a
        derivation of it, and losing the fact because a derivation failed is unacceptable. Any
        failure here — a `CONFIG_ERROR`-producing gap, a lock conflict, an unexpected exception —
        is swallowed and logged; the Phase 8 scheduled sweep (`attendance.run_daily_calculation`,
        trailing 3 days) picks up whatever this attempt missed.

        Wrapped in `begin_nested()` (a `SAVEPOINT`) rather than a bare try/except: `calculate()`
        does real writes (the day row, break rows, the overtime record) on this same session/
        transaction as the punch insert above, so an exception here — including one that aborts
        the transaction at the Postgres level, e.g. a constraint violation deep in
        `_build_calculation_input` — must not poison the outer transaction the punch insert and
        its audit row are still pending in. Rolling back to the savepoint discards only this
        attempt's work, never the punch itself.

        The target date is the *local* (company-timezone) calendar date of the punch instant —
        the same derivation `_ensure_punch_date_open` uses for its own local/previous-local
        check — not `business_today()`: an on-behalf punch backdated to last week must trigger a
        calculation for last week, not for today. Cross-midnight attribution can differ from this
        local-calendar-date approximation (`FR-ATT-005` — a shift's punch may actually belong to
        the *previous* local date); this hook does not need to get that exactly right, because
        `calculate()` re-derives ownership from the shift itself when it runs, and the trailing
        sweep recomputes both the punch's local date and the day before it (`SR-14`'s window
        shapes already cover the shift/no-shift distinction), whichever one recompute here
        doesn't reach."""
        from hrms.modules.organisation.service import OrganisationService

        try:
            async with self._session.begin_nested():
                company = await OrganisationService(self._session).get_company_profile(company_id)
                local_date = punch_time.astimezone(resolve_zoneinfo(company.timezone)).date()
                await AttendanceDayService(self._session).calculate(
                    company_id,
                    employee_id,
                    local_date,
                    actor_user_id=actor_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    lock_timeout_ms=get_settings().attendance_punch_calc_lock_timeout_ms,
                )
        except Exception as exc:  # noqa: BLE001 - best-effort by design; see docstring
            # A lock/statement timeout is logged under its own event so a sweep holding the row
            # (or a stuck transaction) shows up distinctly; the punch itself is already stored and
            # the scheduled sweep recalculates the day.
            _logger.warning(
                "attendance_immediate_calculate_timed_out"
                if is_wait_timeout(exc)
                else "attendance_immediate_calculate_failed",
                company_id=str(company_id),
                employee_id=str(employee_id),
                punch_time=punch_time.isoformat(),
            )

    async def _ensure_within_employment(
        self, company_id: UUID, employee_id: UUID, punch_time: datetime
    ) -> None:
        """Execution gate §8.2's employment-start floor. Before this, `1900-01-01Z` was accepted
        for any employee — verified — because nothing at any layer compared a supplied punch
        instant against the employee's own employment record.

        Reuses the established `employee.service` cross-module seam rather than adding a query:
        `get_latest_employment_on_or_before` returning `None` means no employment episode had
        begun by that date. Uses the UTC date of the instant, matching how every other date bound
        on this path is derived at ingestion; the floor is a coarse-grained data-integrity check,
        not a minute-accurate one, so the ±5h30m question that matters for period locks
        (`DEC-TZ-05`) is immaterial against a joining date.

        **Scoped deliberately to employees who have at least one employment episode.** An employee
        record with no `Employment` row at all is not treated as a violation — rejecting those
        would be a *new* rule ("a punch requires an employment record"), which §8.2 did not ask
        for and which would break the legitimate ordering where a punch is recorded before HR has
        finished creating the employment row. The calculation engine already classifies that case
        as `NOT_JOINED` through its own population gate, so the fact stays recorded and is
        correctly excluded from attendance. The floor here answers only the question it was
        specified to answer: *is this instant before the employment that does exist?*"""
        from hrms.modules.employee.service import EmploymentService

        employment_service = EmploymentService(self._session)
        latest = await employment_service.get_latest_employment_on_or_before(
            company_id, employee_id, punch_time.date()
        )
        if latest is not None:
            return
        episodes = await employment_service.list_employments(company_id, employee_id)
        if episodes:
            raise PunchTimeBeforeEmploymentError()

    async def list_punches(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[list[PunchRead], int]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
        )
        return [punch_to_read(r) for r in rows], total


class AttendanceDayService:
    """The calculation orchestrator (architecture §19.1). Resolves every input via the existing
    cross-module seams — `employee.service` (employment/assignment as-of),
    `organisation.service` (shift version, branch, company timezone),
    `organisation.calendar_resolution.CalendarResolutionService` (day-type, reused verbatim),
    `attendance.resolution.PolicyResolutionService` (policy version, reused verbatim) — then
    hands them to the pure `attendance.calculation.evaluate_day` engine and persists the result.
    No calculation *logic* lives here, only orchestration; no DB access lives in
    `calculation.py`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._day_repo = AttendanceDayRepository()
        self._break_repo = AttendanceBreakRepository()
        self._break_event_repo = BreakEventRepository()
        self._attendance_policy_repo = AttendancePolicyRepository()
        self._overtime_repo = OvertimePolicyRepository()
        self._ot_record_repo = OvertimeRecordRepository()
        self._ot_action_repo = OvertimeActionRepository()
        self._punch_repo = PunchRepository()
        self._roster_repo = ShiftRosterRepository()
        self._leave_repo = LeaveDayProjectionRepository()
        self._regularization_repo = AttendanceRegularizationRequestRepository()
        self._resolution = PolicyResolutionService(session)
        self._audit = AuditService()

    async def get_attendance_day(
        self,
        company_id: UUID,
        attendance_day_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> AttendanceDayRead:
        row = await self._day_repo.get(
            self._session, company_id=company_id, attendance_day_id=attendance_day_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        if visible_ids is not None and row.employee_id not in visible_ids:
            raise NotFoundError("Resource not found")
        breaks = await self._break_repo.list_for_day(
            self._session, company_id=company_id, attendance_day_id=attendance_day_id
        )
        return attendance_day_to_read(row, breaks)

    async def list_attendance_days(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
        break_filter: str | None = None,
    ) -> tuple[list[AttendanceDayRead], int]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._day_repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            break_filter=break_filter,
        )
        breaks_by_day = await self._break_repo.list_for_days(
            self._session, company_id=company_id, attendance_day_ids=[r.id for r in rows]
        )
        return [attendance_day_to_read(row, breaks_by_day[row.id]) for row in rows], total

    @logged_operation("attendance.day.calculate")
    async def calculate(
        self,
        company_id: UUID,
        employee_id: UUID,
        target_date: date | None,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        lock_timeout_ms: int | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> AttendanceDayRead:
        """Runs `_calculate` with bounded lock and statement waits (`core/db/timeouts.py`): a
        calculation queued behind another transaction's row lock, or running unexpectedly long,
        fails with a database timeout (rolled back cleanly) instead of waiting indefinitely.
        `lock_timeout_ms` lets a best-effort caller (the punch's immediate calculation) give up
        sooner than the configured default.

        B12 (DEF-B11-01, OBS-HRA-01): `employee_id` is client-supplied on the HTTP path, so it is
        proven to belong to `company_id` - and, when the route passes the caller's `scope`, to be
        visible under it - before anything is read for calculation or written. Every caller
        (route, punch, sweep, range task) goes through this one guard; a foreign, unknown or
        out-of-scope id raises the same `NotFoundError` and leaves no row and no audit event.
        `scope=None` is the internal mode (company ownership only)."""
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        settings = get_settings()
        async with bounded_waits(
            self._session,
            lock_timeout_ms=(
                lock_timeout_ms
                if lock_timeout_ms is not None
                else settings.attendance_lock_timeout_ms
            ),
            statement_timeout_ms=settings.attendance_statement_timeout_ms,
        ):
            return await self._calculate(
                company_id,
                employee_id,
                target_date,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def _calculate(
        self,
        company_id: UUID,
        employee_id: UUID,
        target_date: date | None,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendanceDayRead:
        """Architecture §19.1 steps 1-19, end to end, for one employee-date. Idempotent — same
        punches + versions produce the same result (SRS §5.1); calling this again on an
        existing row *is* recompute (WD-10 — full replacement of derived fields, never a
        patch). Refuses to touch a locked day (WD-11) — nothing in W4 can set `is_locked=true`
        yet (plan decision 2), so this path is exercised by tests via a direct flag flip, ready
        for W8's `AttendanceLock`.

        `target_date=None` (`ED-2`, execution gate §9.3) — the caller stops sending `todayIso()`
        (a UTC calendar date, `NEW-02`) and the server derives it instead, from the same
        `business_today()` helper every other business-date site now uses. `date.today()`/
        `datetime.now(UTC).date()` are never used here directly — an explicit `date` is honoured
        unchanged when the caller (e.g. the scheduled job, Phase 8) supplies one."""
        if target_date is None:
            from hrms.modules.organisation.service import OrganisationService

            company = await OrganisationService(self._session).get_company_profile(company_id)
            target_date = business_today(company.timezone)

        # WD-30 — period-level check first (catches a date with no `AttendanceDay` row yet at
        # all); the pre-existing row-level `is_locked` check right after it stays as the
        # specific, narrower error for the already-computed-row case (`ATTENDANCE_DAY_LOCKED`,
        # not `ATTENDANCE_PERIOD_CLOSED`) — two independent, defence-in-depth guards, since the
        # two should never actually disagree (finalize/reopen sets both together).
        await _ensure_date_open(self._session, company_id, target_date, employee_id=employee_id)
        # Execution gate §17.3 — `FOR UPDATE`, acquired here (before `_build_calculation_input`
        # re-resolves configuration below), not after. Taking it after the read would serialise
        # the write but leave the read itself racing a concurrent calculate() for the same
        # employee-date — exactly the race this lock exists to close, now that the immediate
        # punch-triggered calculate and the scheduled trailing-window sweep (Phase 8) can
        # legitimately collide on the same row. `FOR UPDATE` on a not-yet-existing row locks
        # nothing; see the `IntegrityError` handling below, around the insert, for that case.
        existing = await self._day_repo.get_by_employee_date_for_update(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=target_date,
        )
        if existing is not None and existing.is_locked:
            raise AttendanceDayLockedError()

        calc_input, resolved_refs, ot_version, ot_rate_rows = await self._build_calculation_input(
            company_id, employee_id, target_date
        )
        result = calc.evaluate_day(calc_input)
        now = datetime.now(UTC)
        values = self._result_to_values(calc_input, result, resolved_refs)

        existing_ot_record: OvertimeRecord | None = None
        if existing is not None:
            existing_ot_record = await self._ot_record_repo.get_by_attendance_day(
                self._session, company_id=company_id, attendance_day_id=existing.id
            )
        ot_decision = await self._resolve_ot_decision(
            company_id=company_id,
            employee_id=employee_id,
            target_date=target_date,
            result=result,
            ot_version=ot_version,
            ot_rate_rows=ot_rate_rows,
            existing_ot_record=existing_ot_record,
        )
        # W7 (WD-29 decision 2) — the OT-facing summary columns on the day row always reflect
        # the current *decision*, not raw engine output: a frozen terminal record's own values
        # win outright, and a fresh AUTO_APPROVED decision (e.g. `approval_chain=AUTO` even when
        # `requires_post_approval=True`) is applied immediately rather than left at the engine's
        # provisional pending numbers.
        if ot_decision is not None:
            values["ot_minutes_approved"] = ot_decision["minutes_approved"]
            # `overtime_record.comp_off_minutes` (below) always carries the policy-computed
            # fact regardless of decision state; the day's payroll-facing summary only reflects
            # it once actually decided (0 while `PENDING`), consistent with `ot_minutes_approved`.
            values["comp_off_minutes_earned"] = (
                ot_decision["comp_off_minutes"] if ot_decision["status"] != "PENDING" else 0
            )
            values["ot_pending"] = ot_decision["status"] == "PENDING"

        row: AttendanceDay | None = None
        action: str
        if existing is None:
            # Execution gate §17.3 constraint 3 — `FOR UPDATE` above locks nothing for a row
            # that doesn't exist yet, so the first-ever calculation of an employee-date (the
            # immediate punch-triggered calculate and the scheduled sweep both reaching a brand
            # new date at once) can still race here. Not a bespoke retry framework (§16.2's
            # "Celery's own task retry semantics; no bespoke retry machinery" is about the
            # trigger layer, not this) — a `SAVEPOINT` around the one statement that can violate
            # the `(company_id, employee_id, attendance_date)` unique constraint, so losing the
            # race self-heals within this same call instead of surfacing a 500: the loser rolls
            # back to the savepoint (the outer transaction and everything already computed above
            # stay intact), re-reads the winner's now-committed row under `FOR UPDATE`, and falls
            # through to the ordinary recompute branch below.
            day_id = uuid4()
            try:
                async with self._session.begin_nested():
                    row = await self._day_repo.insert(
                        self._session,
                        data={
                            **values,
                            "id": day_id,
                            "company_id": company_id,
                            "employee_id": employee_id,
                            "attendance_date": target_date,
                            "calculation_version": 1,
                            "is_locked": False,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                action = "ATTENDANCE_DAY_CALCULATED"
            except IntegrityError:
                existing = await self._day_repo.get_by_employee_date_for_update(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    attendance_date=target_date,
                )
                if existing is None:
                    # The unique constraint fired but no row is visible under our own snapshot —
                    # not the concurrent-insert race this handles; re-raise rather than mask a
                    # real integrity issue.
                    raise
                if existing.is_locked:
                    raise AttendanceDayLockedError() from None
                # `row` stays `None` here on purpose — falls through to the replace-derived-
                # fields branch below, the same branch an ordinary recompute takes.

        if row is None:
            assert existing is not None
            values["calculation_version"] = existing.calculation_version + 1
            row = await self._day_repo.replace_derived_fields(
                self._session,
                company_id=company_id,
                attendance_day_id=existing.id,
                values=values,
                now=now,
            )
            if row is None:
                # Lost the race against a lock applied between the check above and this write —
                # same fail-closed posture as the upfront check.
                raise AttendanceDayLockedError()
            action = "ATTENDANCE_DAY_RECOMPUTED"

        await self._sync_overtime_record(
            company_id=company_id,
            employee_id=employee_id,
            attendance_day_id=row.id,
            attendance_date=target_date,
            overtime_policy_version_id=resolved_refs["overtime_policy_version_id"],
            decision=ot_decision,
            existing_ot_record=existing_ot_record,
            actor_user_id=actor_user_id,
            now=now,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        break_rows = [
            {
                "id": uuid4(),
                "company_id": company_id,
                "attendance_day_id": row.id,
                "shift_break_id": b.shift_break_id,
                "break_start": b.start,
                "break_end": b.end,
                "minutes": b.minutes,
                "is_paid": b.is_paid,
                "is_excess": b.is_excess,
                "name": b.name,
                "kind": b.kind,
                "rule_source": b.rule_source,
                "override_id": b.override_id,
                "scheduled_minutes": b.scheduled_minutes,
                "excess_minutes": b.excess_minutes,
                "deducted_minutes": b.deducted_minutes,
                "needs_review": b.needs_review,
                "is_approved": b.is_approved,
                "start_event_id": b.start_event_id,
                "end_event_id": b.end_event_id,
                "created_at": now,
                "updated_at": now,
            }
            for b in result.breaks
        ]
        breaks = await self._break_repo.replace_breaks(
            self._session, company_id=company_id, attendance_day_id=row.id, rows=break_rows
        )

        read = attendance_day_to_read(row, breaks)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="attendance_day",
            entity_id=row.id,
            after=attendance_day_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def recompute(
        self,
        company_id: UUID,
        attendance_day_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> AttendanceDayRead:
        row = await self._day_repo.get(
            self._session, company_id=company_id, attendance_day_id=attendance_day_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        return await self.calculate(
            company_id,
            row.employee_id,
            row.attendance_date,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            scope=scope,
            caller_employee_id=caller_employee_id,
        )

    async def queue_range_calculation(
        self,
        company_id: UUID,
        body: AttendanceRangeCalculateInput,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> AttendanceRangeCalculateQueued:
        """PAY-001 — queues `attendance.calculate_range` for the range (see
        `tasks._calculate_range_async`). Refuses a range ending after the company's current
        business date.

        B12 (OBS-HRA-01): under a below-COMPANY `scope` the target set is the caller's visible
        employees. An explicit `employee_ids` list must be a subset of it - any other id (another
        tenant's, unknown, or out of scope) rejects the whole request with the one `NotFoundError`
        before anything is queued - and an omitted list is narrowed to the visible set, never
        widened to the company. A caller who can see nobody gets the same `NotFoundError`."""
        from hrms.modules.attendance.tasks import calculate_range
        from hrms.modules.organisation.service import OrganisationService

        company = await OrganisationService(self._session).get_company_profile(company_id)
        if body.date_to > business_today(company.timezone):
            raise AttendanceRangeInFutureError()
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        target_ids = body.employee_ids
        if visible_ids is not None:
            if target_ids is None:
                target_ids = sorted(visible_ids, key=str)
                if not target_ids:
                    raise NotFoundError("Resource not found")
            elif any(e not in visible_ids for e in target_ids):
                raise NotFoundError("Resource not found")
        employee_ids = [str(e) for e in target_ids] if target_ids is not None else None
        try:
            async_result = calculate_range.delay(
                str(company_id),
                body.date_from.isoformat(),
                body.date_to.isoformat(),
                employee_ids,
                str(actor_user_id) if actor_user_id else None,
                str(body.legal_entity_id) if body.legal_entity_id else None,
            )
        except Exception as exc:  # noqa: BLE001 — any broker/publish failure
            # Nothing has been written yet (the audit row below follows a successful publish), so
            # a 503 the client can retry — not a bare 500, and never a "queued" success.
            safe_log(
                _logger.error,
                "attendance.range_calculation.enqueue_failed",
                company_id=str(company_id),
                **safe_error(exc),
            )
            raise AttendanceQueueUnavailableError() from exc
        queued = AttendanceRangeCalculateQueued(
            task_id=str(async_result.id),
            date_from=body.date_from,
            date_to=body.date_to,
            employee_ids=target_ids,
            legal_entity_id=body.legal_entity_id,
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_RANGE_CALCULATION_QUEUED",
            entity_type="attendance_day",
            entity_id=None,
            before=None,
            after=queued.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return queued

    async def keep_leave_over_punches(
        self,
        company_id: UUID,
        attendance_day_id: UUID,
        body: WorkOnLeaveKeepLeaveInput,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> AttendanceDayRead:
        """BUS-012 (`PAYROLL_BUSINESS_DECISIONS.md` #5) — HR confirms the approved full-day leave
        stands over the punches recorded on the same day. The day is already paid as leave
        (the engine never pays it twice); this only records the decision so period finalize
        stops blocking on `WORK_ON_LEAVE_UNRESOLVED`. The alternative resolution — cancelling
        the leave — goes through Leave and needs nothing here."""
        row = await self._day_repo.get(
            self._session, company_id=company_id, attendance_day_id=attendance_day_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        if row.is_locked:
            raise AttendanceDayLockedError()
        if not row.work_on_leave_flagged:
            raise WorkOnLeaveNotFlaggedError()
        before = attendance_day_to_read(row, [])
        updated = await self._day_repo.replace_derived_fields(
            self._session,
            company_id=company_id,
            attendance_day_id=row.id,
            values={
                "work_on_leave_resolution": "KEEP_LEAVE",
                "work_on_leave_resolution_reason": body.reason,
                "work_on_leave_resolved_by": actor_user_id,
                "work_on_leave_resolved_at": datetime.now(UTC),
            },
            now=datetime.now(UTC),
        )
        if updated is None:
            raise AttendanceDayLockedError()
        breaks = await self._break_repo.list_for_day(
            self._session, company_id=company_id, attendance_day_id=updated.id
        )
        after = attendance_day_to_read(updated, breaks)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_WORK_ON_LEAVE_RESOLVED",
            entity_type="attendance_day",
            entity_id=updated.id,
            before={"work_on_leave_resolution": before.work_on_leave_resolution},
            after={
                "work_on_leave_resolution": after.work_on_leave_resolution,
                "reason": body.reason,
            },
            ip=ip_address,
            user_agent=user_agent,
        )
        return after

    async def list_orphaned_punches(
        self, company_id: UUID, *, date_from: date, date_to: date
    ) -> list[PunchRead]:
        """The orphan-punch report (`TZ-08`/`DEC-TZ-16`, execution gate §16.4) — punches that
        fall outside every attendance day's own load window, and are therefore invisible to
        `calculate()` regardless of how many times it runs: a supervisor arriving at 06:45 for a
        09:00 shift and leaving at 20:30 punches successfully, but if 06:45 falls outside the
        ±2h pad, that punch never gets picked up by any `AttendanceDay` row — the employee shows
        `ABSENT` for a day nearly fourteen hours long, silently.

        `[date_from, date_to]` are **local** (company-timezone) business dates — the same
        convention as every other date-range parameter in this module — widened by one day on
        each side when fetching candidate `AttendanceDay` rows, so a window that legitimately
        extends past midnight (a cross-midnight shift's pad, or `FLEXIBLE`'s asymmetric +12h
        lookahead) is still found even when its own `attendance_date` falls just outside the
        nominal range.

        **`SR-14` — the fourth window shape.** A no-shift day (`shift_id IS NULL`) uses
        `calendar_day_window_utc` — the full local calendar day, no pad at all — never the ±2h
        FIXED/SPLIT logic; applying the padded shape to an unscheduled employee would flag every
        punch a little outside midnight as a false orphan. `FIXED`/`SPLIT` shifts share the same
        `scheduled_start - 2h .. scheduled_end + 2h` shape and are reconstructed exactly from the
        row's own stored `scheduled_start`/`scheduled_end`, with no further DB access needed.
        `FLEXIBLE`'s own pad is asymmetric (`-2h/+12h`, `calculation.resolve_schedule_window`) —
        not distinguishable from `FIXED`/`SPLIT` using only what's stored on `AttendanceDay`
        (`shift_id`, not `shift_type`), so this report applies the narrower ±2h shape to every
        shift-bearing day regardless of type. That is conservative in the safe direction for a
        report: it can only ever over-report (flag a `FLEXIBLE` employee's punch inside their
        real +12h lookahead as an orphan candidate for HR to dismiss), never under-report a
        genuinely missed punch.

        A date with **no** `AttendanceDay` row at all (calculation never ran for it) has no
        window to cover anything — every punch on such a date is orphaned by definition, which is
        exactly the visibility this report exists to provide (`F-14`'s gap, before the row is
        ever created)."""
        from hrms.modules.organisation.service import OrganisationService

        company = await OrganisationService(self._session).get_company_profile(company_id)
        tz_name = company.timezone

        padded_from = date_from - timedelta(days=1)
        padded_to = date_to + timedelta(days=1)
        window_start, _ = calc.calendar_day_window_utc(attendance_date=padded_from, tz_name=tz_name)
        _, window_end = calc.calendar_day_window_utc(attendance_date=padded_to, tz_name=tz_name)

        days = await self._day_repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=None,
            employee_id=None,
            date_from=padded_from,
            date_to=padded_to,
            status=None,
        )
        windows_by_employee: dict[UUID, list[tuple[datetime, datetime]]] = {}
        for day in days:
            if day.shift_id is None:
                covering = calc.calendar_day_window_utc(
                    attendance_date=day.attendance_date, tz_name=day.timezone
                )
            elif day.scheduled_start is not None and day.scheduled_end is not None:
                covering = (
                    day.scheduled_start - timedelta(hours=2),
                    day.scheduled_end + timedelta(hours=2),
                )
            else:
                covering = calc.calendar_day_window_utc(
                    attendance_date=day.attendance_date, tz_name=day.timezone
                )
            windows_by_employee.setdefault(day.employee_id, []).append(covering)

        punches = await self._punch_repo.list_for_company_window(
            self._session, company_id=company_id, window_start=window_start, window_end=window_end
        )
        orphaned = [
            punch
            for punch in punches
            if not any(
                start <= punch.punch_time < end
                for start, end in windows_by_employee.get(punch.employee_id, [])
            )
        ]
        return [punch_to_read(p) for p in orphaned]

    @staticmethod
    def _result_to_values(
        calc_input: calc.AttendanceCalculationInput,
        result: calc.AttendanceCalculationResult,
        resolved_refs: dict[str, UUID | None],
    ) -> dict[str, Any]:
        """Every column of `AttendanceDay` except the identity/date/lock columns, which
        `calculate()` sets separately depending on insert vs. replace."""
        return {
            "timezone": calc_input.timezone,
            "shift_id": resolved_refs["shift_id"],
            "shift_version_id": resolved_refs["shift_version_id"],
            "work_calendar_id": resolved_refs["work_calendar_id"],
            "attendance_policy_version_id": resolved_refs["attendance_policy_version_id"],
            "overtime_policy_version_id": resolved_refs["overtime_policy_version_id"],
            "regularization_policy_version_id": resolved_refs["regularization_policy_version_id"],
            "on_duty_regularization_id": resolved_refs["on_duty_regularization_id"],
            "calendar_day_type": result.calendar_day_type,
            "holiday_name": result.holiday_name,
            "holiday_on_weekly_off": result.holiday_on_weekly_off,
            "scheduled_start": result.scheduled_start,
            "scheduled_end": result.scheduled_end,
            "scheduled_minutes": result.scheduled_minutes,
            "actual_first_in": result.actual_first_in,
            "actual_last_out": result.actual_last_out,
            "worked_minutes": result.worked_minutes,
            "unpaid_break_minutes": result.unpaid_break_minutes,
            "paid_break_minutes": result.paid_break_minutes,
            "excess_break_minutes": result.excess_break_minutes,
            "attendance_status": result.attendance_status,
            "late_minutes": result.late_minutes,
            "early_departure_minutes": result.early_departure_minutes,
            "late_classification": result.late_classification,
            "early_departure_classification": result.early_departure_classification,
            "missing_punch": result.missing_punch,
            "auto_closed": result.auto_closed,
            "is_late": result.is_late,
            "is_early_out": result.is_early_out,
            "is_overtime": result.is_overtime,
            "is_regularized": False,
            "is_pending_approval": result.ot_pending,
            "worked_on_holiday": result.worked_on_holiday,
            "worked_on_weekly_off": result.worked_on_weekly_off,
            "work_on_leave_flagged": result.work_on_leave_flagged,
            # BUS-012 — a still-flagged day keeps HR's resolution (key omitted, so
            # `replace_derived_fields` leaves the columns alone); an unflagged one drops it.
            **(
                {}
                if result.work_on_leave_flagged
                else {
                    "work_on_leave_resolution": None,
                    "work_on_leave_resolution_reason": None,
                    "work_on_leave_resolved_by": None,
                    "work_on_leave_resolved_at": None,
                }
            ),
            "is_core_hours_breach": result.is_core_hours_breach,
            "actual_break_minutes": result.actual_break_minutes,
            "auto_deducted_break_minutes": result.auto_deducted_break_minutes,
            "unresolved_break_count": result.unresolved_break_count,
            "has_unresolved_break": result.has_unresolved_break,
            "has_active_break": result.has_active_break,
            "has_excess_break_exception": result.has_excess_break_exception,
            "gross_elapsed_minutes": result.gross_elapsed_minutes,
            "on_duty": result.attendance_status == "ON_DUTY" or result.is_on_duty_flagged,
            "paid_day_fraction": Decimal(result.paid_day_fraction),
            "lop_fraction": Decimal(result.lop_fraction),
            "leave_fraction": Decimal(result.leave_fraction),
            "weekly_off_fraction": Decimal(result.weekly_off_fraction),
            "unpaid_off_fraction": Decimal(result.unpaid_off_fraction),
            "ot_minutes_detected": result.ot_minutes_detected,
            "ot_minutes_approved": result.ot_minutes_approved,
            "ot_pending": result.ot_pending,
            "ot_classification": result.ot_classification,
            "ot_day_class": result.ot_day_class,
            "comp_off_minutes_earned": result.comp_off_minutes_earned,
            "engine_version": calc.ENGINE_VERSION,
            "computation_snapshot": result.snapshot,
            "calculated_at": datetime.now(UTC),
        }

    async def _build_calculation_input(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> tuple[
        calc.AttendanceCalculationInput,
        dict[str, UUID | None],
        OvertimePolicyVersion | None,
        list[OvertimePolicyRateRow],
    ]:
        # Local, function-scoped imports — the established cross-module-seam convention
        # (module docstring; mirrors `PolicyResolutionService.resolve`,
        # `CalendarResolutionService._scope_candidates`, `EmployeeService._check_seat_limit`).
        from hrms.modules.employee.service import EmployeeAssignmentService, EmploymentService
        from hrms.modules.organisation.calendar_resolution import (
            CalendarResolutionService,
            weekly_off_fraction_of,
        )
        from hrms.modules.organisation.service import OrganisationService

        employment_service = EmploymentService(self._session)
        assignment_service = EmployeeAssignmentService(self._session)
        organisation_service = OrganisationService(self._session)
        calendar_service = CalendarResolutionService(self._session)

        employment = await employment_service.get_employment_as_of(
            company_id, employee_id, target_date
        )
        if employment is None:
            latest = await employment_service.get_latest_employment_on_or_before(
                company_id, employee_id, target_date
            )
            population_status = "EXITED" if latest is not None else "NOT_JOINED"
        else:
            population_status = "ACTIVE"

        assignment = await assignment_service.get_assignment_as_of(
            company_id, employee_id, target_date
        )

        company = await organisation_service.get_company_profile(company_id)
        branch_timezone: str | None = None
        branch_id = assignment.branch_id if assignment else None
        if branch_id is not None:
            branch = await organisation_service.get_branch(company_id, branch_id)
            branch_timezone = branch.timezone

        # W5 (architecture §9.7) — a PUBLISHED `ShiftRoster` row for this employee-date outranks
        # `EmployeeAssignment.shift_id`; falling back to the assignment default when none
        # exists. Only PUBLISHED rows are considered (`get_published_for_date`) — a staged
        # DRAFT roster must never change a live calculation (WD-27).
        roster_entry = await self._roster_repo.get_published_for_date(
            self._session, company_id=company_id, employee_id=employee_id, roster_date=target_date
        )
        roster_week_off_override = (
            roster_entry.is_week_off_override if roster_entry is not None else False
        )
        roster_holiday_working_override = (
            roster_entry.is_holiday_working_override if roster_entry is not None else False
        )

        shift_id = (
            roster_entry.shift_id
            if roster_entry is not None
            else (assignment.shift_id if assignment else None)
        )
        schedule = await _resolve_shift_schedule(
            organisation_service,
            company_id=company_id,
            shift_id=shift_id,
            target_date=target_date,
            branch_timezone=branch_timezone,
            company_timezone=company.timezone,
        )
        # Break management V1 — the employee's in-force break overrides are layered over the
        # shift version's breaks (deterministic, dated; the shift rows are never touched).
        from hrms.modules.attendance.break_service import (
            apply_break_overrides,
            to_event_data,
            utcnow,
        )

        schedule = await apply_break_overrides(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            target_date=target_date,
            shift_id=shift_id,
            schedule=schedule,
        )
        shift_inputs = schedule.shift_inputs
        shift_version_id = schedule.shift_version_id
        tz_name = schedule.tz_name
        window = schedule.window

        calendar_result = await calendar_service.resolve_for_employee(
            company_id, employee_id, target_date
        )
        calendar_day_type = None
        holiday_name = None
        holiday_on_weekly_off = False
        weekly_off_fraction = "1.00"
        holiday_type: str | None = None
        holiday_is_paid = True
        work_calendar_id = calendar_result.work_calendar_id
        if not calendar_result.config_incomplete and calendar_result.day_type is not None:
            calendar_day_type = calendar_result.day_type.day_type
            holiday_name = calendar_result.day_type.holiday_name
            holiday_on_weekly_off = calendar_result.day_type.holiday_on_weekly_off
            if calendar_result.day_type.day_type == "WEEKLY_OFF":
                # Shared interpretation (policy A): the OFF share, 1.00 when unset.
                weekly_off_fraction = str(weekly_off_fraction_of(calendar_result.day_type))
            holiday_type = calendar_result.day_type.holiday_type
            if calendar_result.day_type.holiday_is_paid is not None:
                holiday_is_paid = calendar_result.day_type.holiday_is_paid

        attendance_resolution = await self._resolution.resolve(
            company_id, "ATTENDANCE_POLICY", employee_id=employee_id, target_date=target_date
        )
        policy_inputs: calc.PolicyInputs | None = None
        attendance_policy_version_id: UUID | None = None
        hour_bands: list[calc.BandData] = []
        late_bands: list[calc.BandData] = []
        early_bands: list[calc.BandData] = []
        # WD-32 decisions 2/3 — sibling-day counts for the trailing window, excluding this date
        # (same "prior sum computed here, combined with this day's own fresh computation inside
        # the pure engine" shape as W7's weekly/monthly OT caps, WD-29 decision 3).
        prior_late_days_in_window = 0
        prior_excess_break_days_in_window = 0
        if (
            not attendance_resolution.config_incomplete
            and attendance_resolution.resolved_policy_id is not None
            and attendance_resolution.resolved_version_id is not None
        ):
            version = await self._attendance_policy_repo.get_version(
                self._session,
                company_id=company_id,
                policy_id=attendance_resolution.resolved_policy_id,
                version_id=attendance_resolution.resolved_version_id,
            )
            if version is not None:
                attendance_policy_version_id = version.id
                policy_inputs = calc.PolicyInputs(
                    grace_in_minutes=version.grace_in_minutes,
                    grace_out_minutes=version.grace_out_minutes,
                    punch_rounding=version.punch_rounding,
                    rounding_minutes=version.rounding_minutes,
                    missing_punch_behaviour=version.missing_punch_behaviour,
                    missing_shift_behaviour=version.missing_shift_behaviour,
                    half_day_split=version.half_day_split,
                    half_day_boundary_minutes=version.half_day_boundary_minutes,
                    multi_punch_mode=version.multi_punch_mode,
                    duplicate_punch_window_seconds=version.duplicate_punch_window_seconds,
                    core_hours_breach_behaviour=version.core_hours_breach_behaviour,
                    early_out_uses_core_end=version.early_out_uses_core_end,
                    split_shift_missed_block_behaviour=version.split_shift_missed_block_behaviour,
                    excess_break_behaviour=version.excess_break_behaviour,
                    incomplete_at_lock_behaviour=version.incomplete_at_lock_behaviour,
                    work_on_leave_behaviour=version.work_on_leave_behaviour,
                    lates_to_half_day_count=version.lates_to_half_day_count,
                    excess_break_days_to_half_day_count=(
                        version.excess_break_days_to_half_day_count
                    ),
                    early_departure_requires_approval=version.early_departure_requires_approval,
                    on_duty_requires_punch=version.on_duty_requires_punch,
                )
                hour_bands = [
                    calc.BandData(
                        min_minutes=b.min_minutes,
                        max_minutes=b.max_minutes,
                        classification=b.result_status,
                    )
                    for b in await self._attendance_policy_repo.list_hour_bands(
                        self._session, company_id=company_id, policy_version_id=version.id
                    )
                ]
                late_bands = [
                    calc.BandData(
                        min_minutes=b.min_minutes,
                        max_minutes=b.max_minutes,
                        classification=b.classification,
                    )
                    for b in await self._attendance_policy_repo.list_late_bands(
                        self._session, company_id=company_id, policy_version_id=version.id
                    )
                ]
                early_bands = [
                    calc.BandData(
                        min_minutes=b.min_minutes,
                        max_minutes=b.max_minutes,
                        classification=b.classification,
                    )
                    for b in await self._attendance_policy_repo.list_early_departure_bands(
                        self._session, company_id=company_id, policy_version_id=version.id
                    )
                ]

                # WD-32 decisions 2/3/4 — only queried when the corresponding threshold is
                # actually configured; `late_count_window`/`excess_break_count_window` both only
                # support `MONTH` today (schemas.py `_LATE_COUNT_WINDOWS`), so the boundary is
                # the calendar month containing `target_date`, mirroring the OT monthly cap's own
                # `month_start`/`month_end` computation below.
                month_start = target_date.replace(day=1)
                month_end = (
                    date(target_date.year, 12, 31)
                    if target_date.month == 12
                    else date(target_date.year, target_date.month + 1, 1) - timedelta(days=1)
                )
                window_end = target_date - timedelta(days=1)
                if version.lates_to_half_day_count is not None and window_end >= month_start:
                    prior_late_days_in_window = await self._day_repo.count_flagged_days_in_window(
                        self._session,
                        company_id=company_id,
                        employee_id=employee_id,
                        flag="LATE",
                        window_start=month_start,
                        window_end=window_end,
                    )
                if (
                    version.excess_break_days_to_half_day_count is not None
                    and window_end >= month_start
                ):
                    prior_excess_break_days_in_window = (
                        await self._day_repo.count_flagged_days_in_window(
                            self._session,
                            company_id=company_id,
                            employee_id=employee_id,
                            flag="EXCESS_BREAK",
                            window_start=month_start,
                            window_end=window_end,
                        )
                    )

        overtime_resolution = await self._resolution.resolve(
            company_id, "OVERTIME_POLICY", employee_id=employee_id, target_date=target_date
        )
        ot_inputs: calc.OvertimePolicyInputs | None = None
        overtime_policy_version_id: UUID | None = None
        ot_version: OvertimePolicyVersion | None = None
        ot_rate_rows: list[OvertimePolicyRateRow] = []
        if (
            not overtime_resolution.config_incomplete
            and overtime_resolution.resolved_policy_id is not None
            and overtime_resolution.resolved_version_id is not None
        ):
            ot_version = await self._overtime_repo.get_version(
                self._session,
                company_id=company_id,
                policy_id=overtime_resolution.resolved_policy_id,
                version_id=overtime_resolution.resolved_version_id,
            )
            if ot_version is not None:
                overtime_policy_version_id = ot_version.id
                ot_rate_rows = await self._overtime_repo.list_rate_rows(
                    self._session, company_id=company_id, policy_version_id=ot_version.id
                )
                # W7 (WD-29 decision 3) — the weekly/monthly cumulative budget already consumed
                # by sibling days, computed here (DB access) before handing off to the pure
                # engine, exactly like every other policy/calendar input on this input object.
                remaining_weekly_minutes: int | None = None
                if ot_version.weekly_cap_minutes is not None:
                    week_start = target_date - timedelta(days=target_date.weekday())
                    week_end = week_start + timedelta(days=6)
                    week_sum = await self._ot_record_repo.sum_minutes_detected_for_range(
                        self._session,
                        company_id=company_id,
                        employee_id=employee_id,
                        date_from=week_start,
                        date_to=week_end,
                        exclude_date=target_date,
                    )
                    remaining_weekly_minutes = max(0, ot_version.weekly_cap_minutes - week_sum)
                remaining_monthly_minutes: int | None = None
                if ot_version.monthly_cap_minutes is not None:
                    month_start = target_date.replace(day=1)
                    month_end = (
                        date(target_date.year, 12, 31)
                        if target_date.month == 12
                        else date(target_date.year, target_date.month + 1, 1) - timedelta(days=1)
                    )
                    month_sum = await self._ot_record_repo.sum_minutes_detected_for_range(
                        self._session,
                        company_id=company_id,
                        employee_id=employee_id,
                        date_from=month_start,
                        date_to=month_end,
                        exclude_date=target_date,
                    )
                    remaining_monthly_minutes = max(0, ot_version.monthly_cap_minutes - month_sum)
                ot_inputs = calc.OvertimePolicyInputs(
                    eligibility=ot_version.eligibility,
                    min_ot_minutes=ot_version.min_ot_minutes,
                    rounding_minutes=ot_version.rounding_minutes,
                    rounding_mode=ot_version.rounding_mode,
                    requires_post_approval=ot_version.requires_post_approval,
                    daily_cap_minutes=ot_version.daily_cap_minutes,
                    comp_off_instead_of_pay=ot_version.comp_off_instead_of_pay,
                    night_ot_mode=ot_version.night_ot_mode,
                    night_window_start=ot_version.night_window_start,
                    night_window_end=ot_version.night_window_end,
                    rate_rows=[
                        calc.OvertimeRateRowData(
                            day_class=r.day_class, classification_code=r.classification_code
                        )
                        for r in ot_rate_rows
                    ],
                    remaining_weekly_minutes=remaining_weekly_minutes,
                    remaining_monthly_minutes=remaining_monthly_minutes,
                )

        regularization_resolution = await self._resolution.resolve(
            company_id, "REGULARIZATION_POLICY", employee_id=employee_id, target_date=target_date
        )
        regularization_policy_version_id = (
            regularization_resolution.resolved_version_id
            if not regularization_resolution.config_incomplete
            else None
        )

        punches: list[calc.PunchData] = []
        if population_status == "ACTIVE":
            punch_rows = await self._punch_repo.list_for_employee_window(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                window_start=window.load_start,
                window_end=window.load_end,
            )
            punches = [
                calc.PunchData(id=p.id, punch_time=p.punch_time, direction=p.direction)
                for p in punch_rows
            ]
        break_events = to_event_data(
            await self._break_event_repo.list_for_date(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                attendance_date=target_date,
            )
        )
        # An open break START is *active* only while the day can still receive its END; once the
        # punch window has closed it is unresolved (and the sweep's recompute flips it).
        day_open = utcnow() <= window.load_end

        # W9 (architecture §21) — active approved leave projections for this employee-date,
        # resolved here (DB access) exactly like the roster overrides above, then handed to the
        # pure engine as plain values.
        leave_entries = [
            calc.LeaveOverlayEntry(fraction=str(p.fraction), is_paid=p.is_paid, half=p.half)
            for p in await self._leave_repo.list_active_for_employee_date(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                attendance_date=target_date,
            )
        ]

        # WD-32 decisions 5/6 — resolved fresh on every calculate() call, exactly like the leave
        # entries above (never cached on the regularization request row itself).
        early_departure_approval_request = (
            await self._regularization_repo.get_approved_for_date_and_type(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                attendance_date=target_date,
                request_type="EARLY_DEPARTURE_APPROVAL",
            )
        )
        early_departure_pre_approved = early_departure_approval_request is not None
        on_duty_request = await self._regularization_repo.get_approved_for_date_and_type(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=target_date,
            request_type="ON_DUTY",
        )
        on_duty_approved = on_duty_request is not None

        calc_input = calc.AttendanceCalculationInput(
            employee_id=employee_id,
            attendance_date=target_date,
            timezone=tz_name,
            population_status=population_status,
            calendar_day_type=calendar_day_type,
            holiday_name=holiday_name,
            holiday_on_weekly_off=holiday_on_weekly_off,
            weekly_off_fraction=weekly_off_fraction,
            pay_basis=employment.pay_basis if employment is not None else "MONTHLY",
            holiday_type=holiday_type,
            holiday_is_paid=holiday_is_paid,
            shift=shift_inputs,
            scheduled_start=window.scheduled_start,
            scheduled_end=window.scheduled_end,
            policy=policy_inputs,
            hour_bands=hour_bands,
            late_bands=late_bands,
            early_bands=early_bands,
            ot_policy=ot_inputs,
            punches=punches,
            roster_week_off_override=roster_week_off_override,
            roster_holiday_working_override=roster_holiday_working_override,
            leave_entries=leave_entries,
            prior_late_days_in_window=prior_late_days_in_window,
            prior_excess_break_days_in_window=prior_excess_break_days_in_window,
            early_departure_pre_approved=early_departure_pre_approved,
            on_duty_approved=on_duty_approved,
            break_events=break_events,
            day_open=day_open,
        )
        resolved_refs: dict[str, UUID | None] = {
            "shift_id": shift_id,
            "shift_version_id": shift_version_id,
            "work_calendar_id": work_calendar_id,
            "attendance_policy_version_id": attendance_policy_version_id,
            "overtime_policy_version_id": overtime_policy_version_id,
            "regularization_policy_version_id": regularization_policy_version_id,
            "on_duty_regularization_id": on_duty_request.id if on_duty_request else None,
        }
        return calc_input, resolved_refs, ot_version, ot_rate_rows

    async def _resolve_ot_decision(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        target_date: date,
        result: calc.AttendanceCalculationResult,
        ot_version: OvertimePolicyVersion | None,
        ot_rate_rows: list[OvertimePolicyRateRow],
        existing_ot_record: OvertimeRecord | None,
    ) -> dict[str, Any] | None:
        """W7 (WD-29 decisions 2/4) — the single source of truth for "what is this
        calculate() call's OT decision", used both to override the day row's OT summary
        columns and to sync `overtime_record`. Returns `None` when there is nothing to record
        (no prior record and nothing newly eligible this run) — the caller then deletes any
        stale `PENDING` record and leaves the day's OT columns at the engine's own output
        (already zeroed for a no-OT day)."""
        if existing_ot_record is not None and existing_ot_record.status != "PENDING":
            # Frozen (WD-29 decision 2) — a terminal decision is never revised by a recompute,
            # however that recompute was triggered.
            return {
                "frozen": True,
                "status": existing_ot_record.status,
                "minutes_approved": existing_ot_record.minutes_approved,
                "comp_off_minutes": existing_ot_record.comp_off_minutes,
            }

        if result.ot_minutes_detected <= 0 or ot_version is None:
            return None

        approval_chain = ot_version.approval_chain
        resolved_manager_id: UUID | None = None
        approval_stage: str | None = None
        approver_unresolved = False
        needs_review = approval_chain != "AUTO" and ot_version.requires_post_approval
        if needs_review:
            if approval_chain == "HR":
                approval_stage = "HR"
            else:  # MANAGER or MANAGER_THEN_HR
                # Local, function-scoped import — established cross-module-seam convention
                # (mirrors `RegularizationRequestService.submit`'s identical resolution).
                from hrms.modules.employee.service import EmployeeAssignmentService

                if (
                    existing_ot_record is not None
                    and existing_ot_record.approval_chain == approval_chain
                ):
                    # A still-PENDING record keeps the approver it was created for. Every
                    # recompute of the day lands here, and re-resolving would silently hand the
                    # record to whoever manages the employee *now* whenever a manager change is
                    # dated on or before the overtime day — unlike Leave and Regularization,
                    # whose snapshot is written once. A policy switch to a different chain is a
                    # new decision and resolves afresh.
                    resolved_manager_id = existing_ot_record.resolved_approver_manager_id
                else:
                    assignment_service = EmployeeAssignmentService(self._session)
                    assignment = await assignment_service.get_assignment_as_of(
                        company_id, employee_id, target_date
                    )
                    resolved_manager_id = assignment.reporting_manager_id if assignment else None
                approval_stage = "MANAGER" if resolved_manager_id is not None else "HR"
                approver_unresolved = resolved_manager_id is None

        if needs_review:
            status = "PENDING"
            minutes_approved = 0
        else:
            # `approval_chain == "AUTO"` always auto-approves immediately, even when
            # `requires_post_approval` is set — the chain says no human ever reviews this
            # (WD-29 decision 4). Otherwise `requires_post_approval=False` means the engine
            # already auto-approved the detected minutes.
            status = "AUTO_APPROVED"
            minutes_approved = result.ot_minutes_detected

        # Policy-computed fact stored on the record regardless of decision state (mirrors how
        # the engine itself already computes `comp_off_minutes_earned` unconditionally) — only
        # the day row's payroll-facing summary is gated on the decision (see `calculate()`).
        comp_off_minutes = result.comp_off_minutes_earned
        comp_off_expiry_date: date | None = None
        if comp_off_minutes > 0:
            # Decision 13 — comp-off expires after 60 days unless the policy says otherwise.
            expiry_days = (
                ot_version.comp_off_expiry_days
                if ot_version.comp_off_expiry_days is not None
                else DEFAULT_COMP_OFF_EXPIRY_DAYS
            )
            comp_off_expiry_date = target_date + timedelta(days=expiry_days)

        configured_multiplier = next(
            (r.multiplier_decimal for r in ot_rate_rows if r.day_class == result.ot_day_class),
            None,
        )

        return {
            "frozen": False,
            "status": status,
            "approval_chain": approval_chain,
            "approval_stage": approval_stage,
            "resolved_manager_id": resolved_manager_id,
            "approver_unresolved": approver_unresolved,
            "minutes_detected": result.ot_minutes_detected,
            "minutes_approved": minutes_approved,
            "day_class": result.ot_day_class,
            "classification_code": result.ot_classification,
            "configured_multiplier": configured_multiplier,
            "comp_off_minutes": comp_off_minutes,
            "comp_off_expiry_date": comp_off_expiry_date,
        }

    async def _sync_overtime_record(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        attendance_day_id: UUID,
        attendance_date: date,
        overtime_policy_version_id: UUID | None,
        decision: dict[str, Any] | None,
        existing_ot_record: OvertimeRecord | None,
        actor_user_id: UUID | None,
        now: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Applies `decision` (from `_resolve_ot_decision`) to the `overtime_record` table.
        A frozen decision touches nothing. `None` (nothing detected, nothing pre-existing —
        or a pre-existing `PENDING` record that no longer has anything to decide) deletes any
        stale `PENDING` row. Otherwise upserts — in place if a `PENDING` row already exists
        (preserving its `overtime_action` history), inserted fresh otherwise — and records the
        `DETECTED`/`AUTO_APPROVED`/`APPROVER_UNRESOLVED` actions for this run."""
        if decision is not None and decision["frozen"]:
            return

        if decision is None:
            if existing_ot_record is not None:
                await self._ot_record_repo.delete_if_pending(
                    self._session, company_id=company_id, attendance_day_id=attendance_day_id
                )
            return

        values = {
            "employee_id": employee_id,
            "attendance_date": attendance_date,
            "overtime_policy_version_id": overtime_policy_version_id,
            "day_class": decision["day_class"],
            "classification_code": decision["classification_code"],
            "configured_multiplier": decision["configured_multiplier"],
            "minutes_detected": decision["minutes_detected"],
            "minutes_approved": decision["minutes_approved"],
            "status": decision["status"],
            "approval_chain": decision["approval_chain"],
            "approval_stage": decision["approval_stage"],
            "resolved_approver_manager_id": decision["resolved_manager_id"],
            "comp_off_minutes": decision["comp_off_minutes"],
            "comp_off_expiry_date": decision["comp_off_expiry_date"],
        }

        record: OvertimeRecord | None = None
        if existing_ot_record is not None:
            record = await self._ot_record_repo.replace_pending_for_day(
                self._session,
                company_id=company_id,
                attendance_day_id=attendance_day_id,
                values=values,
                now=now,
            )
        if record is None:
            record = await self._ot_record_repo.insert(
                self._session,
                data={
                    **values,
                    "id": uuid4(),
                    "company_id": company_id,
                    "attendance_day_id": attendance_day_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        await self._ot_action_repo.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "overtime_record_id": record.id,
                "action": "DETECTED",
                "actor_user_id": None,
                "actor_employee_id": None,
                "stage": None,
                "comment": None,
            },
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_DETECTED",
            entity_type="overtime_record",
            entity_id=record.id,
            after=overtime_record_to_audit_dict(overtime_record_to_read(record, actions=[])),
            ip=ip_address,
            user_agent=user_agent,
        )

        if decision["approver_unresolved"]:
            await self._ot_action_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "overtime_record_id": record.id,
                    "action": "APPROVER_UNRESOLVED",
                    "actor_user_id": None,
                    "actor_employee_id": None,
                    "stage": "MANAGER",
                    "comment": "No manager resolved as of the attendance date; routed to HR",
                },
            )

        if decision["status"] == "AUTO_APPROVED":
            await self._ot_action_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "overtime_record_id": record.id,
                    "action": "AUTO_APPROVED",
                    "actor_user_id": None,
                    "actor_employee_id": None,
                    "stage": None,
                    "comment": "Auto-approved per policy",
                },
            )
            if decision["comp_off_minutes"] > 0:
                await self._audit.record(
                    self._session,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    action="COMP_OFF_EARNED",
                    entity_type="overtime_record",
                    entity_id=record.id,
                    after={
                        "employee_id": str(employee_id),
                        "attendance_date": attendance_date.isoformat(),
                        "minutes": decision["comp_off_minutes"],
                        "expiry_date": (
                            decision["comp_off_expiry_date"].isoformat()
                            if decision["comp_off_expiry_date"]
                            else None
                        ),
                    },
                    ip=ip_address,
                    user_agent=user_agent,
                )


def _validate_rate_rows(rate_rows: list[Any]) -> None:
    seen: set[str] = set()
    for row in rate_rows:
        if row.day_class in seen:
            raise InvalidPolicyRateRowError(
                f"day_class '{row.day_class}' appears more than once in rate_rows"
            )
        seen.add(row.day_class)


def _validate_allowed_types(allowed_types: list[Any]) -> None:
    seen: set[str] = set()
    for row in allowed_types:
        if row.regularization_type in seen:
            raise InvalidRegularizationAllowedTypeError(
                f"regularization_type '{row.regularization_type}' appears more than once"
            )
        seen.add(row.regularization_type)


# ---------------------------------------------------------------------------
# W6 — Regularization request workflow (architecture §13/§14, decision log WD-28)
# ---------------------------------------------------------------------------


class RegularizationRequestService:
    """Employee/manager/HR regularization requests. Applies an approved correction only through
    the two mechanisms that already exist — synthetic `Punch` rows (`source='REGULARIZATION'`)
    and, for `WRONG_SHIFT`, a `PUBLISHED` `ShiftRoster` row — followed by the existing
    `AttendanceDayService.calculate()` (WD-28 decision 1). No new calculation-engine logic is
    added anywhere in this class."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AttendanceRegularizationRequestRepository()
        self._requested_punch_repo = AttendanceRegularizationRequestedPunchRepository()
        self._action_repo = AttendanceRegularizationActionRepository()
        self._regularization_policy_repo = RegularizationPolicyRepository()
        self._day_repo = AttendanceDayRepository()
        self._punch_repo = PunchRepository()
        self._roster_repo = ShiftRosterRepository()
        self._resolution = PolicyResolutionService(session)
        self._day_service = AttendanceDayService(session)
        self._audit = AuditService()

    async def _read(
        self, row: AttendanceRegularizationRequest, *, company_id: UUID
    ) -> RegularizationRequestRead:
        punches = await self._requested_punch_repo.list_for_request(
            self._session, company_id=company_id, request_id=row.id
        )
        actions = await self._action_repo.list_for_request(
            self._session, company_id=company_id, request_id=row.id
        )
        return regularization_request_to_read(row, requested_punches=punches, actions=actions)

    async def _record_action(
        self,
        *,
        company_id: UUID,
        request_id: UUID,
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
                "request_id": request_id,
                "action": action,
                "actor_user_id": actor_user_id,
                "actor_employee_id": actor_employee_id,
                "stage": stage,
                "comment": comment,
            },
        )

    @logged_operation("attendance.regularization.submit")
    async def _validate_break_correction_target(
        self, company_id: UUID, employee_id: UUID, body: RegularizationRequestCreate
    ) -> None:
        assert body.break_start_event_id is not None  # guaranteed by the schema validator
        start = await BreakEventRepository().get(
            self._session, company_id=company_id, event_id=body.break_start_event_id
        )
        if (
            start is None
            or start.event_type != "START"
            or start.employee_id != employee_id
            or start.attendance_date != body.attendance_date
        ):
            raise ValidationError(
                "break_start_event_id must be a break START of this employee on the attendance date"
            )
        if body.requested_break_end is not None and body.requested_break_end <= start.event_time:
            raise ValidationError("The break must end after it starts")

    async def submit(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: RegularizationRequestCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        on_behalf: bool,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationRequestRead:
        """`scope`/`caller_employee_id` gate the *target* employee, not just whether the caller
        holds `ATTENDANCE.REGULARIZATION_REQUEST`/`_ON_BEHALF` at all — same reasoning as
        `PunchService.record_punch` (fix `fecb740`). Checked first, before any policy read."""
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        # WD-30 — unconditional, independent of `RegularizationPolicyVersion.blocked_when_locked`
        # (that flag only ever gated the day-level `is_locked` check below it, when a day row
        # already exists). A period-level close is a company-wide administrative decision no
        # per-policy flag can opt out of, and it is the only check that can catch a backdated
        # request for a date that has no `AttendanceDay` row at all yet.
        await _ensure_date_open(
            self._session, company_id, body.attendance_date, employee_id=employee_id
        )

        # `TZ-06` — was `date.today()`, the UTC calendar date under the pinned `TZ=UTC` server
        # (`DEC-TZ-04`). Between 00:00 and 05:29 IST that is one day BEHIND the correct India
        # business date, which would reject a same-day request as "in the future" for that
        # entire window. `business_today(company.timezone)` matches `/attendance/days/calculate`'s
        # own default (Phase 4) rather than a second, independently-derived "today".
        from hrms.modules.organisation.service import OrganisationService

        company = await OrganisationService(self._session).get_company_profile(company_id)
        today = business_today(company.timezone)

        # WD-32 decision 5 — `EARLY_DEPARTURE_APPROVAL` is the one correction type that is
        # forward-dated by nature ("I need to leave early on Friday"), not a backdated
        # correction to something that already happened. Every other type keeps the existing
        # future-date rejection.
        if body.attendance_date > today and body.request_type != "EARLY_DEPARTURE_APPROVAL":
            raise ValidationError("attendance_date cannot be in the future")

        # The request may only correct the attendance of its own employment period: the date must
        # not fall after the last working day (or in a rehire gap), and every requested punch must
        # sit on the attendance date or the day either side of it (an overnight shift's IN/OUT
        # straddle midnight) and not in the future. Without this, an approved request could write
        # facts onto any other date, including ones outside the employee's employment.
        await _ensure_date_within_employment(
            self._session, company_id, employee_id, body.attendance_date
        )
        company_zone = resolve_zoneinfo(company.timezone)
        for requested in body.requested_punches or []:
            requested_local = requested.requested_time.astimezone(company_zone).date()
            if abs((requested_local - body.attendance_date).days) > 1:
                raise ValidationError(
                    "requested punch times must fall on the attendance date or the day "
                    "immediately before or after it"
                )
            if requested.requested_time > datetime.now(UTC):
                raise ValidationError("requested punch times cannot be in the future")

        resolution = await self._resolution.resolve(
            company_id,
            "REGULARIZATION_POLICY",
            employee_id=employee_id,
            target_date=body.attendance_date,
        )
        if (
            resolution.config_incomplete
            or resolution.resolved_policy_id is None
            or resolution.resolved_version_id is None
        ):
            raise RegularizationPolicyNotResolvedError()

        policy_version = await self._regularization_policy_repo.get_version(
            self._session,
            company_id=company_id,
            policy_id=resolution.resolved_policy_id,
            version_id=resolution.resolved_version_id,
        )
        if policy_version is None:
            raise RegularizationPolicyNotResolvedError()

        allowed_types = await self._regularization_policy_repo.list_allowed_types(
            self._session, company_id=company_id, policy_version_id=policy_version.id
        )
        allowed_codes = {row.regularization_type for row in allowed_types}
        if body.request_type not in allowed_codes:
            # WD-21 fail-closed: an empty `allowed_codes` (no configured types at all) also
            # lands here — never silently permit every type because none were configured.
            raise RegularizationTypeNotAllowedError()

        if on_behalf:
            if not (policy_version.allow_manager_request or policy_version.allow_hr_request):
                raise RegularizationNotPermittedError(
                    "The applicable policy does not allow on-behalf requests"
                )
        elif not policy_version.allow_employee_request:
            raise RegularizationNotPermittedError(
                "The applicable policy does not allow employee self-service requests"
            )

        if policy_version.max_backdated_days is not None:
            backdated_days = (today - body.attendance_date).days
            if backdated_days > policy_version.max_backdated_days:
                raise RegularizationWindowExceededError()

        if policy_version.reason_required and not body.reason:
            raise RegularizationReasonRequiredError()
        if policy_version.attachment_required and not body.attachment_reference:
            raise RegularizationAttachmentRequiredError()

        now = datetime.now(UTC)
        if policy_version.max_requests_per_month is not None:
            month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
            count = await self._repo.count_since(
                self._session, company_id=company_id, employee_id=employee_id, since=month_start
            )
            if count >= policy_version.max_requests_per_month:
                raise RegularizationRequestLimitExceededError()

        existing_active = await self._repo.get_active_for_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=body.attendance_date,
        )
        if existing_active is not None:
            raise RegularizationDuplicateActiveRequestError()

        existing_day = await self._day_repo.get_by_employee_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=body.attendance_date,
        )
        if (
            existing_day is not None
            and existing_day.is_locked
            and policy_version.blocked_when_locked
        ):
            raise RegularizationBlockedByLockError()

        approval_chain = policy_version.approval_chain
        resolved_manager_id: UUID | None = None
        approval_stage: str | None
        if approval_chain == "AUTO":
            approval_stage = None
        elif approval_chain == "HR":
            approval_stage = "HR"
        else:  # MANAGER or MANAGER_THEN_HR
            # Local, function-scoped import — mirrors the established convention this codebase
            # uses for every cross-`hrms.modules` call (e.g. `calendar_resolution.py` importing
            # `employee.service`; `attendance.resolution` importing
            # `organisation.calendar_resolution`).
            from hrms.modules.employee.service import EmployeeAssignmentService

            assignment_service = EmployeeAssignmentService(self._session)
            assignment = await assignment_service.get_assignment_as_of(
                company_id, employee_id, body.attendance_date
            )
            resolved_manager_id = assignment.reporting_manager_id if assignment else None
            # §14: "Resolution failure (no manager): route to HR, audit
            # APPROVER_UNRESOLVED. Never auto-approve on failure."
            approval_stage = "MANAGER" if resolved_manager_id is not None else "HR"

        await _ensure_shift_in_company(self._session, company_id, body.requested_shift_id)
        if body.request_type == "BREAK_CORRECTION":
            # A break correction is never self-approving: an AUTO chain would let the employee
            # resolve their own break, so it is routed to HR instead.
            if approval_chain == "AUTO":
                approval_chain = "HR"
                approval_stage = "HR"
            await self._validate_break_correction_target(company_id, employee_id, body)
        request_id = uuid4()
        data = {
            "id": request_id,
            "company_id": company_id,
            "employee_id": employee_id,
            "attendance_day_id": existing_day.id if existing_day is not None else None,
            "attendance_date": body.attendance_date,
            "request_type": body.request_type,
            "reason": body.reason,
            "requested_shift_id": body.requested_shift_id,
            "attachment_reference": body.attachment_reference,
            "break_start_event_id": body.break_start_event_id,
            "requested_break_end": body.requested_break_end,
            "requested_break_minutes": body.requested_break_minutes,
            "status": "SUBMITTED",
            "approval_chain": approval_chain,
            "approval_stage": approval_stage,
            "regularization_policy_version_id": policy_version.id,
            "resolved_approver_manager_id": resolved_manager_id,
            "submitted_by_user_id": actor_user_id,
            "submitted_at": now,
        }
        try:
            row = await self._repo.insert(self._session, data=data)
        except IntegrityError as exc:
            raise RegularizationDuplicateActiveRequestError() from exc

        if body.requested_punches:
            await self._requested_punch_repo.insert_many(
                self._session,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "request_id": request_id,
                        "direction": p.direction,
                        "requested_time": p.requested_time,
                        "sort_order": index,
                    }
                    for index, p in enumerate(body.requested_punches)
                ],
            )

        await self._record_action(
            company_id=company_id,
            request_id=request_id,
            action="SUBMITTED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=None,
            comment=body.reason,
        )
        if approval_chain in ("MANAGER", "MANAGER_THEN_HR") and resolved_manager_id is None:
            await self._record_action(
                company_id=company_id,
                request_id=request_id,
                action="APPROVER_UNRESOLVED",
                actor_user_id=None,
                actor_employee_id=None,
                stage="MANAGER",
                comment="No manager resolved as of the attendance date; routed to HR",
            )

        read = await self._read(row, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_SUBMITTED",
            entity_type="attendance_regularization_request",
            entity_id=request_id,
            after=regularization_request_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )

        if existing_day is not None:
            await self._day_repo.set_pending_approval(
                self._session,
                company_id=company_id,
                attendance_day_id=existing_day.id,
                is_pending_approval=True,
                now=now,
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

    @logged_operation("attendance.regularization.cancel")
    async def cancel(
        self,
        company_id: UUID,
        request_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationRequestRead:
        """Only the original submitter may cancel (Phase 11: "Employee: ... Cancel eligible
        request" — no manager/HR cancel path is specified), and only while still `SUBMITTED`."""
        row = await self._repo.get(self._session, company_id=company_id, request_id=request_id)
        if row is None:
            raise RegularizationRequestNotFoundError()
        await _ensure_employee_visible(
            self._session, company_id, row.employee_id, scope, caller_employee_id
        )
        if row.submitted_by_user_id != actor_user_id:
            raise PermissionDeniedError("Only the original submitter may cancel this request")
        if row.status != "SUBMITTED":
            raise RegularizationInvalidTransitionError()

        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            request_id=request_id,
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
            raise await self._stale_error(company_id, request_id)

        await self._record_action(
            company_id=company_id,
            request_id=request_id,
            action="CANCELLED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=None,
            comment=None,
        )
        read = await self._read(updated, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_CANCELLED",
            entity_type="attendance_regularization_request",
            entity_id=request_id,
            after=regularization_request_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        if row.attendance_day_id is not None:
            await self._day_repo.set_pending_approval(
                self._session,
                company_id=company_id,
                attendance_day_id=row.attendance_day_id,
                is_pending_approval=False,
                now=now,
            )
        return read

    @logged_operation("attendance.regularization.approve")
    async def approve(
        self,
        company_id: UUID,
        request_id: UUID,
        body: RegularizationReviewInput,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationRequestRead:
        row = await self._get_reviewable(
            company_id, request_id, scope=scope, caller_employee_id=caller_employee_id
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

    @logged_operation("attendance.regularization.reject")
    async def reject(
        self,
        company_id: UUID,
        request_id: UUID,
        body: RegularizationReviewInput,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationRequestRead:
        row = await self._get_reviewable(
            company_id, request_id, scope=scope, caller_employee_id=caller_employee_id
        )
        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            request_id=request_id,
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
            raise await self._stale_error(company_id, request_id)

        await self._record_action(
            company_id=company_id,
            request_id=request_id,
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
            action="REGULARIZATION_REJECTED",
            entity_type="attendance_regularization_request",
            entity_id=request_id,
            before=regularization_request_to_audit_dict(
                await self._read(row, company_id=company_id)
            ),
            after=regularization_request_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        # A rejected request cannot be treated as approved (Phase 5): no correction is applied,
        # and any earlier pending-approval flag on the day is cleared without touching
        # `is_regularized` (WD-28 decision 3 / `set_pending_approval`).
        if row.attendance_day_id is not None:
            await self._day_repo.set_pending_approval(
                self._session,
                company_id=company_id,
                attendance_day_id=row.attendance_day_id,
                is_pending_approval=False,
                now=now,
            )
        return read

    async def _get_reviewable(
        self,
        company_id: UUID,
        request_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> AttendanceRegularizationRequest:
        row = await self._repo.get(self._session, company_id=company_id, request_id=request_id)
        if row is None:
            raise RegularizationRequestNotFoundError()
        if row.status != "SUBMITTED" or row.approval_stage is None:
            raise RegularizationInvalidTransitionError()
        # WD-28 decision 5 — self-approval is always blocked, no policy escape hatch exists.
        if caller_employee_id is not None and row.employee_id == caller_employee_id:
            raise RegularizationSelfApprovalNotAllowedError()

        if row.approval_stage == "MANAGER":
            # §14: "MANAGER -> reporting_manager_id as of the attendance date" — identity match
            # against the snapshot, not merely "any REPORTEES-scoped grant" (defence in depth:
            # the caller must also hold the permission at all, enforced at the router).
            if caller_employee_id is None or caller_employee_id != row.resolved_approver_manager_id:
                raise RegularizationApproverMismatchError()
        else:  # HR
            # §14: "HR -> any user with ATTENDANCE.REGULARISE_APPROVE at COMPANY".
            if DataScopeLevel.COMPANY not in scope.levels:
                raise RegularizationApproverMismatchError(
                    "HR-stage approval requires a company-wide REGULARIZATION_APPROVE grant"
                )
        return row

    async def _stale_error(
        self, company_id: UUID, request_id: UUID
    ) -> RegularizationRequestNotFoundError | StaleRegularizationRequestResourceError:
        current = await self._repo.get(self._session, company_id=company_id, request_id=request_id)
        if current is None:
            return RegularizationRequestNotFoundError()
        current_read = await self._read(current, company_id=company_id)
        return StaleRegularizationRequestResourceError(
            "This request has been modified by another request",
            current=regularization_request_to_audit_dict(current_read),
        )

    async def _approve_internal(
        self,
        company_id: UUID,
        row: AttendanceRegularizationRequest,
        *,
        actor_user_id: UUID | None,
        actor_employee_id: UUID | None,
        reviewer_comment: str | None,
        expected_version: int,
        ip_address: str | None,
        user_agent: str | None,
    ) -> RegularizationRequestRead:
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
            request_id=row.id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, row.id)

        if not is_final_stage:
            await self._record_action(
                company_id=company_id,
                request_id=row.id,
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
                action="REGULARIZATION_STAGE_APPROVED",
                entity_type="attendance_regularization_request",
                entity_id=row.id,
                before=regularization_request_to_audit_dict(before_read),
                after=regularization_request_to_audit_dict(read),
                ip=ip_address,
                user_agent=user_agent,
            )
            return read

        await self._record_action(
            company_id=company_id,
            request_id=row.id,
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
            action="REGULARIZATION_APPROVED",
            entity_type="attendance_regularization_request",
            entity_id=row.id,
            before=regularization_request_to_audit_dict(before_read),
            after=regularization_request_to_audit_dict(approved_read),
            ip=ip_address,
            user_agent=user_agent,
        )

        return await self._apply_correction(
            company_id,
            updated,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _apply_correction(
        self,
        company_id: UUID,
        row: AttendanceRegularizationRequest,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> RegularizationRequestRead:
        """WD-28 decision 1 — the only two mechanisms an approved request may use: synthetic
        punches and, for `WRONG_SHIFT`, a `PUBLISHED` roster row. Both already exist; nothing
        here is a new calculation path. Runs inside the same transaction as the approval write
        that preceded it — if `AttendanceDayService.calculate()` refuses a locked day, the whole
        transaction (including the `status='APPROVED'` write) rolls back with the exception, so
        a request is never left `APPROVED` without its correction actually applied."""
        now = datetime.now(UTC)

        if row.request_type == "BREAK_CORRECTION":
            return await self._apply_break_correction(
                company_id,
                row,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                now=now,
            )

        if row.requested_shift_id is not None:
            existing_roster = await self._roster_repo.get_for_date(
                self._session,
                company_id=company_id,
                employee_id=row.employee_id,
                roster_date=row.attendance_date,
            )
            if existing_roster is None:
                roster_row = await self._roster_repo.insert(
                    self._session,
                    data={
                        "id": uuid4(),
                        "company_id": company_id,
                        "employee_id": row.employee_id,
                        "roster_date": row.attendance_date,
                        "shift_id": row.requested_shift_id,
                        "is_week_off_override": False,
                        "is_holiday_working_override": False,
                        "status": "PUBLISHED",
                        "reason": f"Applied from regularization request {row.id}",
                        "version": 1,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
                await self._audit.record(
                    self._session,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    action="SHIFT_ROSTER_CREATED",
                    entity_type="shift_roster",
                    entity_id=roster_row.id,
                    after=shift_roster_to_audit_dict(shift_roster_to_read(roster_row)),
                    ip=ip_address,
                    user_agent=user_agent,
                )
            else:
                roster_before = shift_roster_to_read(existing_roster)
                updated_roster = await self._roster_repo.update(
                    self._session,
                    company_id=company_id,
                    roster_id=existing_roster.id,
                    values={
                        "shift_id": row.requested_shift_id,
                        "status": "PUBLISHED",
                        "reason": f"Applied from regularization request {row.id}",
                        "updated_by": actor_user_id,
                    },
                    expected_version=existing_roster.version,
                    now=now,
                )
                # A concurrent roster edit racing this exact apply is not guarded further — if
                # lost, the roster simply keeps its newer state and the punch-based correction
                # and recompute below still proceed (the fail-safe direction: no state is lost,
                # worst case the shift correction silently no-ops and the day recomputes without
                # it, visible on inspection since `applied_at` is still set truthfully by what
                # actually happened below).
                if updated_roster is not None:
                    await self._audit.record(
                        self._session,
                        company_id=company_id,
                        actor_user_id=actor_user_id,
                        action="SHIFT_ROSTER_UPDATED",
                        entity_type="shift_roster",
                        entity_id=updated_roster.id,
                        before=shift_roster_to_audit_dict(roster_before),
                        after=shift_roster_to_audit_dict(shift_roster_to_read(updated_roster)),
                        ip=ip_address,
                        user_agent=user_agent,
                    )

        requested_punches = await self._requested_punch_repo.list_for_request(
            self._session, company_id=company_id, request_id=row.id
        )
        for requested in requested_punches:
            await _ensure_not_after_last_working_day(
                self._session, company_id, row.employee_id, requested.requested_time
            )
            punch_row = await self._punch_repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": row.employee_id,
                    "punch_time": requested.requested_time,
                    "direction": requested.direction,
                    "source": "REGULARIZATION",
                    "idempotency_key": None,
                    "recorded_by_user_id": actor_user_id,
                    "reference": f"regularization:{row.id}",
                    "created_at": now,
                },
            )
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="PUNCH_CREATED",
                entity_type="punch",
                entity_id=punch_row.id,
                after=punch_to_audit_dict(punch_to_read(punch_row)),
                ip=ip_address,
                user_agent=user_agent,
            )

        day_read = await self._day_service.calculate(
            company_id,
            row.employee_id,
            row.attendance_date,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._day_repo.mark_regularized(
            self._session, company_id=company_id, attendance_day_id=day_read.id, now=now
        )
        await self._repo.mark_applied(
            self._session,
            company_id=company_id,
            request_id=row.id,
            attendance_day_id=None if row.attendance_day_id == day_read.id else day_read.id,
            now=now,
        )
        applied_row = await self._repo.get(self._session, company_id=company_id, request_id=row.id)
        assert applied_row is not None  # status write above already succeeded uniquely

        await self._record_action(
            company_id=company_id,
            request_id=row.id,
            action="APPLIED",
            actor_user_id=actor_user_id,
            actor_employee_id=None,
            stage=None,
            comment=None,
        )
        final_read = await self._read(applied_row, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_APPLIED",
            entity_type="attendance_regularization_request",
            entity_id=row.id,
            after=regularization_request_to_audit_dict(final_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return final_read

    async def _apply_break_correction(
        self,
        company_id: UUID,
        row: AttendanceRegularizationRequest,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> RegularizationRequestRead:
        """Applies an approved BREAK_CORRECTION through `BreakEventService` (append-only ADMIN
        END event + recalculation). Same transaction as the approval, so a locked day or a
        stale/superseded start rolls the whole approval back."""
        from hrms.modules.attendance.break_service import BreakEventService

        assert row.break_start_event_id is not None
        start = await BreakEventRepository().get(
            self._session, company_id=company_id, event_id=row.break_start_event_id
        )
        if start is None:
            raise ValidationError("The break being corrected no longer exists")
        await BreakEventService(self._session)._apply_correction(
            company_id,
            start=start,
            corrected_end=row.requested_break_end,
            approved_minutes=row.requested_break_minutes,
            reason=row.reason or "Break correction",
            actor_user_id=actor_user_id,
            regularization_request_id=row.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        day_row = await self._day_repo.get_by_employee_date(
            self._session,
            company_id=company_id,
            employee_id=row.employee_id,
            attendance_date=row.attendance_date,
        )
        if day_row is not None:
            await self._day_repo.mark_regularized(
                self._session, company_id=company_id, attendance_day_id=day_row.id, now=now
            )
        await self._repo.mark_applied(
            self._session,
            company_id=company_id,
            request_id=row.id,
            attendance_day_id=(
                None if day_row is None or row.attendance_day_id == day_row.id else day_row.id
            ),
            now=now,
        )
        applied_row = await self._repo.get(self._session, company_id=company_id, request_id=row.id)
        assert applied_row is not None
        await self._record_action(
            company_id=company_id,
            request_id=row.id,
            action="APPLIED",
            actor_user_id=actor_user_id,
            actor_employee_id=None,
            stage=None,
            comment=None,
        )
        final_read = await self._read(applied_row, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="REGULARIZATION_APPLIED",
            entity_type="attendance_regularization_request",
            entity_id=row.id,
            after=regularization_request_to_audit_dict(final_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return final_read

    async def get(
        self,
        company_id: UUID,
        request_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> RegularizationRequestRead:
        row = await self._repo.get(self._session, company_id=company_id, request_id=request_id)
        if row is None:
            raise RegularizationRequestNotFoundError()
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        if visible_ids is not None and row.employee_id not in visible_ids:
            raise RegularizationRequestNotFoundError()
        return await self._read(row, company_id=company_id)

    async def list(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        status: str | None = None,
        request_type: str | None = None,
    ) -> tuple[list[RegularizationRequestRead], int]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            request_type=request_type,
        )
        return [await self._read(r, company_id=company_id) for r in rows], total


# ---------------------------------------------------------------------------
# W7 — OvertimeRecord approval workflow (architecture §12, decision log WD-29)
# ---------------------------------------------------------------------------


class OvertimeRecordService:
    """Approve/reject for system-detected overtime. There is no submit/cancel/apply — detection,
    auto-approval, and the day-row sync all happen inside `AttendanceDayService.calculate()`
    (WD-29 decision 1: engine-detected only, no manual request flow). This class is purely the
    `PENDING -> APPROVED|REJECTED` review surface, mirroring `RegularizationRequestService`'s
    approval mechanics (manager-as-of resolution, self-approval block, `MANAGER_THEN_HR`
    staging, optimistic concurrency) as closely as the underlying entity allows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OvertimeRecordRepository()
        self._action_repo = OvertimeActionRepository()
        self._day_repo = AttendanceDayRepository()
        self._audit = AuditService()

    async def _read(self, row: OvertimeRecord, *, company_id: UUID) -> OvertimeRecordRead:
        actions = await self._action_repo.list_for_record(
            self._session, company_id=company_id, overtime_record_id=row.id
        )
        return overtime_record_to_read(row, actions=actions)

    async def _record_action(
        self,
        *,
        company_id: UUID,
        overtime_record_id: UUID,
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
                "overtime_record_id": overtime_record_id,
                "action": action,
                "actor_user_id": actor_user_id,
                "actor_employee_id": actor_employee_id,
                "stage": stage,
                "comment": comment,
            },
        )

    async def list_comp_off_facts(self, company_id: UUID) -> list[CompOffFactRow]:
        """LEAVE_DECISION_LOG.md LD-14 — the public seam Leave's L5 comp-off credit engine calls
        into (never queries `overtime_record` directly), mirroring how `LeaveAccrualService`
        already calls `EmploymentService`/`CalendarResolutionService` rather than reaching into
        their tables. Read-only, no `DataScope` narrowing — this is background-job-to-background-
        job, not a request-scoped read (same posture as `LeaveAccrualService.run_for_company`
        itself). Defined before `list()` below — that method's own name would otherwise shadow
        the builtin `list` for every annotation evaluated later in this class body (no
        `from __future__ import annotations` in this module)."""
        return await self._repo.list_comp_off_eligible(self._session, company_id=company_id)

    async def get(
        self,
        company_id: UUID,
        record_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> OvertimeRecordRead:
        row = await self._repo.get_by_id(self._session, company_id=company_id, record_id=record_id)
        if row is None:
            raise OvertimeRecordNotFoundError()
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        if visible_ids is not None and row.employee_id not in visible_ids:
            raise OvertimeRecordNotFoundError()
        return await self._read(row, company_id=company_id)

    async def list(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        status: str | None = None,
    ) -> tuple[list[OvertimeRecordRead], int]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        return [await self._read(r, company_id=company_id) for r in rows], total

    async def _get_reviewable(
        self,
        company_id: UUID,
        record_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> OvertimeRecord:
        row = await self._repo.get_by_id(self._session, company_id=company_id, record_id=record_id)
        if row is None:
            raise OvertimeRecordNotFoundError()
        if row.status != "PENDING" or row.approval_stage is None:
            raise OvertimeInvalidTransitionError()
        # WD-29 decision 4 — self-approval is always blocked, no policy escape hatch exists.
        if caller_employee_id is not None and row.employee_id == caller_employee_id:
            raise OvertimeSelfApprovalNotAllowedError()

        if row.approval_stage == "MANAGER":
            if caller_employee_id is None or caller_employee_id != row.resolved_approver_manager_id:
                raise OvertimeApproverMismatchError()
        else:  # HR
            if DataScopeLevel.COMPANY not in scope.levels:
                raise OvertimeApproverMismatchError(
                    "HR-stage approval requires a company-wide OVERTIME_APPROVE grant"
                )
        return row

    async def _stale_error(
        self, company_id: UUID, record_id: UUID
    ) -> OvertimeRecordNotFoundError | StaleOvertimeRecordResourceError:
        current = await self._repo.get_by_id(
            self._session, company_id=company_id, record_id=record_id
        )
        if current is None:
            return OvertimeRecordNotFoundError()
        current_read = await self._read(current, company_id=company_id)
        return StaleOvertimeRecordResourceError(
            "This overtime record has been modified by another request",
            current=overtime_record_to_audit_dict(current_read),
        )

    @logged_operation("attendance.overtime.approve")
    async def approve(
        self,
        company_id: UUID,
        record_id: UUID,
        body: OvertimeReviewInput,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimeRecordRead:
        row = await self._get_reviewable(
            company_id, record_id, scope=scope, caller_employee_id=caller_employee_id
        )
        # WD-30 — OT approve/reject writes `AttendanceDay.ot_minutes_approved`/
        # `comp_off_minutes_earned` directly (`mark_ot_approved`, below), entirely outside
        # `AttendanceDayService.calculate()` — its own `is_locked` check never runs for this
        # path, so the period check here is the *only* guard, not defence-in-depth.
        await _ensure_date_open(
            self._session, company_id, row.attendance_date, employee_id=row.employee_id
        )
        now = datetime.now(UTC)
        is_final_stage = not (
            row.approval_chain == "MANAGER_THEN_HR" and row.approval_stage == "MANAGER"
        )
        values: dict[str, Any] = (
            {
                "status": "APPROVED",
                "approval_stage": None,
                "minutes_approved": row.minutes_detected,
                "reviewed_by_user_id": actor_user_id,
                "reviewed_at": now,
                "reviewer_comment": body.reviewer_comment,
            }
            if is_final_stage
            else {"approval_stage": "HR"}
        )

        before_read = await self._read(row, company_id=company_id)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            record_id=record_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, record_id)

        if not is_final_stage:
            await self._record_action(
                company_id=company_id,
                overtime_record_id=record_id,
                action="STAGE_APPROVED",
                actor_user_id=actor_user_id,
                actor_employee_id=caller_employee_id,
                stage="MANAGER",
                comment=body.reviewer_comment,
            )
            read = await self._read(updated, company_id=company_id)
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="OVERTIME_STAGE_APPROVED",
                entity_type="overtime_record",
                entity_id=record_id,
                before=overtime_record_to_audit_dict(before_read),
                after=overtime_record_to_audit_dict(read),
                ip=ip_address,
                user_agent=user_agent,
            )
            return read

        await self._record_action(
            company_id=company_id,
            overtime_record_id=record_id,
            action="APPROVED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=row.approval_stage,
            comment=body.reviewer_comment,
        )
        await self._day_repo.mark_ot_approved(
            self._session,
            company_id=company_id,
            attendance_day_id=updated.attendance_day_id,
            minutes_approved=updated.minutes_approved,
            comp_off_minutes=updated.comp_off_minutes,
            now=now,
        )
        read = await self._read(updated, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_APPROVED",
            entity_type="overtime_record",
            entity_id=record_id,
            before=overtime_record_to_audit_dict(before_read),
            after=overtime_record_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        if updated.comp_off_minutes > 0:
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="COMP_OFF_EARNED",
                entity_type="overtime_record",
                entity_id=record_id,
                after={
                    "employee_id": str(updated.employee_id),
                    "attendance_date": updated.attendance_date.isoformat(),
                    "minutes": updated.comp_off_minutes,
                    "expiry_date": (
                        updated.comp_off_expiry_date.isoformat()
                        if updated.comp_off_expiry_date
                        else None
                    ),
                },
                ip=ip_address,
                user_agent=user_agent,
            )
        return read

    @logged_operation("attendance.overtime.reject")
    async def reject(
        self,
        company_id: UUID,
        record_id: UUID,
        body: OvertimeReviewInput,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        expected_version: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimeRecordRead:
        row = await self._get_reviewable(
            company_id, record_id, scope=scope, caller_employee_id=caller_employee_id
        )
        # WD-30 — OT approve/reject writes `AttendanceDay.ot_minutes_approved`/
        # `comp_off_minutes_earned` directly (`mark_ot_approved`, below), entirely outside
        # `AttendanceDayService.calculate()` — its own `is_locked` check never runs for this
        # path, so the period check here is the *only* guard, not defence-in-depth.
        await _ensure_date_open(
            self._session, company_id, row.attendance_date, employee_id=row.employee_id
        )
        now = datetime.now(UTC)
        before_read = await self._read(row, company_id=company_id)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            record_id=record_id,
            values={
                "status": "REJECTED",
                "approval_stage": None,
                "minutes_approved": 0,
                "comp_off_minutes": 0,
                "reviewed_by_user_id": actor_user_id,
                "reviewed_at": now,
                "reviewer_comment": body.reviewer_comment,
                "rejection_reason": body.rejection_reason,
            },
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, record_id)

        await self._record_action(
            company_id=company_id,
            overtime_record_id=record_id,
            action="REJECTED",
            actor_user_id=actor_user_id,
            actor_employee_id=caller_employee_id,
            stage=row.approval_stage,
            comment=body.rejection_reason or body.reviewer_comment,
        )
        # A rejected overtime record cannot become a payroll fact (mirrors WD-28's identical
        # regularization rule): the day's OT summary is cleared to zero, never left at whatever
        # the engine last provisionally detected.
        await self._day_repo.mark_ot_approved(
            self._session,
            company_id=company_id,
            attendance_day_id=updated.attendance_day_id,
            minutes_approved=0,
            comp_off_minutes=0,
            now=now,
        )
        read = await self._read(updated, company_id=company_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="OVERTIME_REJECTED",
            entity_type="overtime_record",
            entity_id=record_id,
            before=overtime_record_to_audit_dict(before_read),
            after=overtime_record_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read


# ---------------------------------------------------------------------------
# W8 — AttendancePeriod (architecture §4.2/§22, decision log WD-30)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PeriodScope:
    """Decision 14 — which employee-dates one legal-entity period owns. `members` are the
    employees with an employment in the period's entity overlapping the period; of their dates,
    the period owns those `_owning_legal_entity` attributes to its entity (so a mid-period
    transfer splits the employee between two entities' periods). `expected_dates` are the dates
    each member is employed in this entity inside the period — the ones that must have a
    calculated row before finalize."""

    legal_entity_id: UUID
    spans_by_employee: dict[UUID, list[_EntitySpan]]
    expected_dates: dict[UUID, set[date]]

    def owns(self, employee_id: UUID, target_date: date) -> bool:
        spans = self.spans_by_employee.get(employee_id)
        if spans is None or employee_id not in self.expected_dates:
            return False
        return _owning_legal_entity(spans, target_date) == self.legal_entity_id


@dataclass(frozen=True)
class PayrollPeriodInputs:
    """What Payroll reads from a `CLOSED` period: its identity and version (to detect a later
    reopen), the frozen per-employee summaries, and the payable overtime per employee, day class
    and multiplier (`AttendanceDayRepository.list_payable_overtime_for_period` — the days are
    locked while the period is closed, so this is as frozen as the summary)."""

    attendance_period_id: UUID
    version: int
    summaries: list[AttendancePeriodSummaryRead]
    overtime: list[tuple[UUID, str, Decimal | None, int]]


class AttendancePeriodService:
    """Period lifecycle (`OPEN` -> `CLOSED`), finalization validation, and the payroll-facing
    `AttendancePeriodSummary` snapshot. `CLOSED` *is* locked — closing a period is what actually
    sets `AttendanceDay.is_locked=true` across its range (via `AttendanceDayRepository.bulk_lock`)
    for the first time anywhere in this codebase; every other service in this module only ever
    *checked* that flag before this slice existed."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AttendancePeriodRepository()
        self._action_repo = AttendancePeriodActionRepository()
        self._summary_repo = AttendancePeriodSummaryRepository()
        self._day_repo = AttendanceDayRepository()
        self._reg_repo = AttendanceRegularizationRequestRepository()
        self._ot_repo = OvertimeRecordRepository()
        self._roster_repo = ShiftRosterRepository()
        self._policy_repo = AttendancePolicyRepository()
        self._audit = AuditService()

    async def _read(self, row: "AttendancePeriod") -> AttendancePeriodRead:
        actions = await self._action_repo.list_for_period(
            self._session, company_id=row.company_id, attendance_period_id=row.id
        )
        return attendance_period_to_read(row, actions=actions)

    async def _record_action(
        self,
        *,
        company_id: UUID,
        attendance_period_id: UUID,
        action: str,
        actor_user_id: UUID | None,
        comment: str | None,
    ) -> None:
        await self._action_repo.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "attendance_period_id": attendance_period_id,
                "action": action,
                "actor_user_id": actor_user_id,
                "comment": comment,
                "created_at": datetime.now(UTC),
            },
        )

    async def _get_or_404(self, company_id: UUID, period_id: UUID) -> "AttendancePeriod":
        row = await self._repo.get(self._session, company_id=company_id, period_id=period_id)
        if row is None:
            raise AttendancePeriodNotFoundError()
        return row

    async def _stale_error(
        self, company_id: UUID, period_id: UUID
    ) -> AttendancePeriodNotFoundError | StaleAttendancePeriodResourceError:
        current = await self._repo.get(self._session, company_id=company_id, period_id=period_id)
        if current is None:
            return AttendancePeriodNotFoundError()
        current_read = await self._read(current)
        return StaleAttendancePeriodResourceError(
            "This attendance period has been modified by another request",
            current=attendance_period_to_audit_dict(current_read),
        )

    async def create(
        self,
        company_id: UUID,
        body: AttendancePeriodCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePeriodRead:
        """Create always opens immediately (WD-30) — there is no separate "open" action."""
        from hrms.modules.organisation.service import OrganisationService

        try:
            await OrganisationService(self._session).get_legal_entity(
                company_id, body.legal_entity_id
            )
        except NotFoundError as exc:
            raise AttendancePeriodLegalEntityInvalidError() from exc

        now = datetime.now(UTC)
        period_id = uuid4()
        data = {
            "id": period_id,
            "company_id": company_id,
            "legal_entity_id": body.legal_entity_id,
            "period_start": body.period_start,
            "period_end": body.period_end,
            "label": body.label,
            "status": "OPEN",
            "opened_by_user_id": actor_user_id,
            "opened_at": now,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        try:
            row = await self._repo.insert(self._session, data=data)
        except IntegrityError as exc:
            raise AttendancePeriodOverlapError() from exc

        await self._record_action(
            company_id=company_id,
            attendance_period_id=period_id,
            action="OPENED",
            actor_user_id=actor_user_id,
            comment=None,
        )
        read = await self._read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_PERIOD_OPENED",
            entity_type="attendance_period",
            entity_id=period_id,
            after=attendance_period_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_periods(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        status: str | None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[list[AttendancePeriodRead], int]:
        rows, total = await self._repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            status=status,
            legal_entity_id=legal_entity_id,
        )
        return [await self._read(row) for row in rows], total

    async def get(self, company_id: UUID, period_id: UUID) -> AttendancePeriodRead:
        row = await self._get_or_404(company_id, period_id)
        return await self._read(row)

    # -- finalization validation --------------------------------------------------------

    async def _scope(self, company_id: UUID, period: "AttendancePeriod") -> _PeriodScope:
        """Built from every employment spell in the company (not only those overlapping the
        period) so a not-employed day is attributed exactly as `_ensure_date_open` attributes
        it for a single employee."""
        from hrms.modules.employee.service import EmploymentService

        spans = await EmploymentService(self._session).list_legal_entity_spans(company_id)
        spans_by_employee: dict[UUID, list[_EntitySpan]] = {}
        expected_dates: dict[UUID, set[date]] = {}
        for employee_id, legal_entity_id, joining_date, last_working_day in spans:
            spans_by_employee.setdefault(employee_id, []).append(
                (legal_entity_id, joining_date, last_working_day)
            )
            if legal_entity_id != period.legal_entity_id:
                continue
            span_start = max(joining_date, period.period_start)
            span_end = min(last_working_day or period.period_end, period.period_end)
            if span_start > span_end:
                continue
            dates = expected_dates.setdefault(employee_id, set())
            for offset in range((span_end - span_start).days + 1):
                dates.add(span_start + timedelta(days=offset))
        return _PeriodScope(
            legal_entity_id=period.legal_entity_id,
            spans_by_employee=spans_by_employee,
            expected_dates=expected_dates,
        )

    async def _owned_day_rows(
        self, company_id: UUID, period: "AttendancePeriod", scope: _PeriodScope
    ) -> list["AttendanceDay"]:
        day_rows = await self._day_repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=None,
            employee_id=None,
            date_from=period.period_start,
            date_to=period.period_end,
            status=None,
        )
        return [r for r in day_rows if scope.owns(r.employee_id, r.attendance_date)]

    async def _run_validation(
        self, company_id: UUID, period: "AttendancePeriod"
    ) -> tuple[AttendancePeriodValidationRead, list["AttendanceDay"]]:
        """Fail-closed (WD-21): any non-empty bucket blocks. Returns the raw `AttendanceDay`
        rows alongside the verdict so `finalize` never re-queries them — the summary snapshot
        and the lock-time INCOMPLETE resolution both need the exact same row set validation
        just inspected, not a second read that could race against it.

        Decision 14 — everything below is limited to the employee-dates this legal entity's
        period owns (`_PeriodScope`); another entity's blockers never hold this one up."""
        scope = await self._scope(company_id, period)
        day_rows = await self._owned_day_rows(company_id, period, scope)
        reasons: list[AttendancePeriodBlockingReason] = []

        # EMPLOYEES_WITHOUT_ATTENDANCE — every day an employee is employed in this entity inside
        # the period must have an `AttendanceDay` row (architecture §19.1: `calculate()` always
        # writes a row, even NOT_JOINED/EXITED/CONFIG_ERROR ones, once run — a missing row means
        # it was simply never run for that employee-date). Exact per-date comparison, not a row
        # count: a count lets `NOT_JOINED` rows computed before a mid-period joining date mask
        # missing days after it, and cannot tell two employment spans in the same period apart.
        dates_by_employee: dict[UUID, set[date]] = {}
        for day_row in day_rows:
            dates_by_employee.setdefault(day_row.employee_id, set()).add(day_row.attendance_date)
        missing_employees = [
            str(employee_id)
            for employee_id, expected_dates in scope.expected_dates.items()
            if not expected_dates <= dates_by_employee.get(employee_id, set())
        ]
        if missing_employees:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="EMPLOYEES_WITHOUT_ATTENDANCE",
                    message=(
                        "Some employees are missing calculated attendance for one or more days "
                        "in this period — run calculation for every employee-date before "
                        "finalizing"
                    ),
                    count=len(missing_employees),
                    sample=missing_employees[:20],
                )
            )

        # CONFIG_ERROR — WD-21 fail-closed, no lock-time resolution mechanism exists for this
        # (unlike INCOMPLETE, below); must be fixed and recomputed before finalize.
        config_error_rows = [r for r in day_rows if r.attendance_status == "CONFIG_ERROR"]
        if config_error_rows:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="CONFIG_ERROR",
                    message="Some attendance days have an unresolved configuration error",
                    count=len(config_error_rows),
                    sample=[
                        f"{r.employee_id}:{r.attendance_date.isoformat()}"
                        for r in config_error_rows[:20]
                    ],
                )
            )

        # WORK_ON_LEAVE_UNRESOLVED — BUS-012: punches on an approved full-day leave day must be
        # resolved by HR (cancel the leave, or confirm it stands) before the period can close.
        unresolved_leave_rows = [
            r for r in day_rows if r.work_on_leave_flagged and r.work_on_leave_resolution is None
        ]
        if unresolved_leave_rows:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="WORK_ON_LEAVE_UNRESOLVED",
                    message=(
                        "Some employees punched on a day of approved full-day leave — cancel "
                        "the leave or confirm it stands before finalizing"
                    ),
                    count=len(unresolved_leave_rows),
                    sample=[
                        f"{r.employee_id}:{r.attendance_date.isoformat()}"
                        for r in unresolved_leave_rows[:20]
                    ],
                )
            )

        # PAID_LOP_MISMATCH — PAY-003 reconciliation (PAYROLL_BUSINESS_DECISIONS.md "Derived
        # rules" #5): every employed day must split exactly into paid + LOP = 1.00, or the frozen
        # summary's `paid_days + lop_days = payable_days` invariant cannot hold. INCOMPLETE rows
        # are exempt here only because `finalize` resolves them to 1.00/0.00 or 0.00/1.00.
        mismatched_rows = [
            r
            for r in day_rows
            if r.attendance_status not in ("NOT_JOINED", "EXITED", "INCOMPLETE", "CONFIG_ERROR")
            and Decimal(str(r.paid_day_fraction))
            + Decimal(str(r.lop_fraction))
            + Decimal(str(r.unpaid_off_fraction))
            != Decimal("1.00")
        ]
        if mismatched_rows:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="PAID_LOP_MISMATCH",
                    message=(
                        "Some attendance days do not split exactly into paid and loss-of-pay — "
                        "recompute them before finalizing"
                    ),
                    count=len(mismatched_rows),
                    sample=[
                        f"{r.employee_id}:{r.attendance_date.isoformat()}"
                        for r in mismatched_rows[:20]
                    ],
                )
            )

        # INCOMPLETE_ATTENDANCE — architecture §11.4: a `KEEP_INCOMPLETE` policy blocks; a
        # `TREAT_ABSENT`/`TREAT_PRESENT` policy is auto-resolved by `finalize` itself, not a
        # blocker.
        incomplete_rows = [r for r in day_rows if r.attendance_status == "INCOMPLETE"]
        if incomplete_rows:
            version_ids = {
                r.attendance_policy_version_id
                for r in incomplete_rows
                if r.attendance_policy_version_id is not None
            }
            versions = await self._policy_repo.get_versions_by_ids(
                self._session, company_id=company_id, version_ids=version_ids
            )
            behaviour_by_version: dict[UUID | None, str] = {
                v.id: v.incomplete_at_lock_behaviour for v in versions
            }
            blocking_incomplete = [
                r
                for r in incomplete_rows
                if behaviour_by_version.get(r.attendance_policy_version_id, "TREAT_ABSENT")
                == "KEEP_INCOMPLETE"
            ]
            if blocking_incomplete:
                reasons.append(
                    AttendancePeriodBlockingReason(
                        code="INCOMPLETE_ATTENDANCE",
                        message=(
                            "Some attendance days are still INCOMPLETE under a policy that "
                            "requires manual resolution before locking (incomplete_at_lock_"
                            "behaviour=KEEP_INCOMPLETE)"
                        ),
                        count=len(blocking_incomplete),
                        sample=[
                            f"{r.employee_id}:{r.attendance_date.isoformat()}"
                            for r in blocking_incomplete[:20]
                        ],
                    )
                )

        # PENDING_REGULARIZATION
        pending_reg = await self._reg_repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=None,
            employee_id=None,
            date_from=period.period_start,
            date_to=period.period_end,
            status="SUBMITTED",
            request_type=None,
        )
        pending_reg = [r for r in pending_reg if scope.owns(r.employee_id, r.attendance_date)]
        if pending_reg:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="PENDING_REGULARIZATION",
                    message=(
                        "Some regularization requests in this period are still awaiting a decision"
                    ),
                    count=len(pending_reg),
                    sample=[
                        f"{r.employee_id}:{r.attendance_date.isoformat()}" for r in pending_reg[:20]
                    ],
                )
            )

        # PENDING_OVERTIME_APPROVAL
        pending_ot = await self._ot_repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=None,
            employee_id=None,
            date_from=period.period_start,
            date_to=period.period_end,
            status="PENDING",
        )
        pending_ot = [r for r in pending_ot if scope.owns(r.employee_id, r.attendance_date)]
        if pending_ot:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="PENDING_OVERTIME_APPROVAL",
                    message="Some detected overtime in this period is still awaiting approval",
                    count=len(pending_ot),
                    sample=[
                        f"{r.employee_id}:{r.attendance_date.isoformat()}" for r in pending_ot[:20]
                    ],
                )
            )

        # UNPUBLISHED_ROSTER
        draft_roster = await self._roster_repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=None,
            employee_id=None,
            date_from=period.period_start,
            date_to=period.period_end,
            status="DRAFT",
        )
        draft_roster = [r for r in draft_roster if scope.owns(r.employee_id, r.roster_date)]
        if draft_roster:
            reasons.append(
                AttendancePeriodBlockingReason(
                    code="UNPUBLISHED_ROSTER",
                    message="Some roster entries in this period are still DRAFT, not PUBLISHED",
                    count=len(draft_roster),
                    sample=[
                        f"{r.employee_id}:{r.roster_date.isoformat()}" for r in draft_roster[:20]
                    ],
                )
            )

        status = "BLOCKED" if reasons else "READY"
        result = AttendancePeriodValidationRead(
            status=status,
            reasons=reasons,
            validated_at=_format_timestamp(datetime.now(UTC)) or "",
        )
        return result, day_rows

    async def validate(self, company_id: UUID, period_id: UUID) -> AttendancePeriodValidationRead:
        period = await self._get_or_404(company_id, period_id)
        result, _ = await self._run_validation(company_id, period)
        now = datetime.now(UTC)
        await self._repo.record_validation(
            self._session, company_id=company_id, period_id=period_id, status=result.status, now=now
        )
        await self._record_action(
            company_id=company_id,
            attendance_period_id=period_id,
            action="VALIDATED" if result.status == "READY" else "VALIDATION_FAILED",
            actor_user_id=None,
            comment=f"{len(result.reasons)} blocking reason(s)" if result.reasons else None,
        )
        return result

    # -- summary aggregation --------------------------------------------------------

    @staticmethod
    def _aggregate_day_rows(
        day_rows: list["AttendanceDay"], *, period_days: int | None = None
    ) -> dict[UUID, dict[str, Any]]:
        """Pure read-side aggregation of already-computed `AttendanceDay` facts (architecture
        §22.2) — never derives a new attendance fact, only tallies existing ones.

        PAY-002/PAY-003 (`PAYROLL_BUSINESS_DECISIONS.md`, "Derived rules for the attendance
        period summary"): every day lands in exactly one bucket, split by `leave_fraction` when
        part of it was leave — `present`/`half`/`absent`/`leave`/`on_duty`/`holiday`/
        `weekly_off`/`incomplete`/`not_employed`. Working on a holiday or weekly off counts as
        `present` only (the calendar type is still visible via `worked_on_holiday`/
        `worked_on_weekly_off` on the day row), never also as `holiday`/`weekly_off`.

        `period_days` — passed by `finalize` only. There the EMPLOYEES_WITHOUT_ATTENDANCE gate
        guarantees a row for every employed day, so any day without an employed row is by
        construction a not-employed day. The live (OPEN) preview cannot assume that — a missing
        row there may just be uncalculated — so it counts only explicit NOT_JOINED/EXITED rows."""
        zero = Decimal("0.00")
        one = Decimal("1.00")
        by_employee: dict[UUID, dict[str, Any]] = {}
        for row in day_rows:
            agg = by_employee.setdefault(
                row.employee_id,
                {
                    "present_days": zero,
                    "absent_days": zero,
                    "leave_days": zero,
                    "holiday_days": zero,
                    "weekly_off_days": zero,
                    "half_days": zero,
                    "on_duty_days": zero,
                    "incomplete_days": zero,
                    "not_employed_days": zero,
                    "paid_days": zero,
                    "lop_days": zero,
                    "unpaid_off_days": zero,
                    "payable_days": zero,
                    "ot_minutes_normal": 0,
                    "ot_minutes_weekly_off": 0,
                    "ot_minutes_holiday": 0,
                    "ot_minutes_night": 0,
                    "comp_off_minutes_earned": 0,
                    "late_count": 0,
                    "worked_minutes_total": 0,
                    "paid_break_minutes_total": 0,
                    "unpaid_break_minutes_total": 0,
                    "auto_deducted_break_minutes_total": 0,
                    "actual_break_minutes_total": 0,
                    "excess_break_minutes_total": 0,
                    "unresolved_break_days": 0,
                },
            )
            status = row.attendance_status
            if status in ("NOT_JOINED", "EXITED"):
                agg["not_employed_days"] += one
                continue

            paid = Decimal(str(row.paid_day_fraction))
            lop = Decimal(str(row.lop_fraction))
            agg["payable_days"] += one
            agg["paid_days"] += paid
            agg["lop_days"] += lop
            agg["unpaid_off_days"] += Decimal(str(row.unpaid_off_fraction or 0))

            leave_part = min(Decimal(str(row.leave_fraction or 0)), one)
            if status == "LEAVE" and leave_part == zero:
                # A LEAVE row computed before `leave_fraction` existed and never backfilled
                # (locked history) — it can only mean a full-day leave.
                leave_part = one
            # PAY-012 — the off half of a half-day weekly off.
            off_part = min(Decimal(str(row.weekly_off_fraction or 0)), one - leave_part)
            rest = one - leave_part - off_part
            agg["leave_days"] += leave_part
            agg["weekly_off_days"] += off_part
            if rest > zero:
                if status in ("PRESENT", "WFH"):
                    agg["present_days"] += rest
                elif status == "HALF_DAY":
                    # With leave or a half weekly off: the worked remainder. Without either: a
                    # band-derived half day (0.50 paid / 0.50 LOP), counted as one day.
                    split_day = leave_part > zero or off_part > zero
                    agg["present_days" if split_day else "half_days"] += rest
                elif status in ("ABSENT", "LEAVE"):
                    # LEAVE with rest > 0 = half-day leave, unworked other half (LOP).
                    agg["absent_days"] += rest
                elif status == "ON_DUTY":
                    agg["on_duty_days"] += rest
                elif status == "NOT_EXPECTED":
                    if row.calendar_day_type in ("HOLIDAY", "SHUTDOWN"):
                        agg["holiday_days"] += rest
                    else:  # WEEKLY_OFF, or a roster week-off on a calendar WORKING day
                        agg["weekly_off_days"] += rest
                elif status == "INCOMPLETE" and paid > zero:
                    agg["present_days"] += rest  # resolved TREAT_PRESENT at lock
                elif status == "INCOMPLETE" and lop > zero:
                    agg["absent_days"] += rest  # resolved TREAT_ABSENT at lock
                else:  # unresolved INCOMPLETE, CONFIG_ERROR
                    agg["incomplete_days"] += rest

            # Bucket by the engine's day class, never the policy's configurable rate code.
            ot_day_class = row.ot_day_class
            if ot_day_class == "WEEKLY_OFF":
                agg["ot_minutes_weekly_off"] += row.ot_minutes_approved
            elif ot_day_class == "HOLIDAY":
                agg["ot_minutes_holiday"] += row.ot_minutes_approved
            elif ot_day_class == "NIGHT":
                agg["ot_minutes_night"] += row.ot_minutes_approved
            elif row.ot_minutes_approved:
                agg["ot_minutes_normal"] += row.ot_minutes_approved
            agg["comp_off_minutes_earned"] += row.comp_off_minutes_earned
            if row.is_late:
                agg["late_count"] += 1
            agg["worked_minutes_total"] += row.worked_minutes
            agg["paid_break_minutes_total"] += row.paid_break_minutes or 0
            agg["unpaid_break_minutes_total"] += row.unpaid_break_minutes or 0
            agg["auto_deducted_break_minutes_total"] += row.auto_deducted_break_minutes or 0
            agg["actual_break_minutes_total"] += row.actual_break_minutes or 0
            agg["excess_break_minutes_total"] += row.excess_break_minutes or 0
            if row.has_unresolved_break:
                agg["unresolved_break_days"] += 1

        if period_days is not None:
            for agg in by_employee.values():
                agg["not_employed_days"] = Decimal(period_days) - agg["payable_days"]
        return by_employee

    @staticmethod
    def _assert_summary_reconciles(
        aggregates: dict[UUID, dict[str, Any]], *, period_days: int
    ) -> None:
        """PAY-003 reconciliation invariant, asserted on the exact values about to be frozen.
        Unreachable when validation passed (`PAID_LOP_MISMATCH`, INCOMPLETE resolution, the
        EMPLOYEES_WITHOUT_ATTENDANCE gate) — a failure here is a bug, and the whole finalize
        transaction must roll back rather than freeze figures Payroll would pay from."""
        bucket_keys = (
            "present_days",
            "half_days",
            "absent_days",
            "leave_days",
            "on_duty_days",
            "holiday_days",
            "weekly_off_days",
            "incomplete_days",
            "not_employed_days",
        )
        for employee_id, agg in aggregates.items():
            bucket_total = sum((agg[key] for key in bucket_keys), Decimal("0.00"))
            if bucket_total != Decimal(period_days):
                raise AttendanceSummaryReconciliationError(
                    f"Summary buckets for employee {employee_id} total {bucket_total}, "
                    f"expected {period_days} days"
                )
            if agg["paid_days"] + agg["lop_days"] + agg["unpaid_off_days"] != agg["payable_days"]:
                raise AttendanceSummaryReconciliationError(
                    f"paid_days + lop_days + unpaid_off_days != payable_days for employee "
                    f"{employee_id}"
                )

    async def get_summary(
        self,
        company_id: UUID,
        period_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> list[AttendancePeriodSummaryRead]:
        """ "Regenerated only while unlocked; frozen at lock/snapshot" (architecture §4.2) — an
        `OPEN` period computes a live, unpersisted preview on every call; a `CLOSED` period
        returns the frozen rows `finalize` wrote once and only once.

        DEF-B6-02 — each row is one employee's attendance, so the caller sees only the
        employees their data scope allows (`None` = COMPANY, no filter). `scope` is required
        and has no default so a caller can never skip the narrowing by omission."""
        period = await self._get_or_404(company_id, period_id)
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        if period.status == "CLOSED":
            rows = await self._summary_repo.list_for_period(
                self._session, company_id=company_id, attendance_period_id=period_id
            )
            return [
                attendance_period_summary_to_read(row, frozen=True)
                for row in rows
                if visible_ids is None or row.employee_id in visible_ids
            ]

        scope = await self._scope(company_id, period)
        day_rows = await self._owned_day_rows(company_id, period, scope)
        now_str = _format_timestamp(datetime.now(UTC)) or ""
        aggregates = self._aggregate_day_rows(day_rows)
        return [
            AttendancePeriodSummaryRead(
                employee_id=employee_id,
                present_days=str(agg["present_days"]),
                absent_days=str(agg["absent_days"]),
                leave_days=str(agg["leave_days"]),
                holiday_days=str(agg["holiday_days"]),
                weekly_off_days=str(agg["weekly_off_days"]),
                half_days=str(agg["half_days"]),
                lop_days=str(agg["lop_days"]),
                on_duty_days=str(agg["on_duty_days"]),
                incomplete_days=str(agg["incomplete_days"]),
                not_employed_days=str(agg["not_employed_days"]),
                unpaid_off_days=str(agg["unpaid_off_days"]),
                paid_days=str(agg["paid_days"]),
                payable_days=str(agg["payable_days"]),
                ot_minutes_normal=agg["ot_minutes_normal"],
                ot_minutes_weekly_off=agg["ot_minutes_weekly_off"],
                ot_minutes_holiday=agg["ot_minutes_holiday"],
                ot_minutes_night=agg["ot_minutes_night"],
                comp_off_minutes_earned=agg["comp_off_minutes_earned"],
                late_count=agg["late_count"],
                worked_minutes_total=agg["worked_minutes_total"],
                paid_break_minutes_total=agg["paid_break_minutes_total"],
                unpaid_break_minutes_total=agg["unpaid_break_minutes_total"],
                auto_deducted_break_minutes_total=agg["auto_deducted_break_minutes_total"],
                actual_break_minutes_total=agg["actual_break_minutes_total"],
                excess_break_minutes_total=agg["excess_break_minutes_total"],
                unresolved_break_days=agg["unresolved_break_days"],
                generated_at=now_str,
                frozen=False,
            )
            for employee_id, agg in aggregates.items()
            if visible_ids is None or employee_id in visible_ids
        ]

    # -- payroll seams (payroll plan Phase 5.2) ---------------------------------------

    async def closed_period_for_month(
        self, company_id: UUID, legal_entity_id: UUID, period_start: date, period_end: date
    ) -> "PayrollPeriodInputs | None":
        """PD-2 — the only way Payroll reads attendance: the legal entity's period covering
        exactly the pay month, and only when it is `CLOSED`, with its frozen summary rows.
        `None` when there is no such period or it is still open."""
        period = await self._repo.get_for_range(
            self._session,
            company_id=company_id,
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
        )
        if period is None or period.status != "CLOSED":
            return None
        rows = await self._summary_repo.list_for_period(
            self._session, company_id=company_id, attendance_period_id=period.id
        )
        overtime = await self._day_repo.list_payable_overtime_for_period(
            self._session, company_id=company_id, attendance_period_id=period.id
        )
        return PayrollPeriodInputs(
            attendance_period_id=period.id,
            version=period.version,
            summaries=[attendance_period_summary_to_read(row, frozen=True) for row in rows],
            overtime=overtime,
        )

    async def period_state(self, company_id: UUID, period_id: UUID) -> tuple[str, int] | None:
        """`(status, version)` — Payroll re-checks this before approving or finalising a run, so a
        period reopened after the run's inputs were locked is caught."""
        period = await self._repo.get(self._session, company_id=company_id, period_id=period_id)
        return (period.status, period.version) if period is not None else None

    # -- finalize / reopen --------------------------------------------------------

    async def _apply_incomplete_lock_resolution(
        self,
        company_id: UUID,
        period_id: UUID,
        day_rows: list["AttendanceDay"],
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Architecture §11.4 — resolves every still-`INCOMPLETE` day's `paid_day_fraction`/
        `lop_fraction` per its own snapshotted policy's `incomplete_at_lock_behaviour`
        immediately before locking. `_run_validation` already guarantees no `KEEP_INCOMPLETE`
        row reaches this point.

        PAY-007: the resolved values are written onto the in-memory rows with
        `set_committed_value` as well as to the database, so the summary `finalize` aggregates
        next is computed from the resolved figures explicitly rather than depending on the ORM
        synchronizing a Core `UPDATE` into objects already loaded. The rewrite is recorded as
        one audit row per period listing every resolved day."""
        incomplete_rows = [r for r in day_rows if r.attendance_status == "INCOMPLETE"]
        if not incomplete_rows:
            return
        version_ids = {
            r.attendance_policy_version_id
            for r in incomplete_rows
            if r.attendance_policy_version_id is not None
        }
        versions = await self._policy_repo.get_versions_by_ids(
            self._session, company_id=company_id, version_ids=version_ids
        )
        behaviour_by_version: dict[UUID | None, str] = {
            v.id: v.incomplete_at_lock_behaviour for v in versions
        }
        now = datetime.now(UTC)
        resolved: list[dict[str, Any]] = []
        for row in incomplete_rows:
            behaviour = behaviour_by_version.get(row.attendance_policy_version_id, "TREAT_ABSENT")
            # PAY-012 — the off half of a half-day weekly off is never LOP; BUS-001 — for a
            # daily-wage employee that half is unpaid rather than paid.
            off = Decimal(str(row.weekly_off_fraction or 0)).quantize(Decimal("0.01"))
            unpaid_off = Decimal(str(row.unpaid_off_fraction or 0)).quantize(Decimal("0.01"))
            if behaviour == "TREAT_PRESENT":
                paid_day_fraction, lop_fraction = Decimal("1.00") - unpaid_off, Decimal("0.00")
            else:  # TREAT_ABSENT (default) — KEEP_INCOMPLETE already blocked validation
                behaviour = "TREAT_ABSENT"
                paid_day_fraction, lop_fraction = off - unpaid_off, Decimal("1.00") - off
            resolved.append(
                {
                    "attendance_day_id": str(row.id),
                    "employee_id": str(row.employee_id),
                    "attendance_date": row.attendance_date.isoformat(),
                    "behaviour": behaviour,
                    "before": {
                        "paid_day_fraction": str(row.paid_day_fraction),
                        "lop_fraction": str(row.lop_fraction),
                    },
                    "after": {
                        "paid_day_fraction": str(paid_day_fraction),
                        "lop_fraction": str(lop_fraction),
                    },
                }
            )
            await self._day_repo.set_lock_time_incomplete_resolution(
                self._session,
                company_id=company_id,
                attendance_day_id=row.id,
                paid_day_fraction=paid_day_fraction,
                lop_fraction=lop_fraction,
                now=now,
            )
            set_committed_value(row, "paid_day_fraction", paid_day_fraction)
            set_committed_value(row, "lop_fraction", lop_fraction)

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK",
            entity_type="attendance_period",
            entity_id=period_id,
            before=None,
            after={"resolved_days": resolved},
            ip=ip_address,
            user_agent=user_agent,
        )

    async def finalize(
        self,
        company_id: UUID,
        period_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePeriodRead:
        """Fail-closed, race-safe, atomic (WD-30): re-validates fresh (never trusts
        `last_validation_status`), then wins the version-guarded `status='CLOSED'` write
        *before* touching any `AttendanceDay`/`AttendancePeriodSummary` row — a losing
        concurrent finalize aborts cheaply, before locking anything, and the whole request is
        one transaction, so any failure after the version-guarded write rolls that write back
        too (no partial finalization)."""
        # Leave approvals and reversals change attendance days; wait for the ones in flight and
        # make later ones wait for this finalisation (`core/db/locks.py`), so the summary frozen
        # below is built from days no leave change can alter underneath it.
        await lock_attendance_period_close(self._session, company_id, exclusive=True)
        period = await self._get_or_404(company_id, period_id)
        if period.status != "OPEN":
            raise AttendancePeriodInvalidTransitionError("Only an OPEN period can be finalized")

        # A BLOCKED verdict raises immediately, aborting this transaction — neither the
        # validation-status cache nor a `VALIDATION_FAILED` action would survive being written
        # here anyway, so this deliberately does not attempt either (unlike the standalone
        # `validate()` above, which never raises and therefore can and does persist both). A
        # caller wanting a persisted, audited BLOCKED record ahead of attempting finalize should
        # call `POST .../validate` first.
        result, day_rows = await self._run_validation(company_id, period)
        if result.status != "READY":
            raise AttendancePeriodFinalizationBlockedError(
                reasons=[r.model_dump() for r in result.reasons]
            )

        now = datetime.now(UTC)

        before_read = await self._read(period)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            period_id=period_id,
            values={"status": "CLOSED", "closed_by_user_id": actor_user_id, "closed_at": now},
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, period_id)

        await self._apply_incomplete_lock_resolution(
            company_id,
            period_id,
            day_rows,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        period_days = (period.period_end - period.period_start).days + 1
        aggregates = self._aggregate_day_rows(day_rows, period_days=period_days)
        self._assert_summary_reconciles(aggregates, period_days=period_days)
        summary_rows = [
            {
                "id": uuid4(),
                "company_id": company_id,
                "attendance_period_id": period_id,
                "employee_id": employee_id,
                **agg,
                "generated_at": now,
                "created_at": now,
                "updated_at": now,
            }
            for employee_id, agg in aggregates.items()
        ]
        await self._summary_repo.replace_for_period(
            self._session,
            company_id=company_id,
            attendance_period_id=period_id,
            rows=summary_rows,
        )

        await self._day_repo.bulk_lock(
            self._session,
            company_id=company_id,
            attendance_day_ids=[r.id for r in day_rows],
            attendance_period_id=period_id,
            locked_by=actor_user_id,
            now=now,
        )

        await self._record_action(
            company_id=company_id,
            attendance_period_id=period_id,
            action="CLOSED",
            actor_user_id=actor_user_id,
            comment=None,
        )
        read = await self._read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_PERIOD_CLOSED",
            entity_type="attendance_period",
            entity_id=period_id,
            before=attendance_period_to_audit_dict(before_read),
            after=attendance_period_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    @logged_operation("attendance.period.reopen")
    async def reopen(
        self,
        company_id: UUID,
        period_id: UUID,
        body: AttendancePeriodReopenInput,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePeriodRead:
        """`ATTENDANCE.UNLOCK` (architecture §13.4/§23.2) — clears `AttendanceDay.is_locked`
        on the days this period's finalize locked and reopens it for correction. Does not
        recompute or restore anything by itself; a day made mutable again is only actually
        changed by a later, ordinary `calculate()`/regularization/adjustment call, and
        re-finalizing regenerates a
        fresh frozen `AttendancePeriodSummary` snapshot (`AttendancePeriodSummaryRepository.
        replace_for_period` is a full delete/recreate, never a stale leftover)."""
        # Exclusive against payroll finalisation (`core/db/locks.py`): a run cannot finalise on
        # this period while it reopens, and the finalised-run check below reads what such a run
        # committed. Taken before the period is read so both reads are fresh.
        await lock_attendance_period_close(self._session, company_id, exclusive=True)
        period = await self._get_or_404(company_id, period_id)
        if period.status != "CLOSED":
            raise AttendancePeriodInvalidTransitionError("Only a CLOSED period can be reopened")
        # Decision 15 — a month whose payroll is finalised never reopens.
        from hrms.modules.payroll.service import PayRunService

        if await PayRunService(self._session).has_finalised_run_for_period(company_id, period_id):
            raise AttendancePeriodPayrollFinalisedError()

        before_read = await self._read(period)
        now = datetime.now(UTC)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            period_id=period_id,
            values={
                "status": "OPEN",
                "reopened_by_user_id": actor_user_id,
                "reopened_at": now,
                "reopen_reason": body.reason,
            },
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise await self._stale_error(company_id, period_id)

        await self._day_repo.bulk_unlock(
            self._session, company_id=company_id, attendance_period_id=period_id, now=now
        )

        await self._record_action(
            company_id=company_id,
            attendance_period_id=period_id,
            action="REOPENED",
            actor_user_id=actor_user_id,
            comment=body.reason,
        )
        read = await self._read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_PERIOD_REOPENED",
            entity_type="attendance_period",
            entity_id=period_id,
            before=attendance_period_to_audit_dict(before_read),
            after=attendance_period_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read


@dataclass(frozen=True)
class _BackingLeaveDay:
    """LM-14 - the authoritative values a leave projection is derived from."""

    leave_type_id: UUID
    leave_type_code: str | None
    fraction: Decimal
    half: str | None
    is_paid: bool


class LeaveProjectionService:
    """W9 — the Leave -> Attendance projection adapter (architecture §21, decision log WD-31).
    `sync`/`cancel` are the two mutating operations a future Leave module (or, until it exists,
    an authorized internal/test caller under `ATTENDANCE.LEAVE_PROJECTION_SYNC`) uses to publish
    or withdraw an approved leave day projection; each triggers a synchronous in-process
    recompute of the affected `AttendanceDay` (architecture §25 — acceptable "since the ADR-0012
    event/outbox infra doesn't exist yet"). Reads (`list_projections`/`get_projection`) reuse
    `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL`, mirroring every other read-reuse precedent in this
    module (WD-28 decision 6 / WD-29 decision 6 / WD-30's identical reasoning)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = LeaveDayProjectionRepository()
        self._audit = AuditService()

    async def sync(
        self,
        company_id: UUID,
        body: LeaveProjectionSync,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveDayProjectionRead:
        await _ensure_employee_visible(
            self._session, company_id, body.employee_id, scope, caller_employee_id
        )
        # D3 / LM-14 - leave is only ever projected onto a date inside an employment spell. The
        # leave-dates lock (the first lock in the Leave ordering; reentrant when the caller is a
        # leave approval that already holds it) keeps a termination from moving the last working
        # day between this check and the write.
        from hrms.modules.employee.service import EmploymentService

        await lock_employee_leave_dates(self._session, company_id, body.employee_id)
        # LM-14 - a projection is only ever the shadow of a real APPROVED leave application. The
        # application, its day row and every projected value come from Leave's own tables; the
        # request body names *which* day, never *what* it is.
        backing = await self._resolve_backing_leave_day(company_id, body)
        coverage = await EmploymentService(self._session).check_employment_coverage(
            company_id, body.employee_id, body.attendance_date
        )
        if not coverage.is_valid:
            raise LeaveProjectionOutsideEmploymentError(
                reason=coverage.status.value, offending_date=body.attendance_date
            )
        # §21 — "Leave module must consult AttendanceLock (service). Default refuse." A closed
        # period refuses the publish outright, before any row is written or recomputed.
        await _ensure_date_open(
            self._session, company_id, body.attendance_date, employee_id=body.employee_id
        )

        existing = await self._repo.get_by_natural_key(
            self._session,
            company_id=company_id,
            employee_id=body.employee_id,
            attendance_date=body.attendance_date,
            leave_application_id=body.leave_application_id,
        )
        other_active = [
            p
            for p in await self._repo.list_active_for_employee_date(
                self._session,
                company_id=company_id,
                employee_id=body.employee_id,
                attendance_date=body.attendance_date,
            )
            if existing is None or p.id != existing.id
        ]
        already_active = sum((Decimal(str(p.fraction)) for p in other_active), Decimal("0.00"))
        if already_active + backing.fraction > Decimal("1.00"):
            raise LeaveProjectionOverlapError()

        now = datetime.now(UTC)
        before_read = leave_day_projection_to_read(existing) if existing is not None else None
        row: LeaveDayProjection | None
        if existing is None:
            row = await self._repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": body.employee_id,
                    "attendance_date": body.attendance_date,
                    "leave_application_id": body.leave_application_id,
                    "leave_type_id": backing.leave_type_id,
                    "leave_type_code": backing.leave_type_code,
                    "fraction": backing.fraction,
                    "half": backing.half,
                    "is_paid": backing.is_paid,
                    "status": "APPROVED",
                    "source_version": 1,
                    "synced_at": now,
                    "cancelled_at": None,
                    "cancelled_reason": None,
                    "created_by_user_id": actor_user_id,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            action = "LEAVE_PROJECTION_SYNCED"
        else:
            # A resync of the same natural key is a correction, not a new fact (mirrors
            # `AttendanceDay`'s own full-replace-on-recompute posture, WD-10) — it also revives a
            # previously `CANCELLED` row rather than leaving it orphaned.
            row = await self._repo.update(
                self._session,
                company_id=company_id,
                projection_id=existing.id,
                values={
                    "leave_type_id": backing.leave_type_id,
                    "leave_type_code": backing.leave_type_code,
                    "fraction": backing.fraction,
                    "half": backing.half,
                    "is_paid": backing.is_paid,
                    "status": "APPROVED",
                    "source_version": existing.source_version + 1,
                    "synced_at": now,
                    "cancelled_at": None,
                    "cancelled_reason": None,
                },
                expected_version=existing.version,
                now=now,
            )
            if row is None:
                raise await self._stale_error(company_id, existing.id)
            action = "LEAVE_PROJECTION_RESYNCED"

        read = leave_day_projection_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="leave_day_projection",
            entity_id=row.id,
            before=leave_day_projection_to_audit_dict(before_read) if before_read else None,
            after=leave_day_projection_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )

        # Recompute-on-event (architecture §30's own naming for this slice) — an in-process call,
        # not a real event bus (§25), exactly like every other cross-module seam in this module.
        await AttendanceDayService(self._session).calculate(
            company_id,
            body.employee_id,
            body.attendance_date,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _resolve_backing_leave_day(
        self, company_id: UUID, body: LeaveProjectionSync
    ) -> "_BackingLeaveDay":
        """LM-14 - resolve the authoritative leave facts for one projection. Looked up by
        application id + company, then checked against the employee, so a foreign company's or
        another employee's application is indistinguishable from a missing one."""
        from hrms.modules.leave.repository import (
            LeaveApplicationDayRepository,
            LeaveApplicationRepository,
            LeaveTypeRepository,
        )

        application = await LeaveApplicationRepository().get(
            self._session, company_id=company_id, application_id=body.leave_application_id
        )
        if application is None or application.employee_id != body.employee_id:
            raise LeaveProjectionApplicationNotFoundError()
        if application.status != "APPROVED":
            raise LeaveProjectionApplicationNotApprovedError(status=application.status)
        day = await LeaveApplicationDayRepository().get_for_date(
            self._session,
            company_id=company_id,
            leave_application_id=application.id,
            calendar_date=body.attendance_date,
        )
        if day is None:
            raise LeaveProjectionDateNotInApplicationError(offending_date=body.attendance_date)
        leave_type = await LeaveTypeRepository().get(
            self._session, company_id=company_id, leave_type_id=application.leave_type_id
        )
        half_to_projection_half = {"FIRST_HALF": "FIRST", "SECOND_HALF": "SECOND"}
        return _BackingLeaveDay(
            leave_type_id=application.leave_type_id,
            leave_type_code=leave_type.code if leave_type is not None else None,
            fraction=Decimal(day.fraction).quantize(Decimal("0.01")),
            half=half_to_projection_half.get(day.half) if day.half else None,
            # Mirrors what approval has always projected: the type's paid default, unless this
            # day was approved as loss of pay.
            is_paid=(leave_type.is_paid_default if leave_type is not None else True)
            and not day.is_lop,
        )

    async def cancel(
        self,
        company_id: UUID,
        projection_id: UUID,
        body: LeaveProjectionCancelInput,
        *,
        expected_version: int,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeaveDayProjectionRead:
        existing = await self._repo.get(
            self._session, company_id=company_id, projection_id=projection_id
        )
        if existing is None:
            raise LeaveProjectionNotFoundError()
        await _ensure_employee_visible(
            self._session, company_id, existing.employee_id, scope, caller_employee_id
        )
        # §21 "Leave approved after payroll lock... default refuse" applies symmetrically to
        # cancellation — refuse rather than silently rewriting an already-locked day. Matches
        # PD-LOCK-2's scope boundary (W8): no arrears mechanism exists, so the only correction
        # path for a locked date is a full `ATTENDANCE.UNLOCK` period reopen.
        await _ensure_date_open(
            self._session, company_id, existing.attendance_date, employee_id=existing.employee_id
        )

        before_read = leave_day_projection_to_read(existing)
        now = datetime.now(UTC)
        row = await self._repo.update(
            self._session,
            company_id=company_id,
            projection_id=projection_id,
            values={"status": "CANCELLED", "cancelled_at": now, "cancelled_reason": body.reason},
            expected_version=expected_version,
            now=now,
        )
        if row is None:
            raise await self._stale_error(company_id, projection_id)

        read = leave_day_projection_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_PROJECTION_CANCELLED",
            entity_type="leave_day_projection",
            entity_id=projection_id,
            before=leave_day_projection_to_audit_dict(before_read),
            after=leave_day_projection_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )

        await AttendanceDayService(self._session).calculate(
            company_id,
            existing.employee_id,
            existing.attendance_date,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_projections(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> tuple[list[LeaveDayProjectionRead], int]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._repo.page_filtered(
            self._session,
            page=page,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        return [leave_day_projection_to_read(r) for r in rows], total

    async def get_projection(
        self,
        company_id: UUID,
        projection_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> LeaveDayProjectionRead:
        row = await self._repo.get(
            self._session, company_id=company_id, projection_id=projection_id
        )
        if row is None:
            raise LeaveProjectionNotFoundError()
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        if visible_ids is not None and row.employee_id not in visible_ids:
            raise LeaveProjectionNotFoundError()
        return leave_day_projection_to_read(row)

    async def _stale_error(
        self, company_id: UUID, projection_id: UUID
    ) -> LeaveProjectionNotFoundError | StaleLeaveProjectionResourceError:
        current = await self._repo.get(
            self._session, company_id=company_id, projection_id=projection_id
        )
        if current is None:
            return LeaveProjectionNotFoundError()
        current_read = leave_day_projection_to_read(current)
        return StaleLeaveProjectionResourceError(
            "This leave projection has been modified since you last read it",
            current=leave_day_projection_to_audit_dict(current_read),
        )

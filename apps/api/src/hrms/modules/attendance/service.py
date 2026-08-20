"""Business logic for the attendance module — the public interface for other modules.

One service class per Module Standard, covering all three policy families (Attendance/Overtime/
Regularization — WD-03 locked as separate identities, not one mega-policy) since they share
identical CRUD/versioning/publish mechanics. Mirrors `organisation.service.OrganisationService`'s
`ShiftVersion` methods (create/list/get/update/discard/publish/resolve_as_of) three times over,
plus policy-resolution delegation (§16/§19 step 7)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import NotFoundError, PermissionDeniedError, ValidationError
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.attendance import calculation as calc
from hrms.modules.attendance.exceptions import (
    AttendanceDayLockedError,
    DuplicatePunchIdempotencyKeyError,
    InvalidPolicyBandError,
    InvalidPolicyRateRowError,
    InvalidRegularizationAllowedTypeError,
    PolicyCodeAlreadyExistsError,
    PolicyDraftAlreadyExistsError,
    PolicyPublishIncompleteError,
    PolicyVersionNotDraftError,
    PolicyVersionNotFoundForDateError,
    PolicyVersionOverlapError,
    PolicyVersionPreviousVersionRequiredError,
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
    StalePolicyResourceError,
    StaleRegularizationRequestResourceError,
    StaleShiftRosterResourceError,
)
from hrms.modules.attendance.models import AttendanceDay, AttendanceRegularizationRequest
from hrms.modules.attendance.repository import (
    AttendanceBreakRepository,
    AttendanceDayRepository,
    AttendancePolicyRepository,
    AttendanceRegularizationActionRepository,
    AttendanceRegularizationRequestedPunchRepository,
    AttendanceRegularizationRequestRepository,
    OvertimePolicyRepository,
    PunchRepository,
    RegularizationPolicyRepository,
    ShiftRosterRepository,
)
from hrms.modules.attendance.resolution import PolicyResolutionService
from hrms.modules.attendance.schemas import (
    AttendanceDayRead,
    AttendancePolicyCreate,
    AttendancePolicyRead,
    AttendancePolicyUpdate,
    AttendancePolicyVersionCreate,
    AttendancePolicyVersionPublishRequest,
    AttendancePolicyVersionRead,
    AttendancePolicyVersionUpdate,
    OvertimePolicyCreate,
    OvertimePolicyRead,
    OvertimePolicyUpdate,
    OvertimePolicyVersionCreate,
    OvertimePolicyVersionPublishRequest,
    OvertimePolicyVersionRead,
    OvertimePolicyVersionUpdate,
    PolicyResolutionRead,
    PunchCreate,
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
    _parse_time,
    attendance_day_to_audit_dict,
    attendance_day_to_read,
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
    overtime_policy_to_audit_dict,
    overtime_policy_to_read,
    overtime_policy_version_to_audit_dict,
    overtime_policy_version_to_read,
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
                    "code": body.code,
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

    async def list_attendance_policies(self, company_id: UUID) -> list[AttendancePolicyRead]:
        rows = await self._attendance_repo.list_policies(self._session, company_id=company_id)
        return [attendance_policy_to_read(r) for r in rows]

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
                "incomplete_at_lock_behaviour": body.incomplete_at_lock_behaviour,
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
                    "code": body.code,
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

    async def list_overtime_policies(self, company_id: UUID) -> list[OvertimePolicyRead]:
        rows = await self._overtime_repo.list_policies(self._session, company_id=company_id)
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
                    "code": body.code,
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
        self, company_id: UUID
    ) -> list[RegularizationPolicyRead]:
        rows = await self._regularization_repo.list_policies(self._session, company_id=company_id)
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

    async def policy_exists(self, company_id: UUID, policy_kind: str, policy_id: UUID) -> bool:
        row: Any
        if policy_kind == "ATTENDANCE_POLICY":
            row = await self._attendance_repo.get_policy(
                self._session, company_id=company_id, policy_id=policy_id
            )
        elif policy_kind == "OVERTIME_POLICY":
            row = await self._overtime_repo.get_policy(
                self._session, company_id=company_id, policy_id=policy_id
            )
        elif policy_kind == "REGULARIZATION_POLICY":
            row = await self._regularization_repo.get_policy(
                self._session, company_id=company_id, policy_id=policy_id
            )
        else:
            return False
        return row is not None


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
    scope: DataScope,
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
    await employee_service.get_employee(
        company_id, target_employee_id, scope=scope, caller_employee_id=caller_employee_id
    )


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
        before_read = shift_roster_to_read(row)

        values = build_shift_roster_update_values(patch)
        if not values:
            return before_read

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
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> list[ShiftRosterRead]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
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
        return [shift_roster_to_read(r) for r in rows]


class PunchService:
    """Punch ingestion (architecture §19.1 step 9, WD-11 — punches are immutable, append-only
    once written; corrections are new punches, never an UPDATE/DELETE of this row)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PunchRepository()
        self._audit = AuditService()

    async def record_punch(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: PunchCreate,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        default_source: str,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PunchRead:
        """Idempotent on `idempotency_key` when the caller supplies one — a resubmission with
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
        idempotency lookup, so a forged/out-of-scope `employee_id` never touches punch state."""
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )

        if body.idempotency_key:
            existing = await self._repo.get_by_idempotency_key(
                self._session, company_id=company_id, idempotency_key=body.idempotency_key
            )
            if existing is not None:
                return punch_to_read(existing)

        now = datetime.now(UTC)
        punch_id = uuid4()
        data = {
            "id": punch_id,
            "company_id": company_id,
            "employee_id": employee_id,
            "punch_time": body.punch_time or now,
            "direction": body.direction,
            "source": body.source or default_source,
            "idempotency_key": body.idempotency_key,
            "recorded_by_user_id": actor_user_id,
            "reference": body.reference,
            "created_at": now,
        }
        try:
            row = await self._repo.insert(self._session, data=data)
        except IntegrityError as exc:
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
        return read

    async def list_punches(
        self,
        company_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[PunchRead]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows = await self._repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
        )
        return [punch_to_read(r) for r in rows]


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
        self._attendance_policy_repo = AttendancePolicyRepository()
        self._overtime_repo = OvertimePolicyRepository()
        self._punch_repo = PunchRepository()
        self._roster_repo = ShiftRosterRepository()
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
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> list[AttendanceDayRead]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows = await self._day_repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        results = []
        for row in rows:
            breaks = await self._break_repo.list_for_day(
                self._session, company_id=company_id, attendance_day_id=row.id
            )
            results.append(attendance_day_to_read(row, breaks))
        return results

    async def calculate(
        self,
        company_id: UUID,
        employee_id: UUID,
        target_date: date,
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
        for W8's `AttendanceLock`."""
        existing = await self._day_repo.get_by_employee_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=target_date,
        )
        if existing is not None and existing.is_locked:
            raise AttendanceDayLockedError()

        calc_input, resolved_refs = await self._build_calculation_input(
            company_id, employee_id, target_date
        )
        result = calc.evaluate_day(calc_input)
        now = datetime.now(UTC)
        values = self._result_to_values(calc_input, result, resolved_refs)

        row: AttendanceDay | None
        if existing is None:
            day_id = uuid4()
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
        else:
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
    ) -> AttendanceDayRead:
        row = await self._day_repo.get(
            self._session, company_id=company_id, attendance_day_id=attendance_day_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return await self.calculate(
            company_id,
            row.employee_id,
            row.attendance_date,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

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
            "paid_day_fraction": Decimal(result.paid_day_fraction),
            "lop_fraction": Decimal(result.lop_fraction),
            "ot_minutes_detected": result.ot_minutes_detected,
            "ot_minutes_approved": result.ot_minutes_approved,
            "ot_pending": result.ot_pending,
            "ot_classification": result.ot_classification,
            "comp_off_minutes_earned": result.comp_off_minutes_earned,
            "computation_snapshot": result.snapshot,
            "calculated_at": datetime.now(UTC),
        }

    async def _build_calculation_input(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> tuple[calc.AttendanceCalculationInput, dict[str, UUID | None]]:
        # Local, function-scoped imports — the established cross-module-seam convention
        # (module docstring; mirrors `PolicyResolutionService.resolve`,
        # `CalendarResolutionService._scope_candidates`, `EmployeeService._check_seat_limit`).
        from hrms.modules.employee.service import EmployeeAssignmentService, EmploymentService
        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService
        from hrms.modules.organisation.exceptions import ShiftVersionNotFoundForDateError
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

        shift_inputs: calc.ShiftInputs | None = None
        shift_version_timezone: str | None = None
        shift_version_id: UUID | None = None
        raw_start_time = raw_end_time = raw_window_start = raw_window_end = None
        shift_id = (
            roster_entry.shift_id
            if roster_entry is not None
            else (assignment.shift_id if assignment else None)
        )
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
                raw_end_time = (
                    _parse_time(shift_version.end_time) if shift_version.end_time else None
                )
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
                    core_end=(
                        _parse_time(shift_version.core_end) if shift_version.core_end else None
                    ),
                    required_minutes=shift_version.required_minutes,
                )

        tz_name = calc.resolve_timezone(
            shift_version_timezone=shift_version_timezone,
            branch_timezone=branch_timezone,
            company_timezone=company.timezone,
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

        calendar_result = await calendar_service.resolve_for_employee(
            company_id, employee_id, target_date
        )
        calendar_day_type = None
        holiday_name = None
        holiday_on_weekly_off = False
        work_calendar_id = calendar_result.work_calendar_id
        if not calendar_result.config_incomplete and calendar_result.day_type is not None:
            calendar_day_type = calendar_result.day_type.day_type
            holiday_name = calendar_result.day_type.holiday_name
            holiday_on_weekly_off = calendar_result.day_type.holiday_on_weekly_off

        attendance_resolution = await self._resolution.resolve(
            company_id, "ATTENDANCE_POLICY", employee_id=employee_id, target_date=target_date
        )
        policy_inputs: calc.PolicyInputs | None = None
        attendance_policy_version_id: UUID | None = None
        hour_bands: list[calc.BandData] = []
        late_bands: list[calc.BandData] = []
        early_bands: list[calc.BandData] = []
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

        overtime_resolution = await self._resolution.resolve(
            company_id, "OVERTIME_POLICY", employee_id=employee_id, target_date=target_date
        )
        ot_inputs: calc.OvertimePolicyInputs | None = None
        overtime_policy_version_id: UUID | None = None
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
                rate_rows = await self._overtime_repo.list_rate_rows(
                    self._session, company_id=company_id, policy_version_id=ot_version.id
                )
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
                        for r in rate_rows
                    ],
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

        calc_input = calc.AttendanceCalculationInput(
            employee_id=employee_id,
            attendance_date=target_date,
            timezone=tz_name,
            population_status=population_status,
            calendar_day_type=calendar_day_type,
            holiday_name=holiday_name,
            holiday_on_weekly_off=holiday_on_weekly_off,
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
        )
        resolved_refs: dict[str, UUID | None] = {
            "shift_id": shift_id,
            "shift_version_id": shift_version_id,
            "work_calendar_id": work_calendar_id,
            "attendance_policy_version_id": attendance_policy_version_id,
            "overtime_policy_version_id": overtime_policy_version_id,
            "regularization_policy_version_id": regularization_policy_version_id,
        }
        return calc_input, resolved_refs


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

        if body.attendance_date > date.today():
            raise ValidationError("attendance_date cannot be in the future")

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
            backdated_days = (date.today() - body.attendance_date).days
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
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        status: str | None = None,
        request_type: str | None = None,
    ) -> list[RegularizationRequestRead]:
        visible_ids = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows = await self._repo.list_filtered(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            request_type=request_type,
        )
        return [await self._read(r, company_id=company_id) for r in rows]

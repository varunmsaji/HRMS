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
from hrms.core.errors.base import NotFoundError
from hrms.core.rbac.types import DataScope
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
    StalePolicyResourceError,
)
from hrms.modules.attendance.models import AttendanceDay
from hrms.modules.attendance.repository import (
    AttendanceBreakRepository,
    AttendanceDayRepository,
    AttendancePolicyRepository,
    OvertimePolicyRepository,
    PunchRepository,
    RegularizationPolicyRepository,
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

        shift_inputs: calc.ShiftInputs | None = None
        shift_version_timezone: str | None = None
        shift_version_id: UUID | None = None
        raw_start_time = raw_end_time = raw_window_start = raw_window_end = None
        shift_id = assignment.shift_id if assignment else None
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

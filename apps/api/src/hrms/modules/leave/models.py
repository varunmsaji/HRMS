"""ORM models owned by the Leave module.

L1 (docs/architecture/LEAVE_DECISION_LOG.md LD-01/LD-02/LD-04) — identity + immutable-published-
version shape, mirroring `AttendancePolicy`/`AttendancePolicyVersion` (attendance/models.py) and
`RegularizationPolicyVersion`'s "defines the contract, a later slice builds the engine that reads
it" posture exactly: `LeavePolicyVersion` carries typed accrual/approval/request-limit fields, but
no accrual job or application workflow exists yet (LD-09: those are L3/L4). `PolicyAssignment`
(organisation/models.py) is reused as-is for scope/precedence — this module widens its
`policy_kind` allow-list (LD-04) rather than duplicating that table.

L2 (LD-02/LD-03) — `LeaveLedgerEntry`: the append-only balance ledger (ADR-0004/DEC-004). Balance
for an (employee, leave_type) is always `SUM(amount)` over this table — no code path anywhere may
write a mutable balance column.

`leave_application` (LD-05) is explicitly NOT part of this slice — L4."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# Leave Type — identity only, no versioning (mirrors Shift/AttendancePolicy identity rows)
# ---------------------------------------------------------------------------


class LeaveType(Base, TimestampMixin):
    """Identity row only — code/name/paid-default/balance-requirement. No versioned config of
    its own; accrual/approval rules for a leave type live on `LeavePolicyVersion`, resolved via
    `PolicyAssignment` like every other policy in this system (LD-04)."""

    __tablename__ = "leave_type"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    is_paid_default: Mapped[bool] = mapped_column(Boolean, default=True)
    # LOP-style types are never balance-backed — no ledger entries are ever expected for them,
    # and application submission skips the balance-sufficiency check entirely (LD-02).
    requires_balance: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


# ---------------------------------------------------------------------------
# Leave Policy — identity + version, same shape as AttendancePolicy/Version
# ---------------------------------------------------------------------------


class LeavePolicy(Base, TimestampMixin):
    """Identity row — name/code/active/leave_type_id only, never carries evaluation fields
    directly (mirrors `AttendancePolicy`). The actual rule configuration lives on
    `LeavePolicyVersion`.

    `leave_type_id` (LD-10) binds every version of this policy to exactly one `LeaveType` — not
    unique, since multiple policies may target the same leave type for different
    `PolicyAssignment` scopes (e.g. "Casual Leave — HQ" vs "Casual Leave — Remote")."""

    __tablename__ = "leave_policy"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_type.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class LeavePolicyVersion(Base, TimestampMixin):
    """Immutable once PUBLISHED (mirrors `AttendancePolicyVersion`/`RegularizationPolicyVersion`).

    This slice (L1) defines the contract only — no accrual job (L3), application workflow (L4),
    or comp-off redemption (L5) reads these fields yet. Field shapes are locked (LD-02); several
    of the *values* HR would set here are genuinely open business questions (LD-06: accrual
    rate/frequency, carry-forward cap, encashment trigger, negative-balance policy, sandwich-leave
    rule) — nothing in this model guesses a default for those beyond the same conservative,
    change-nothing-by-default posture every other policy in this codebase uses for an unanswered
    setting (e.g. `allow_negative_balance`/`sandwich_rule_enabled` default `False`, matching
    `AttendancePolicyVersion.early_departure_requires_approval`'s "off until explicitly turned on"
    convention)."""

    __tablename__ = "leave_policy_version"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_policy.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Request/approval — same shape as RegularizationPolicyVersion (LD-05: mirrors, doesn't
    # share code).
    allow_employee_request: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_manager_request_on_behalf: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_hr_request_on_behalf: Mapped[bool] = mapped_column(Boolean, default=True)
    max_backdated_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_requests_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_required: Mapped[bool] = mapped_column(Boolean, default=True)
    attachment_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_chain: Mapped[str] = mapped_column(String(20), default="MANAGER")
    half_day_allowed: Mapped[bool] = mapped_column(Boolean, default=True)

    # Accrual (LD-06 — mechanism only in this slice; values are HR-set, several remain OPEN
    # business questions not guessed here).
    accrual_frequency: Mapped[str] = mapped_column(String(20), default="NONE")
    accrual_rate_per_cycle: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_carry_forward_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    encashment_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_negative_balance: Mapped[bool] = mapped_column(Boolean, default=False)
    # LD-06 decision 5: sandwich-leave rule applies for this client — new drafts default to it
    # being on, though HR can still turn it off per policy.
    sandwich_rule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    publish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Leave Ledger — L2, append-only (ADR-0004/DEC-004)
# ---------------------------------------------------------------------------


class LeaveLedgerEntry(Base):
    """Append-only balance ledger (ADR-0004/DEC-004 — "every accrual, deduction, adjustment,
    encashment and carry-forward is its own immutable row"; displayed balance is always a
    derived `SUM(amount)`, never a column that gets incremented/decremented in place). No
    update, no delete, no soft-delete flag, no `version` column — a correction is a new,
    separate offsetting entry, never an edit of a past row, the same posture ADR-0005 already
    established for finalised payroll runs.

    Deliberately does **not** use `TimestampMixin` — an `updated_at` column would misleadingly
    imply a row can change after being written. Mirrors `AttendanceRegularizationAction`'s
    append-only-timeline shape (single `created_at`, no `updated_at`, no `version`), not the
    identity/version tables above.

    L2 only writes `ADJUSTMENT` entries (manual HR corrections, via
    `LeaveLedgerService.create_adjustment`). `ACCRUAL` (L3), `APPLICATION`/`ENCASHMENT`/
    `CARRY_FORWARD` (L4), and `COMP_OFF_CREDIT` (L5) are locked into the `entry_type` CHECK now
    (LD-02's field-shape decision) but nothing writes them yet."""

    __tablename__ = "leave_ledger"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_type.id"), index=True
    )

    entry_type: Mapped[str] = mapped_column(String(20))
    # Signed — positive credits the balance (ACCRUAL, CARRY_FORWARD, COMP_OFF_CREDIT, or a
    # positive ADJUSTMENT), negative debits it (APPLICATION, ENCASHMENT, or a negative
    # ADJUSTMENT). Never zero (CHECK, migration) — a zero entry has no ledger meaning.
    amount: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    effective_date: Mapped[date] = mapped_column(Date)

    # Opaque external reference (e.g. a future leave_application_id, or an OvertimeRecord.id for
    # a COMP_OFF_CREDIT entry) — no FK, mirrors LeaveDayProjection.leave_application_id's own
    # "not joinable yet" posture (L4/L5 not built).
    reference_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

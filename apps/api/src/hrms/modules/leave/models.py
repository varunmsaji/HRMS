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

L4 (LD-02/LD-05/LD-12/LD-13) — `LeaveApplication`/`LeaveApplicationDay`/`LeaveApplicationAction`:
the submission + approval workflow. `LeaveApplication` mirrors `AttendanceRegularizationRequest`'s
state machine shape (status/approval_chain/approval_stage/resolved_approver_manager_id), mirrored
not shared code (LD-05). `LeaveApplicationDay` has no Regularization precedent — one row per
calendar date the application covers, since a leave spans a range with per-day fractions where a
regularization request is always single-date."""

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
    # LD-14 — marks this the company's comp-off balance type (OvertimeRecord has no
    # leave_type_id of its own to link against). At most one active row per company
    # (DB partial unique index, migration 20260909090000).
    is_comp_off: Mapped[bool] = mapped_column(Boolean, default=False)
    # LD-22 — classifies this company's free-form leave type against the small fixed statutory
    # taxonomy `statutory_leave_minimum` rows are keyed on, so "Privilege Leave" and "Earned
    # Leave" (different companies, same legal category) both compare against the same floor.
    # NULL means this leave type has no statutory category (LOP, comp-off, bereavement, ...) and
    # is never checked against a minimum.
    statutory_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    # LD-23 — widened from VARCHAR(20) to fit MANAGER_THEN_HOD_THEN_HR (24 chars).
    approval_chain: Mapped[str] = mapped_column(String(30), default="MANAGER")
    half_day_allowed: Mapped[bool] = mapped_column(Boolean, default=True)

    # Accrual (LD-06 — mechanism only in this slice; values are HR-set, several remain OPEN
    # business questions not guessed here).
    accrual_frequency: Mapped[str] = mapped_column(String(20), default="NONE")
    accrual_rate_per_cycle: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_carry_forward_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    encashment_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_negative_balance: Mapped[bool] = mapped_column(Boolean, default=False)
    # PAY-011 (decision 8) — how far below zero the balance may go when `allow_negative_balance`
    # is on (`3.00` = down to −3). Required to publish with the switch on; NULL reads as 0.
    negative_balance_floor: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Decision 11 — balance handling at leave-year start: CARRY_FORWARD (up to
    # `max_carry_forward_days`, excess lapses), LAPSE (whole balance lapses), or ENCASH_EXCESS
    # (up to the cap carried, excess written as an ENCASHMENT for payroll).
    year_end_action: Mapped[str] = mapped_column(String(20), default="CARRY_FORWARD")
    # LD-06 decision 5: sandwich-leave rule applies for this client — new drafts default to it
    # being on, though HR can still turn it off per policy.
    sandwich_rule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # LD-15 — whether a SUBMITTED (not yet resolved) application blocks further balance for this
    # leave type. Reserved amount itself is never stored here or in the ledger — always derived
    # live from open `leave_application` rows (LD-15's "no new ledger entry type" decision).
    reserve_balance_on_submission: Mapped[bool] = mapped_column(Boolean, default=False)
    # LD-17 — client spec §F. Purely HR-documented entitlement split (e.g. "6 weeks pre + 20
    # weeks post"); never enforced against an application's actual start_date/end_date, which
    # count days the same way every other leave type does.
    pre_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # LD-18 — client spec §9. Reads the existing `Employee.status = 'PROBATION'` fact (FR-EMP-014
    # lifecycle enum) — no new schema in the Employee module. Both default True: neither
    # submission nor accrual look at employee status today, so this preserves that exactly until
    # HR explicitly turns one off.
    allowed_during_probation: Mapped[bool] = mapped_column(Boolean, default=True)
    accrue_during_probation: Mapped[bool] = mapped_column(Boolean, default=True)
    # LD-19 — client spec §12. `max_encashment_days`/`min_balance_after_encashment` are enforced
    # by LeaveLedgerService.create_encashment; both nullable (no limit assumed when unset).
    # `encashment_frequency`/`encashment_calculation_basis` are informational only — frequency
    # enforcement needs a leave-year concept not yet decided, and calculation basis is a Payroll
    # concern (Payroll doesn't exist as a module yet).
    max_encashment_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    min_balance_after_encashment: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    encashment_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    encashment_calculation_basis: Mapped[str | None] = mapped_column(String(50), nullable=True)

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

    # Opaque external reference (e.g. a leave_application_id for an APPLICATION/ADJUSTMENT entry
    # written by L4's approval/cancel flow, or a future OvertimeRecord.id for a COMP_OFF_CREDIT
    # entry) — no FK, polymorphic across entry_type, mirrors LeaveDayProjection's own
    # leave_application_id "not joinable" posture.
    reference_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Leave Application — L4, mirrors AttendanceRegularizationRequest's state machine (LD-05)
# ---------------------------------------------------------------------------


class LeaveApplication(Base, TimestampMixin):
    """Employee's request for leave over a date range. `leave_policy_version_id` is snapshotted
    at submit time (mirrors `AttendanceRegularizationRequest.regularization_policy_version_id`)
    so a later policy edit cannot retroactively change how an in-flight application is reviewed.
    `approval_stage` tracks whose turn it is next (`MANAGER`|`HOD`|`HR`|`NULL` once terminal or
    `AUTO`) — identical state machine to Regularization's, mirrored not shared (LD-05).
    `resolved_department_head_id` (LD-23) is the third stage's snapshotted reviewer, resolved
    from the employee's assignment `department_id` at submit time exactly like
    `resolved_approver_manager_id` — only ever populated for `MANAGER_THEN_HOD_THEN_HR`."""

    __tablename__ = "leave_application"

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
    leave_policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_policy_version.id")
    )

    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    total_days: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    # PAY-010 (decision 9) — days approved as loss of pay because the balance could not cover
    # them ("approve with excess as LOP"). Only `total_days - lop_days` is debited.
    lop_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # LD-17 — client spec §F. Generic, optional, harmless for every non-maternity leave type
    # (same posture as `attachment_reference`/half-day) — never read by day-counting or balance
    # logic, purely informational for HR/coverage planning.
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")
    # LD-23 — widened from VARCHAR(20) to fit MANAGER_THEN_HOD_THEN_HR (24 chars).
    approval_chain: Mapped[str] = mapped_column(String(30))
    approval_stage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    resolved_approver_manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    resolved_department_head_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )

    submitted_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Decision 10 — mandatory when HR cancels leave that has already started.
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    version: Mapped[int] = mapped_column(Integer, default=1)


class LeaveApplicationDay(Base, TimestampMixin):
    """One row per calendar date a `LeaveApplication` covers — new shape, no Regularization
    precedent (a regularization request is always single-date). `is_sandwich_generated` marks a
    weekend/holiday date included only because LD-06's sandwich rule bracketed it between two
    leave-consuming days, not because the employee applied for it directly.

    `leave_day_projection_id` is an opaque reference (no FK — `leave_day_projection` lives in
    `attendance`, cross-module, mirrors `leave_ledger.reference_id`'s "not joinable" posture) to
    the row `LeaveProjectionService.sync()` returns on approval, so `cancel()` (LD-13) can
    address it directly instead of re-deriving it from the natural key."""

    __tablename__ = "leave_application_day"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    leave_application_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_application.id"), index=True
    )
    calendar_date: Mapped[date] = mapped_column(Date)
    fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    half: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_sandwich_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    # PAY-010 — this day is approved as unpaid (LOP) leave, not debited from the balance.
    is_lop: Mapped[bool] = mapped_column(Boolean, default=False)
    leave_day_projection_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )


class LeaveApplicationAction(Base):
    """Append-only per-application timeline — mirrors `AttendanceRegularizationAction` exactly
    (single `created_at`, no `updated_at`/`version`): a single `reviewed_by_user_id`/
    `reviewed_at` pair on `LeaveApplication` cannot hold a `MANAGER_THEN_HR` chain's full
    history."""

    __tablename__ = "leave_application_action"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    leave_application_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_application.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    actor_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Leave Combination Rule — client spec §7 (LD-16), configurable pairwise exclusivity
# ---------------------------------------------------------------------------


class LeaveCombinationRule(Base, TimestampMixin):
    """An unordered pair of leave types plus whether they may be applied for on overlapping
    dates (client spec §7 — "CL + SL = Not Allowed", "AL + CL = Allowed"). Absence of a row for
    a pair means allowed — matches today's behavior, where nothing blocks any combination
    (LD-16). No versioning/publish lifecycle (unlike `LeavePolicyVersion`) — this is a flat
    identity row; changing a rule is delete-and-recreate, since there's no meaningful
    "in-flight draft" state for a single boolean.

    `leave_type_id_a`/`_b` are stored in whatever order the creator gave them — the DB partial
    unique index (`leave_combination_rule_pair_idx`, `LEAST`/`GREATEST` over both columns) is
    what actually enforces "at most one rule per unordered pair", not column order."""

    __tablename__ = "leave_combination_rule"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    leave_type_id_a: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_type.id")
    )
    leave_type_id_b: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_type.id")
    )
    allowed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )


# ---------------------------------------------------------------------------
# Leave Year Setting — client spec §10 (LD-20), singleton per company
# ---------------------------------------------------------------------------


class LeaveYearSetting(Base, TimestampMixin):
    """Singleton per company (unique index on `company_id`) — client answer (2026-09-06):
    default `CALENDAR`. `start_month`/`start_day` are only meaningful for `CUSTOM`; `CALENDAR`
    (Jan 1) and `FINANCIAL` (client answer: India, so Apr 1) have their start dates hardcoded in
    application code (`leave/year.py`), not stored — they aren't configurable values, just named
    choices. `ANNIVERSARY` has no company-wide start date at all — each employee's own
    `Employment.joining_date` month/day is used instead (LD-20)."""

    __tablename__ = "leave_year_setting"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    leave_year_type: Mapped[str] = mapped_column(String(20), default="CALENDAR")
    start_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


# ---------------------------------------------------------------------------
# Statutory Leave Minimum — client spec §16 (LD-22), legal compliance floor
# ---------------------------------------------------------------------------


class StatutoryLeaveMinimum(Base, TimestampMixin):
    """HR/compliance-entered floor for a statutory leave category (LD-22) — no legal figures are
    hardcoded anywhere in this codebase, the same "engine reads whatever is configured" posture
    LD-06 established for accrual. `state_code`/`establishment_type` are reference dimensions
    (India's Shops & Establishments minimums vary by state and, in some states, by establishment
    type) — `NULL` on either means "not narrowed by this dimension". Flat identity row, no
    versioning: editing a minimum is delete-and-recreate, same posture as `LeaveCombinationRule`.

    The publish-time check (`LeavePolicyService.publish_version`) does not resolve a specific
    branch/state at publish time — a policy's eventual `PolicyAssignment` scope isn't known yet —
    so it compares against the *strictest* (`MAX`) `min_days_per_year` configured for the leave
    type's `statutory_category`, regardless of `state_code`/`establishment_type`. Fail-safe, not
    scope-precise (LD-22)."""

    __tablename__ = "statutory_leave_minimum"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    establishment_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    leave_category: Mapped[str] = mapped_column(String(20))
    min_days_per_year: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

"""Business logic for the Payroll module — the public interface for other modules.

Phase 5.2 (same plan): payroll settings and the monthly pay run (`PayRunService`), computed by
the pure `engine.compute_employee` over inputs snapshotted at lock-inputs.

Phase 5.1 (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`): salary components, salary
structures (draft → publish, effective-dated) and employee salary assignment, plus the CTC
breakup built on the pure `breakup.compute_breakup`.

Defaults (decisions D1/D2) are seeded per company on first use rather than by a migration, so a
new company and an existing one get exactly the same rows from one definition:
the five system components, and — only while the company has no structure at all — two
published structures, `STANDARD` (HRA 40 % of Basic) and `STANDARD_METRO` (HRA 50 %)."""

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.db.locks import (
    lock_attendance_period_close,
    lock_pay_adjustment,
    lock_payroll_finalise,
)
from hrms.core.errors.base import NotFoundError
from hrms.core.observability.operations import logged_operation
from hrms.core.rbac.types import DataScope
from hrms.modules.notification.producer import employee_user_ids, notify
from hrms.modules.notification.types import MY_PAYSLIPS_PATH, PAYSLIP_AVAILABLE
from hrms.modules.payroll.breakup import (
    ARREARS_PREFIX,
    Breakup,
    BreakupError,
    StructureLine,
    compute_breakup,
    validate_structure,
)
from hrms.modules.payroll.engine import (
    ERROR,
    WARNING,
    Issue,
    compute_employee,
    employee_input_from_snapshot,
)
from hrms.modules.payroll.exceptions import (
    EmployeeSalaryInvalidError,
    PayAdjustmentInvalidError,
    PayAdjustmentNotFoundError,
    PayRunAlreadyExistsError,
    PayRunArrearsStaleError,
    PayRunAttendanceChangedError,
    PayRunBlockedError,
    PayRunEmployeeNotFoundError,
    PayRunInputsChangedError,
    PayRunInputsUnavailableError,
    PayRunInvalidTransitionError,
    PayRunLegalEntityInvalidError,
    PayRunMakerCheckerError,
    PayRunNotFoundError,
    SalaryBreakupUnavailableError,
    SalaryComponentCodeAlreadyExistsError,
    SalaryComponentNotFoundError,
    SalaryComponentSystemFieldError,
    SalaryStructureCodeAlreadyExistsError,
    SalaryStructureDraftExistsError,
    SalaryStructureEffectiveFromError,
    SalaryStructureInvalidError,
    SalaryStructureNotFoundError,
    SalaryStructureVersionNotDraftError,
    SalaryStructureVersionNotFoundError,
    StalePayrollResourceError,
    StatutoryRateEditorUnverifiableError,
    StatutoryRateInvalidError,
    StatutoryRateNotFoundError,
    StatutoryRateSelfVerificationError,
)
from hrms.modules.payroll.income_tax import financial_year_start
from hrms.modules.payroll.models import (
    PayRun,
    PayRunEmployee,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureLine,
    SalaryStructureVersion,
    StatutoryRate,
)
from hrms.modules.payroll.repository import (
    EmployeeSalaryRepository,
    PayAdjustmentRepository,
    PayrollSettingRepository,
    PayRunArrearRepository,
    PayRunRepository,
    SalaryComponentRepository,
    SalaryStructureRepository,
    StatutoryAuditReader,
    StatutoryRateRepository,
)
from hrms.modules.payroll.schemas import (
    EmployeeSalaryBreakupRead,
    EmployeeSalaryBulkAssign,
    EmployeeSalaryBulkResult,
    EmployeeSalaryBulkSkip,
    EmployeeSalaryCreate,
    EmployeeSalaryRead,
    EmployeeSalarySetupPreviewInput,
    EmployeeSalarySetupPreviewRead,
    EmployeeSalarySetupRead,
    EmployeeSalarySetupSave,
    PayAdjustmentCreate,
    PayAdjustmentRead,
    PayrollSettingRead,
    PayrollSettingUpdate,
    PayRunCreate,
    PayRunEmployeeDetailRead,
    PayRunEmployeeRead,
    PayRunRead,
    PayRunRollback,
    PayRunUpdate,
    PayRunVarianceAcknowledge,
    PayslipLeaveBalanceRead,
    PayslipLineRead,
    PayslipRead,
    PayslipSummaryRead,
    SalaryBreakupLineRead,
    SalaryBreakupPreviewInput,
    SalaryBreakupRead,
    SalaryComponentCreate,
    SalaryComponentRead,
    SalaryComponentUpdate,
    SalaryStructureCreate,
    SalaryStructureLineInput,
    SalaryStructureLineRead,
    SalaryStructureRead,
    SalaryStructureUpdate,
    SalaryStructureVersionCreate,
    SalaryStructureVersionPublish,
    SalaryStructureVersionRead,
    StatutoryRateCreate,
    StatutoryRateRead,
    StatutoryRateUpdate,
    employee_salary_to_read,
    pay_adjustment_to_read,
    pay_run_employee_to_read,
    pay_run_line_to_read,
    pay_run_to_read,
    payroll_setting_to_read,
    salary_component_to_read,
    salary_structure_line_to_read,
    salary_structure_to_read,
    salary_structure_version_to_read,
    statutory_rate_to_read,
    validate_statutory_parameters,
)
from hrms.modules.payroll.words import rupees_in_words
from hrms.shared.business_time import business_today
from hrms.shared.pagination import PageParams

if TYPE_CHECKING:
    from hrms.modules.attendance.service import PayrollPeriodInputs

# ---------------------------------------------------------------------------
# Defaults (D1/D2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SystemComponent:
    code: str
    name: str
    component_type: str
    is_taxable: bool
    is_pf_wage: bool
    is_esi_wage: bool
    display_order: int


SYSTEM_COMPONENTS: tuple[_SystemComponent, ...] = (
    _SystemComponent("BASIC", "Basic", "EARNING", True, True, True, 10),
    _SystemComponent("HRA", "House Rent Allowance", "EARNING", True, False, True, 20),
    _SystemComponent("SPECIAL_ALLOWANCE", "Special Allowance", "EARNING", True, False, True, 30),
    _SystemComponent(
        "EMPLOYER_PF", "Employer PF contribution", "EMPLOYER_CONTRIBUTION", False, False, False, 90
    ),
    _SystemComponent(
        "EMPLOYER_ESI",
        "Employer ESI contribution",
        "EMPLOYER_CONTRIBUTION",
        False,
        False,
        False,
        91,
    ),
)

#: Default structures seeded while a company has none. Employer PF is 12 % of Basic capped at
#: ₹1,800 a month (PF wage ceiling ₹15,000) — seeded as ordinary, editable structure data; the
#: statutory phase (5.3) replaces it with the effective-dated statutory rate master. Employer ESI
#: is left out until then (its eligibility depends on gross against a ceiling).
DEFAULT_STRUCTURES: tuple[tuple[str, str, str, Decimal], ...] = (
    ("STANDARD", "Standard", "Basic 50% of gross, HRA 40% of Basic", Decimal("40")),
    ("STANDARD_METRO", "Standard (metro)", "Basic 50% of gross, HRA 50% of Basic", Decimal("50")),
)
DEFAULT_STRUCTURE_EFFECTIVE_FROM = date(2000, 1, 1)
_EMPLOYER_PF_CAP_MINOR = 180_000


def _default_lines(hra_percentage: Decimal) -> list[dict[str, Any]]:
    return [
        {"code": "BASIC", "calculation_type": "PERCENTAGE_OF_GROSS",
         "percentage": Decimal("50"), "display_order": 10},
        {"code": "HRA", "calculation_type": "PERCENTAGE_OF_COMPONENT",
         "percentage": hra_percentage, "base": "BASIC", "display_order": 20},
        {"code": "SPECIAL_ALLOWANCE", "calculation_type": "BALANCING", "display_order": 30},
        {"code": "EMPLOYER_PF", "calculation_type": "PERCENTAGE_OF_COMPONENT",
         "percentage": Decimal("12"), "base": "BASIC", "max": _EMPLOYER_PF_CAP_MINOR,
         "applies_when": "PF_APPLICABLE", "display_order": 90},
    ]  # fmt: skip


def _to_structure_lines(
    rows: list[SalaryStructureLine], components: dict[UUID, SalaryComponent]
) -> list[StructureLine]:
    return [
        StructureLine(
            component_code=components[row.salary_component_id].code,
            component_name=components[row.salary_component_id].name,
            component_type=components[row.salary_component_id].component_type,
            calculation_type=row.calculation_type,
            percentage=row.percentage,
            amount_monthly_minor=row.amount_monthly_minor,
            base_component_code=(
                components[row.base_salary_component_id].code
                if row.base_salary_component_id is not None
                and row.base_salary_component_id in components
                else None
            ),
            max_monthly_minor=row.max_monthly_minor,
            applies_when=row.applies_when,
            display_order=row.display_order,
        )
        for row in rows
    ]


def _breakup_to_read(breakup: Breakup) -> SalaryBreakupRead:
    return SalaryBreakupRead(
        annual_ctc_minor=breakup.annual_ctc_minor,
        monthly_ctc_minor=breakup.monthly_ctc_minor,
        gross_monthly_minor=breakup.gross_monthly_minor,
        employer_contributions_monthly_minor=breakup.employer_contributions_monthly_minor,
        lines=[
            SalaryBreakupLineRead(
                component_code=line.component_code,
                component_name=line.component_name,
                component_type=line.component_type,
                monthly_minor=line.monthly_minor,
                annual_minor=line.annual_minor,
                basis=line.basis,
            )
            for line in breakup.lines
        ],
    )


# ---------------------------------------------------------------------------
# Salary components
# ---------------------------------------------------------------------------


def _line_key(
    component_id: UUID,
    calculation_type: str,
    percentage: Decimal | str | None,
    amount_monthly_minor: int | None,
    base_component_id: UUID | None,
    max_monthly_minor: int | None,
    applies_when: str,
) -> tuple[Any, ...]:
    """What a line pays, without its display order — two line sets with the same keys pay the
    same. Fields the calculation type does not use are ignored."""
    uses_percentage = calculation_type.startswith("PERCENTAGE")
    return (
        str(component_id),
        calculation_type,
        Decimal(str(percentage)).normalize()
        if uses_percentage and percentage is not None
        else None,
        amount_monthly_minor if calculation_type == "FIXED" else None,
        str(base_component_id) if calculation_type == "PERCENTAGE_OF_COMPONENT" else None,
        max_monthly_minor,
        applies_when,
    )


def _input_keys(lines: list[SalaryStructureLineInput]) -> list[tuple[Any, ...]]:
    return sorted(
        _line_key(
            line.salary_component_id,
            line.calculation_type,
            line.percentage,
            line.amount_monthly_minor,
            line.base_salary_component_id,
            line.max_monthly_minor,
            line.applies_when,
        )
        for line in lines
    )


def _read_keys(lines: list[SalaryStructureLineRead]) -> list[tuple[Any, ...]]:
    return sorted(
        _line_key(
            line.salary_component_id,
            line.calculation_type,
            line.percentage,
            line.amount_monthly_minor,
            line.base_salary_component_id,
            line.max_monthly_minor,
            line.applies_when,
        )
        for line in lines
    )


def _published_as_of(
    structure: SalaryStructureRead, as_of: date
) -> SalaryStructureVersionRead | None:
    return next(
        (
            v
            for v in structure.versions
            if v.status == "PUBLISHED"
            and v.effective_from is not None
            and v.effective_from <= as_of
            and (v.effective_to is None or v.effective_to >= as_of)
        ),
        None,
    )


class SalaryComponentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SalaryComponentRepository()
        self._audit = AuditService()

    async def ensure_system_components(self, company_id: UUID) -> None:
        now = datetime.now(UTC)
        for component in SYSTEM_COMPONENTS:
            await self._repo.insert_if_missing(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "code": component.code,
                    "name": component.name,
                    "component_type": component.component_type,
                    "is_system": True,
                    "is_taxable": component.is_taxable,
                    "is_pf_wage": component.is_pf_wage,
                    "is_esi_wage": component.is_esi_wage,
                    "is_prorated": True,
                    "show_on_payslip": True,
                    "display_order": component.display_order,
                    "is_active": True,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    async def list_components(self, company_id: UUID) -> list[SalaryComponentRead]:
        await self.ensure_system_components(company_id)
        rows = await self._repo.list_for_company(self._session, company_id=company_id)
        return [salary_component_to_read(r) for r in rows]

    async def create(
        self,
        company_id: UUID,
        body: SalaryComponentCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryComponentRead:
        await self.ensure_system_components(company_id)
        now = datetime.now(UTC)
        component_id = uuid4()
        try:
            async with self._session.begin_nested():
                row = await self._repo.insert(
                    self._session,
                    data={
                        "id": component_id,
                        "company_id": company_id,
                        **body.model_dump(),
                        "is_system": False,
                        "is_active": True,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError as exc:
            raise SalaryComponentCodeAlreadyExistsError() from exc
        read = salary_component_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_SALARY_COMPONENT_CREATED",
            entity_type="salary_component",
            entity_id=component_id,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def update(
        self,
        company_id: UUID,
        component_id: UUID,
        patch: SalaryComponentUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryComponentRead:
        row = await self._repo.get(self._session, company_id=company_id, component_id=component_id)
        if row is None:
            raise SalaryComponentNotFoundError()
        values = {field: getattr(patch, field) for field in patch.model_fields_set}
        if (
            row.is_system
            and "component_type" in values
            and (values["component_type"] != row.component_type)
        ):
            raise SalaryComponentSystemFieldError()
        before = salary_component_to_read(row)
        updated = row
        if values:
            result = await self._repo.update(
                self._session,
                company_id=company_id,
                component_id=component_id,
                values=values,
                expected_version=expected_version,
                now=datetime.now(UTC),
            )
            if result is None:
                latest = await self._repo.get(
                    self._session, company_id=company_id, component_id=component_id
                )
                if latest is None:
                    raise SalaryComponentNotFoundError()
                raise StalePayrollResourceError(
                    "This salary component has been modified by another request",
                    current=salary_component_to_read(latest).model_dump(mode="json"),
                )
            updated = result
        after = salary_component_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_SALARY_COMPONENT_UPDATED",
            entity_type="salary_component",
            entity_id=component_id,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after


# ---------------------------------------------------------------------------
# Salary structures
# ---------------------------------------------------------------------------


class SalaryStructureService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SalaryStructureRepository()
        self._component_repo = SalaryComponentRepository()
        self._components = SalaryComponentService(session)
        self._audit = AuditService()

    # -- defaults -------------------------------------------------------------------

    async def ensure_defaults(self, company_id: UUID) -> None:
        await self._components.ensure_system_components(company_id)
        if await self._repo.list_for_company(self._session, company_id=company_id):
            return
        components = {
            c.code: c
            for c in await self._component_repo.list_for_company(
                self._session, company_id=company_id
            )
        }
        now = datetime.now(UTC)
        try:
            async with self._session.begin_nested():
                for code, name, description, hra in DEFAULT_STRUCTURES:
                    structure = await self._repo.insert(
                        self._session,
                        data={
                            "id": uuid4(),
                            "company_id": company_id,
                            "code": code,
                            "name": name,
                            "description": description,
                            "is_active": True,
                            "version": 1,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                    version = await self._repo.insert_version(
                        self._session,
                        data={
                            "id": uuid4(),
                            "company_id": company_id,
                            "salary_structure_id": structure.id,
                            "version_number": 1,
                            "status": "PUBLISHED",
                            "effective_from": DEFAULT_STRUCTURE_EFFECTIVE_FROM,
                            "published_at": now,
                            "version": 1,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                    await self._repo.replace_lines(
                        self._session,
                        company_id=company_id,
                        version_id=version.id,
                        rows=[
                            {
                                "id": uuid4(),
                                "company_id": company_id,
                                "salary_structure_version_id": version.id,
                                "salary_component_id": components[line["code"]].id,
                                "calculation_type": line["calculation_type"],
                                "percentage": line.get("percentage"),
                                "amount_monthly_minor": None,
                                "base_salary_component_id": (
                                    components[line["base"]].id if "base" in line else None
                                ),
                                "max_monthly_minor": line.get("max"),
                                "applies_when": line.get("applies_when", "ALWAYS"),
                                "display_order": line["display_order"],
                                "created_at": now,
                                "updated_at": now,
                            }
                            for line in _default_lines(hra)
                        ],
                    )
        except IntegrityError:
            # A concurrent request seeded them first — theirs stand.
            return

    # -- reads -------------------------------------------------------------------------

    async def _read_many(
        self, company_id: UUID, structures: list[SalaryStructure]
    ) -> list[SalaryStructureRead]:
        versions = await self._repo.list_versions(
            self._session, company_id=company_id, structure_ids=[s.id for s in structures]
        )
        lines = await self._repo.list_lines(
            self._session, company_id=company_id, version_ids=[v.id for v in versions]
        )
        component_ids = {line.salary_component_id for line in lines}
        components = await self._component_repo.get_many(
            self._session, company_id=company_id, component_ids=component_ids
        )
        lines_by_version: dict[UUID, list[SalaryStructureLine]] = {}
        for line in lines:
            lines_by_version.setdefault(line.salary_structure_version_id, []).append(line)
        versions_by_structure: dict[UUID, list[SalaryStructureVersionRead]] = {}
        for version in versions:
            versions_by_structure.setdefault(version.salary_structure_id, []).append(
                salary_structure_version_to_read(
                    version,
                    [
                        salary_structure_line_to_read(line, components[line.salary_component_id])
                        for line in lines_by_version.get(version.id, [])
                    ],
                )
            )
        return [
            salary_structure_to_read(s, versions_by_structure.get(s.id, [])) for s in structures
        ]

    async def list_structures(self, company_id: UUID) -> list[SalaryStructureRead]:
        await self.ensure_defaults(company_id)
        return await self._read_many(
            company_id, await self._repo.list_for_company(self._session, company_id=company_id)
        )

    async def _get_row(self, company_id: UUID, structure_id: UUID) -> SalaryStructure:
        row = await self._repo.get(self._session, company_id=company_id, structure_id=structure_id)
        if row is None:
            raise SalaryStructureNotFoundError()
        return row

    async def get(self, company_id: UUID, structure_id: UUID) -> SalaryStructureRead:
        row = await self._get_row(company_id, structure_id)
        return (await self._read_many(company_id, [row]))[0]

    # -- line helpers ------------------------------------------------------------------

    async def _line_rows(
        self, company_id: UUID, version_id: UUID, lines: list[SalaryStructureLineInput]
    ) -> list[dict[str, Any]]:
        """Resolves and validates line inputs — components must exist, be active and in this
        company; the set must form a valid structure (`breakup.validate_structure`)."""
        component_ids = {line.salary_component_id for line in lines} | {
            line.base_salary_component_id
            for line in lines
            if line.base_salary_component_id is not None
        }
        components = await self._component_repo.get_many(
            self._session, company_id=company_id, component_ids=component_ids
        )
        missing = component_ids - set(components)
        if missing:
            raise SalaryStructureInvalidError("A line references an unknown salary component")
        inactive = [
            components[line.salary_component_id].code
            for line in lines
            if not components[line.salary_component_id].is_active
        ]
        if inactive:
            raise SalaryStructureInvalidError(f"Inactive component in structure: {inactive[0]}")
        now = datetime.now(UTC)
        rows = [
            {
                "id": uuid4(),
                "company_id": company_id,
                "salary_structure_version_id": version_id,
                "salary_component_id": line.salary_component_id,
                "calculation_type": line.calculation_type,
                "percentage": line.percentage,
                "amount_monthly_minor": line.amount_monthly_minor,
                "base_salary_component_id": line.base_salary_component_id,
                "max_monthly_minor": line.max_monthly_minor,
                "applies_when": line.applies_when,
                "display_order": line.display_order,
                "created_at": now,
                "updated_at": now,
            }
            for line in lines
        ]
        if rows:
            try:
                validate_structure(
                    _to_structure_lines([SalaryStructureLine(**r) for r in rows], components)
                )
            except BreakupError as exc:
                raise SalaryStructureInvalidError(str(exc)) from exc
        return rows

    async def _version_lines(self, company_id: UUID, version_id: UUID) -> list[StructureLine]:
        rows = await self._repo.list_lines(
            self._session, company_id=company_id, version_ids=[version_id]
        )
        component_ids = {r.salary_component_id for r in rows} | {
            r.base_salary_component_id for r in rows if r.base_salary_component_id is not None
        }
        components = await self._component_repo.get_many(
            self._session, company_id=company_id, component_ids=component_ids
        )
        return _to_structure_lines(rows, components)

    async def _record(
        self,
        company_id: UUID,
        structure_id: UUID,
        action: str,
        *,
        actor_user_id: UUID | None,
        before: SalaryStructureRead | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SalaryStructureRead:
        after = await self.get(company_id, structure_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="salary_structure",
            entity_id=structure_id,
            before=before.model_dump(mode="json") if before is not None else None,
            after=after.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after

    # -- writes ------------------------------------------------------------------------

    async def create(
        self,
        company_id: UUID,
        body: SalaryStructureCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryStructureRead:
        await self.ensure_defaults(company_id)
        now = datetime.now(UTC)
        structure_id = uuid4()
        version_id = uuid4()
        line_rows = await self._line_rows(company_id, version_id, body.lines)
        try:
            async with self._session.begin_nested():
                await self._repo.insert(
                    self._session,
                    data={
                        "id": structure_id,
                        "company_id": company_id,
                        "code": body.code,
                        "name": body.name,
                        "description": body.description,
                        "is_active": True,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError as exc:
            raise SalaryStructureCodeAlreadyExistsError() from exc
        await self._repo.insert_version(
            self._session,
            data={
                "id": version_id,
                "company_id": company_id,
                "salary_structure_id": structure_id,
                "version_number": 1,
                "status": "DRAFT",
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        await self._repo.replace_lines(
            self._session, company_id=company_id, version_id=version_id, rows=line_rows
        )
        return await self._record(
            company_id,
            structure_id,
            "PAYROLL_SALARY_STRUCTURE_CREATED",
            actor_user_id=actor_user_id,
            before=None,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def update(
        self,
        company_id: UUID,
        structure_id: UUID,
        patch: SalaryStructureUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryStructureRead:
        await self._get_row(company_id, structure_id)
        before = await self.get(company_id, structure_id)
        values = {field: getattr(patch, field) for field in patch.model_fields_set}
        if values:
            result = await self._repo.update(
                self._session,
                company_id=company_id,
                structure_id=structure_id,
                values=values,
                expected_version=expected_version,
                now=datetime.now(UTC),
            )
            if result is None:
                raise StalePayrollResourceError(
                    "This salary structure has been modified by another request",
                    current=before.model_dump(mode="json"),
                )
        return await self._record(
            company_id,
            structure_id,
            "PAYROLL_SALARY_STRUCTURE_UPDATED",
            actor_user_id=actor_user_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def create_version(
        self,
        company_id: UUID,
        structure_id: UUID,
        body: SalaryStructureVersionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryStructureRead:
        await self._get_row(company_id, structure_id)
        before = await self.get(company_id, structure_id)
        if any(v.status == "DRAFT" for v in before.versions):
            raise SalaryStructureDraftExistsError()
        version_id = uuid4()
        if body.lines is not None:
            line_rows = await self._line_rows(company_id, version_id, body.lines)
        else:
            latest = next((v for v in before.versions if v.status == "PUBLISHED"), None)
            line_rows = await self._line_rows(
                company_id,
                version_id,
                [
                    SalaryStructureLineInput(
                        salary_component_id=line.salary_component_id,
                        calculation_type=line.calculation_type,
                        percentage=Decimal(line.percentage) if line.percentage else None,
                        amount_monthly_minor=line.amount_monthly_minor,
                        base_salary_component_id=line.base_salary_component_id,
                        max_monthly_minor=line.max_monthly_minor,
                        applies_when=line.applies_when,
                        display_order=line.display_order,
                    )
                    for line in (latest.lines if latest is not None else [])
                ],
            )
        now = datetime.now(UTC)
        next_number = max((v.version_number for v in before.versions), default=0) + 1
        try:
            async with self._session.begin_nested():
                await self._repo.insert_version(
                    self._session,
                    data={
                        "id": version_id,
                        "company_id": company_id,
                        "salary_structure_id": structure_id,
                        "version_number": next_number,
                        "status": "DRAFT",
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError as exc:
            raise SalaryStructureDraftExistsError() from exc
        await self._repo.replace_lines(
            self._session, company_id=company_id, version_id=version_id, rows=line_rows
        )
        return await self._record(
            company_id,
            structure_id,
            "PAYROLL_SALARY_STRUCTURE_VERSION_CREATED",
            actor_user_id=actor_user_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _get_draft(
        self, company_id: UUID, structure_id: UUID, version_id: UUID
    ) -> SalaryStructureVersion:
        version = await self._repo.get_version(
            self._session, company_id=company_id, structure_id=structure_id, version_id=version_id
        )
        if version is None:
            raise SalaryStructureVersionNotFoundError()
        if version.status != "DRAFT":
            raise SalaryStructureVersionNotDraftError()
        return version

    async def update_version_lines(
        self,
        company_id: UUID,
        structure_id: UUID,
        version_id: UUID,
        lines: list[SalaryStructureLineInput],
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryStructureRead:
        await self._get_draft(company_id, structure_id, version_id)
        before = await self.get(company_id, structure_id)
        line_rows = await self._line_rows(company_id, version_id, lines)
        bumped = await self._repo.update_version(
            self._session,
            company_id=company_id,
            version_id=version_id,
            values={},
            expected_version=expected_version,
            now=datetime.now(UTC),
        )
        if bumped is None:
            raise StalePayrollResourceError(
                "This salary structure version has been modified by another request",
                current=before.model_dump(mode="json"),
            )
        await self._repo.replace_lines(
            self._session, company_id=company_id, version_id=version_id, rows=line_rows
        )
        return await self._record(
            company_id,
            structure_id,
            "PAYROLL_SALARY_STRUCTURE_VERSION_UPDATED",
            actor_user_id=actor_user_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def publish_version(
        self,
        company_id: UUID,
        structure_id: UUID,
        version_id: UUID,
        body: SalaryStructureVersionPublish,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryStructureRead:
        """The draft becomes the structure's version from `effective_from`; the previously open
        published version ends the day before. Employees assigned to the structure pick the new
        version up from that date — past breakups and (from 5.2) pay runs keep what they used."""
        await self._get_draft(company_id, structure_id, version_id)
        before = await self.get(company_id, structure_id)
        lines = await self._version_lines(company_id, version_id)
        try:
            validate_structure(lines)
        except BreakupError as exc:
            raise SalaryStructureInvalidError(str(exc)) from exc
        now = datetime.now(UTC)
        current = await self._repo.get_open_published(
            self._session, company_id=company_id, structure_id=structure_id
        )
        if current is not None:
            if current.effective_from is not None and body.effective_from <= current.effective_from:
                raise SalaryStructureEffectiveFromError()
            await self._repo.update_version(
                self._session,
                company_id=company_id,
                version_id=current.id,
                values={"effective_to": body.effective_from - timedelta(days=1)},
                expected_version=None,
                now=now,
            )
        published = await self._repo.update_version(
            self._session,
            company_id=company_id,
            version_id=version_id,
            values={
                "status": "PUBLISHED",
                "effective_from": body.effective_from,
                "published_at": now,
                "published_by_user_id": actor_user_id,
            },
            expected_version=expected_version,
            now=now,
        )
        if published is None:
            raise StalePayrollResourceError(
                "This salary structure version has been modified by another request",
                current=before.model_dump(mode="json"),
            )
        return await self._record(
            company_id,
            structure_id,
            "PAYROLL_SALARY_STRUCTURE_VERSION_PUBLISHED",
            actor_user_id=actor_user_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def discard_version(
        self,
        company_id: UUID,
        structure_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SalaryStructureRead:
        await self._get_draft(company_id, structure_id, version_id)
        before = await self.get(company_id, structure_id)
        await self._repo.delete_version(self._session, company_id=company_id, version_id=version_id)
        return await self._record(
            company_id,
            structure_id,
            "PAYROLL_SALARY_STRUCTURE_VERSION_DISCARDED",
            actor_user_id=actor_user_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def structure_lines_for(
        self, company_id: UUID, lines: list[SalaryStructureLineInput]
    ) -> list[StructureLine]:
        """Unsaved line inputs, validated as a structure (`_line_rows`), ready for
        `compute_breakup`."""
        rows = await self._line_rows(company_id, uuid4(), lines)
        component_ids = {r["salary_component_id"] for r in rows} | {
            r["base_salary_component_id"] for r in rows if r["base_salary_component_id"]
        }
        components = await self._component_repo.get_many(
            self._session, company_id=company_id, component_ids=component_ids
        )
        return _to_structure_lines([SalaryStructureLine(**r) for r in rows], components)

    async def save_for_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        template: SalaryStructure,
        lines: list[SalaryStructureLineInput],
        effective_from: date,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> UUID:
        """The employee's own structure paying `lines` from `effective_from`: created (published
        from that date) the first time, otherwise a new version published from that date — or
        left alone when the version in effect already pays exactly these lines. Returns its id."""
        existing = await self._repo.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if existing is None:
            now = datetime.now(UTC)
            structure_id = uuid4()
            version_id = uuid4()
            line_rows = await self._line_rows(company_id, version_id, lines)
            await self._repo.insert(
                self._session,
                data={
                    "id": structure_id,
                    "company_id": company_id,
                    "code": f"EMP_{employee_id.hex[:26]}",
                    "name": f"{template.name} (customised)",
                    "description": f"Changed for one employee from {template.name}",
                    "is_active": True,
                    "employee_id": employee_id,
                    "based_on_structure_id": template.id,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await self._repo.insert_version(
                self._session,
                data={
                    "id": version_id,
                    "company_id": company_id,
                    "salary_structure_id": structure_id,
                    "version_number": 1,
                    "status": "PUBLISHED",
                    "effective_from": effective_from,
                    "published_at": now,
                    "published_by_user_id": actor_user_id,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await self._repo.replace_lines(
                self._session, company_id=company_id, version_id=version_id, rows=line_rows
            )
            await self._record(
                company_id,
                structure_id,
                "PAYROLL_SALARY_STRUCTURE_CREATED",
                actor_user_id=actor_user_id,
                before=None,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return structure_id

        current = await self.get(company_id, existing.id)
        in_effect = _published_as_of(current, effective_from)
        if in_effect is not None and _read_keys(in_effect.lines) == _input_keys(lines):
            return existing.id
        if existing.based_on_structure_id != template.id:
            # Re-based on another template; the version audit below records the change.
            await self._repo.update(
                self._session,
                company_id=company_id,
                structure_id=existing.id,
                values={
                    "based_on_structure_id": template.id,
                    "name": f"{template.name} (customised)",
                    "description": f"Changed for one employee from {template.name}",
                },
                expected_version=existing.version,
                now=datetime.now(UTC),
            )
        draft = next((v for v in current.versions if v.status == "DRAFT"), None)
        if draft is not None:
            await self._repo.delete_version(
                self._session, company_id=company_id, version_id=draft.id
            )
        created = await self.create_version(
            company_id,
            existing.id,
            SalaryStructureVersionCreate(lines=lines),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        new_draft = next(v for v in created.versions if v.status == "DRAFT")
        await self.publish_version(
            company_id,
            existing.id,
            new_draft.id,
            SalaryStructureVersionPublish(effective_from=effective_from),
            expected_version=new_draft.version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return existing.id

    async def preview(
        self,
        company_id: UUID,
        structure_id: UUID,
        version_id: UUID,
        body: SalaryBreakupPreviewInput,
    ) -> SalaryBreakupRead:
        version = await self._repo.get_version(
            self._session, company_id=company_id, structure_id=structure_id, version_id=version_id
        )
        if version is None:
            raise SalaryStructureVersionNotFoundError()
        lines = await self._version_lines(company_id, version_id)
        try:
            breakup = compute_breakup(
                lines,
                annual_ctc_minor=body.annual_ctc_minor,
                pf_applicable=body.pf_applicable,
                esi_applicable=body.esi_applicable,
            )
        except BreakupError as exc:
            raise SalaryStructureInvalidError(str(exc)) from exc
        return _breakup_to_read(breakup)

    async def breakup_as_of(
        self,
        company_id: UUID,
        structure_id: UUID,
        as_of: date,
        *,
        annual_ctc_minor: int,
        pf_applicable: bool,
        esi_applicable: bool,
    ) -> tuple[UUID, Breakup]:
        """The breakup from the structure's published version covering `as_of` — the seam the
        pay-run engine (5.2) calls. Raises `SalaryBreakupUnavailableError` when no published
        version covers the date, `BreakupError` when the CTC does not fit the structure."""
        version = await self._repo.get_published_as_of(
            self._session, company_id=company_id, structure_id=structure_id, as_of=as_of
        )
        if version is None:
            raise SalaryBreakupUnavailableError(
                f"The salary structure has no published version on {as_of.isoformat()}"
            )
        lines = await self._version_lines(company_id, version.id)
        return version.id, compute_breakup(
            lines,
            annual_ctc_minor=annual_ctc_minor,
            pf_applicable=pf_applicable,
            esi_applicable=esi_applicable,
        )


# ---------------------------------------------------------------------------
# Employee salary assignment
# ---------------------------------------------------------------------------


class EmployeeSalaryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = EmployeeSalaryRepository()
        self._structures = SalaryStructureService(session)
        self._structure_repo = SalaryStructureRepository()
        self._audit = AuditService()

    async def _ensure_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        from hrms.modules.employee.service import EmployeeService

        await EmployeeService(self._session).get_employee(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

    async def _statutory_flags(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> tuple[bool, bool]:
        from hrms.modules.employee.service import EmployeeStatutoryService

        statutory = await EmployeeStatutoryService(self._session).get_statutory_as_of(
            company_id, employee_id, as_of
        )
        if statutory is None:
            return False, False
        return statutory.is_pf_applicable, statutory.is_esi_applicable

    async def _pay_basis(self, company_id: UUID, employee_id: UUID, as_of: date) -> str | None:
        from hrms.modules.employee.service import EmploymentService

        employment = await EmploymentService(self._session).get_employment_as_of(
            company_id, employee_id, as_of
        )
        return employment.pay_basis if employment is not None else None

    async def _annual_ctc(self, company_id: UUID, employee_id: UUID, as_of: date) -> int | None:
        from hrms.modules.employee.service import EmployeeCompensationService

        compensation = await EmployeeCompensationService(self._session).get_compensation_as_of(
            company_id, employee_id, as_of
        )
        return compensation.annual_ctc_minor if compensation is not None else None

    async def list_for_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> list[EmployeeSalaryRead]:
        await self._ensure_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        rows = await self._repo.list_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [employee_salary_to_read(r) for r in rows]

    async def _validate(
        self, company_id: UUID, employee_id: UUID, body: EmployeeSalaryCreate
    ) -> None:
        """Everything that must hold for the assignment to produce a pay on its first day."""
        structure = (
            await self._structure_repo.get(
                self._session, company_id=company_id, structure_id=body.salary_structure_id
            )
            if body.salary_structure_id is not None
            else None
        )
        if structure is not None and structure.employee_id not in (None, employee_id):
            raise EmployeeSalaryInvalidError(
                "That salary structure belongs to another employee", field="salary_structure_id"
            )
        pay_basis = await self._pay_basis(company_id, employee_id, body.effective_from)
        if pay_basis is None:
            raise EmployeeSalaryInvalidError(
                "The employee has no employment covering effective_from"
            )
        if pay_basis == "DAILY_WAGE" and body.daily_rate_minor is None:
            raise EmployeeSalaryInvalidError(
                "A daily-wage employee is paid a daily rate — send daily_rate_minor",
                field="daily_rate_minor",
            )
        if pay_basis == "MONTHLY" and body.salary_structure_id is None:
            raise EmployeeSalaryInvalidError(
                "A monthly-paid employee needs a salary structure", field="salary_structure_id"
            )
        if body.salary_structure_id is None:
            return
        if structure is None or not structure.is_active:
            raise EmployeeSalaryInvalidError(
                "Salary structure not found or inactive", field="salary_structure_id"
            )
        annual_ctc = await self._annual_ctc(company_id, employee_id, body.effective_from)
        if annual_ctc is None:
            raise EmployeeSalaryInvalidError(
                "The employee has no CTC on effective_from — record compensation first"
            )
        pf, esi = await self._statutory_flags(company_id, employee_id, body.effective_from)
        try:
            await self._structures.breakup_as_of(
                company_id,
                body.salary_structure_id,
                body.effective_from,
                annual_ctc_minor=annual_ctc,
                pf_applicable=pf,
                esi_applicable=esi,
            )
        except SalaryBreakupUnavailableError as exc:
            raise EmployeeSalaryInvalidError(exc.message) from exc
        except BreakupError as exc:
            raise EmployeeSalaryInvalidError(str(exc), field="salary_structure_id") from exc

    async def _insert(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeSalaryCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> EmployeeSalaryRead:
        now = datetime.now(UTC)
        current = await self._repo.get_open(
            self._session, company_id=company_id, employee_id=employee_id
        )
        before = employee_salary_to_read(current) if current is not None else None
        if current is not None:
            if body.effective_from <= current.effective_from:
                raise EmployeeSalaryInvalidError(
                    "effective_from must be after the current assignment's start "
                    f"({current.effective_from.isoformat()})"
                )
            await self._repo.close(
                self._session,
                company_id=company_id,
                salary_id=current.id,
                effective_to=body.effective_from - timedelta(days=1),
                now=now,
            )
        salary_id = uuid4()
        try:
            async with self._session.begin_nested():
                row = await self._repo.insert(
                    self._session,
                    data={
                        "id": salary_id,
                        "company_id": company_id,
                        "employee_id": employee_id,
                        "salary_structure_id": body.salary_structure_id,
                        "daily_rate_minor": body.daily_rate_minor,
                        "effective_from": body.effective_from,
                        "reason": body.reason,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError as exc:
            raise EmployeeSalaryInvalidError(
                "Another salary assignment already covers effective_from"
            ) from exc
        read = employee_salary_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_EMPLOYEE_SALARY_ASSIGNED",
            entity_type="employee_salary",
            entity_id=salary_id,
            before=before.model_dump(mode="json") if before is not None else None,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def create(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeSalaryCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeSalaryRead:
        await self._ensure_visible(company_id, employee_id, scope=None, caller_employee_id=None)
        await self._structures.ensure_defaults(company_id)
        await self._validate(company_id, employee_id, body)
        return await self._insert(
            company_id,
            employee_id,
            body,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def breakup(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> EmployeeSalaryBreakupRead:
        await self._ensure_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        if as_of is None:
            from hrms.modules.organisation.service import OrganisationService

            company = await OrganisationService(self._session).get_company_profile(company_id)
            as_of = business_today(company.timezone)
        pay_basis = await self._pay_basis(company_id, employee_id, as_of)
        if pay_basis is None:
            raise SalaryBreakupUnavailableError(
                f"The employee is not employed on {as_of.isoformat()}"
            )
        salary = await self._repo.get_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        if salary is None:
            raise SalaryBreakupUnavailableError(
                f"No salary structure is assigned on {as_of.isoformat()}"
            )
        pf, esi = await self._statutory_flags(company_id, employee_id, as_of)
        result = EmployeeSalaryBreakupRead(
            employee_id=employee_id,
            as_of=as_of,
            pay_basis=pay_basis,
            salary_structure_id=salary.salary_structure_id,
            salary_structure_version_id=None,
            daily_rate_minor=salary.daily_rate_minor,
            pf_applicable=pf,
            esi_applicable=esi,
            breakup=None,
        )
        if salary.salary_structure_id is None:
            return result
        annual_ctc = await self._annual_ctc(company_id, employee_id, as_of)
        if annual_ctc is None:
            raise SalaryBreakupUnavailableError(f"The employee has no CTC on {as_of.isoformat()}")
        try:
            version_id, breakup = await self._structures.breakup_as_of(
                company_id,
                salary.salary_structure_id,
                as_of,
                annual_ctc_minor=annual_ctc,
                pf_applicable=pf,
                esi_applicable=esi,
            )
        except BreakupError as exc:
            raise SalaryBreakupUnavailableError(str(exc)) from exc
        return result.model_copy(
            update={"salary_structure_version_id": version_id, "breakup": _breakup_to_read(breakup)}
        )

    # -- salary setup (CTC + structure on the employee's Salary tab) --------------------

    async def setup(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> EmployeeSalarySetupRead:
        await self._ensure_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        await self._structures.ensure_defaults(company_id)
        if as_of is None:
            from hrms.modules.organisation.service import OrganisationService

            company = await OrganisationService(self._session).get_company_profile(company_id)
            as_of = business_today(company.timezone)
        pf, esi = await self._statutory_flags(company_id, employee_id, as_of)
        salary = await self._repo.get_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        result = EmployeeSalarySetupRead(
            employee_id=employee_id,
            as_of=as_of,
            pay_basis=await self._pay_basis(company_id, employee_id, as_of),
            annual_ctc_minor=await self._annual_ctc(company_id, employee_id, as_of),
            pf_applicable=pf,
            esi_applicable=esi,
            assignment=employee_salary_to_read(salary) if salary is not None else None,
            salary_structure_id=None,
            salary_structure_name=None,
            template_structure_id=None,
            is_customised=False,
            lines=[],
        )
        if salary is None or salary.salary_structure_id is None:
            return result
        structure = await self._structures.get(company_id, salary.salary_structure_id)
        version = _published_as_of(structure, as_of)
        return result.model_copy(
            update={
                "salary_structure_id": structure.id,
                "salary_structure_name": structure.name,
                "template_structure_id": (
                    structure.based_on_structure_id
                    if structure.employee_id is not None
                    else structure.id
                ),
                "is_customised": structure.employee_id is not None,
                "lines": version.lines if version is not None else [],
            }
        )

    async def setup_preview(
        self, company_id: UUID, employee_id: UUID, body: EmployeeSalarySetupPreviewInput
    ) -> EmployeeSalarySetupPreviewRead:
        """The breakup the Salary tab shows as HR types — nothing is saved."""
        await self._ensure_visible(company_id, employee_id, scope=None, caller_employee_id=None)
        pf, esi = await self._statutory_flags(company_id, employee_id, body.as_of)
        lines = await self._structures.structure_lines_for(company_id, body.lines)
        try:
            breakup = compute_breakup(
                lines,
                annual_ctc_minor=body.annual_ctc_minor,
                pf_applicable=pf,
                esi_applicable=esi,
            )
        except BreakupError as exc:
            raise SalaryStructureInvalidError(str(exc)) from exc
        return EmployeeSalarySetupPreviewRead(
            pf_applicable=pf, esi_applicable=esi, breakup=_breakup_to_read(breakup)
        )

    async def save_setup(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeSalarySetupSave,
        *,
        actor_user_id: UUID | None,
        scope: DataScope,
        caller_employee_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeSalarySetupRead:
        """One transaction: the CTC (a new compensation row when it changes), then the structure —
        the template itself when the lines are the template's, otherwise the employee's own
        structure — assigned from `effective_from` unless already assigned."""
        from hrms.modules.employee.schemas import CompensationCreate
        from hrms.modules.employee.service import EmployeeCompensationService

        # `scope` is `EMPLOYEE.UPDATE_COMPENSATION`'s: a team or branch grant reaches only those
        # employees. `PAYROLL.SETUP_MANAGE` is company-level.
        await self._ensure_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        await self._structures.ensure_defaults(company_id)
        day = body.effective_from
        template = await self._structure_repo.get(
            self._session, company_id=company_id, structure_id=body.template_structure_id
        )
        if template is None or not template.is_active or template.employee_id is not None:
            raise EmployeeSalaryInvalidError(
                "Choose an active company salary structure", field="template_structure_id"
            )
        pay_basis = await self._pay_basis(company_id, employee_id, day)
        if pay_basis is None:
            raise EmployeeSalaryInvalidError(
                "The employee has no employment covering effective_from"
            )
        if pay_basis != "MONTHLY":
            raise EmployeeSalaryInvalidError(
                "A daily-wage employee is paid a daily rate, not a salary structure"
            )

        # Validate everything before writing anything.
        structure_lines = await self._structures.structure_lines_for(company_id, body.lines)
        current_ctc = await self._annual_ctc(company_id, employee_id, day)
        annual_ctc = body.annual_ctc_minor or current_ctc
        if annual_ctc is None:
            raise EmployeeSalaryInvalidError("Enter the employee's CTC", field="annual_ctc_minor")
        pf, esi = await self._statutory_flags(company_id, employee_id, day)
        try:
            compute_breakup(
                structure_lines, annual_ctc_minor=annual_ctc, pf_applicable=pf, esi_applicable=esi
            )
        except BreakupError as exc:
            raise EmployeeSalaryInvalidError(str(exc), field="lines") from exc

        if annual_ctc != current_ctc:
            compensations = EmployeeCompensationService(self._session)
            history = await compensations.list_compensations(company_id, employee_id)
            open_row = next((c for c in history if c.effective_to is None), None)
            revision_type = body.revision_type or ("JOINING" if open_row is None else None)
            if revision_type is None:
                raise EmployeeSalaryInvalidError(
                    "Choose why the CTC is changing", field="revision_type"
                )
            from hrms.modules.organisation.service import OrganisationService

            company = await OrganisationService(self._session).get_company_profile(company_id)
            await compensations.create_compensation(
                company_id,
                employee_id,
                CompensationCreate(
                    effective_from=day,
                    annual_ctc_minor=annual_ctc,
                    currency=company.currency,
                    revision_type=revision_type,  # type: ignore[arg-type]
                    revision_reason=body.reason,
                ),
                expected_version=open_row.version if open_row is not None else None,
                actor_user_id=actor_user_id,
                scope=scope,
                caller_employee_id=caller_employee_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        template_read = await self._structures.get(company_id, template.id)
        template_version = _published_as_of(template_read, day)
        if template_version is not None and _read_keys(template_version.lines) == _input_keys(
            body.lines
        ):
            target_id = template.id
        else:
            try:
                target_id = await self._structures.save_for_employee(
                    company_id,
                    employee_id,
                    template,
                    body.lines,
                    day,
                    actor_user_id=actor_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            except SalaryStructureEffectiveFromError as exc:
                raise EmployeeSalaryInvalidError(
                    "This employee's salary structure already changed on or after "
                    f"{day.isoformat()} — choose a later effective date",
                    field="effective_from",
                ) from exc

        open_salary = await self._repo.get_open(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if open_salary is None or open_salary.salary_structure_id != target_id:
            item = EmployeeSalaryCreate(
                salary_structure_id=target_id, effective_from=day, reason=body.reason
            )
            await self._validate(company_id, employee_id, item)
            await self._insert(
                company_id,
                employee_id,
                item,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return await self.setup(
            company_id, employee_id, as_of=day, scope=None, caller_employee_id=None
        )

    async def bulk_assign(
        self,
        company_id: UUID,
        body: EmployeeSalaryBulkAssign,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeSalaryBulkResult:
        """Each employee is validated and assigned independently; one that cannot be assigned is
        reported in `skipped` with the reason and never blocks the others."""
        from hrms.modules.employee.service import EmploymentService

        await self._structures.ensure_defaults(company_id)
        day = body.effective_from
        spans = await EmploymentService(self._session).list_legal_entity_spans(
            company_id, date_from=day, date_to=day
        )
        employed = {employee_id for employee_id, _, _, _ in spans}
        candidates = (
            [e for e in body.employee_ids] if body.employee_ids is not None else sorted(employed)
        )
        covered = await self._repo.list_employee_ids_covering(
            self._session, company_id=company_id, as_of=day
        )
        assigned: list[UUID] = []
        skipped: list[EmployeeSalaryBulkSkip] = []
        for employee_id in candidates:
            if employee_id not in employed:
                skipped.append(EmployeeSalaryBulkSkip(
                    employee_id=employee_id, reason="Not employed on effective_from"
                ))  # fmt: skip
                continue
            if employee_id in covered:
                skipped.append(EmployeeSalaryBulkSkip(
                    employee_id=employee_id, reason="Already has a salary assignment"
                ))  # fmt: skip
                continue
            if await self._pay_basis(company_id, employee_id, day) == "DAILY_WAGE":
                skipped.append(EmployeeSalaryBulkSkip(
                    employee_id=employee_id,
                    reason="Daily-wage employee — assign a daily rate individually",
                ))  # fmt: skip
                continue
            item = EmployeeSalaryCreate(
                salary_structure_id=body.salary_structure_id,
                effective_from=day,
                reason=body.reason,
            )
            try:
                async with self._session.begin_nested():
                    await self._validate(company_id, employee_id, item)
                    await self._insert(
                        company_id,
                        employee_id,
                        item,
                        actor_user_id=actor_user_id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
            except (EmployeeSalaryInvalidError, NotFoundError) as exc:
                skipped.append(EmployeeSalaryBulkSkip(employee_id=employee_id, reason=exc.message))
                continue
            assigned.append(employee_id)
        return EmployeeSalaryBulkResult(assigned=assigned, skipped=skipped)


# ---------------------------------------------------------------------------
# Phase 5.2 — payroll settings and pay runs
# ---------------------------------------------------------------------------


class PayrollSettingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PayrollSettingRepository()
        self._audit = AuditService()

    async def get(self, company_id: UUID) -> PayrollSettingRead:
        row = await self._repo.get_or_create(
            self._session, company_id=company_id, now=datetime.now(UTC)
        )
        return payroll_setting_to_read(row)

    async def update(
        self,
        company_id: UUID,
        body: PayrollSettingUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayrollSettingRead:
        before = await self.get(company_id)
        row = await self._repo.update(
            self._session,
            company_id=company_id,
            values={"variance_threshold_percent": body.variance_threshold_percent},
            expected_version=expected_version,
            now=datetime.now(UTC),
        )
        if row is None:
            raise StalePayrollResourceError(
                "Payroll settings have been modified by another request",
                current=before.model_dump(mode="json"),
            )
        after = payroll_setting_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_SETTING_UPDATED",
            entity_type="payroll_setting",
            entity_id=company_id,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after


def month_bounds(month: str) -> tuple[date, date, int]:
    """`YYYY-MM` → `(first day, last day, days in month)`."""
    year, number = (int(part) for part in month.split("-"))
    days = calendar.monthrange(year, number)[1]
    return date(year, number, 1), date(year, number, days), days


#: How far back a pay run looks for earlier months to pay arrears for (FR-PAY-010).
ARREARS_LOOKBACK_MONTHS = 12


def _add_months(first_of_month: date, months: int) -> date:
    index = first_of_month.year * 12 + first_of_month.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def default_pay_date(period_end: date) -> date:
    """D11 — the first weekday (Mon–Fri) after the month ends. Holidays are not consulted; the
    date is editable on the run until it is finalised."""
    day = period_end + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _owning_entity(spans: list[tuple[UUID, date, date | None]], day: date) -> UUID | None:
    """Decision 14's ownership rule for an employee-date (the same rule attendance periods use):
    the entity of the employment covering it, else of the latest spell ended before it, else of
    the first spell starting after it."""
    covering = [le for le, start, end in spans if start <= day and (end is None or day <= end)]
    if covering:
        return covering[0]
    before = [(end, le) for le, _start, end in spans if end is not None and end < day]
    if before:
        return max(before, key=lambda item: item[0])[1]
    after = [(start, le) for le, start, _end in spans if start > day]
    if after:
        return min(after, key=lambda item: item[0])[1]
    return None


def _issue(code: str, message: str, severity: str = ERROR) -> dict[str, str]:
    return Issue(code, severity, message).to_dict()


_ROLLBACK_FROM: dict[str, tuple[str, ...]] = {
    "DRAFT": ("INPUTS_LOCKED", "COMPUTED", "APPROVED"),
    "INPUTS_LOCKED": ("COMPUTED", "APPROVED"),
}

_RESET_COMPUTED: dict[str, Any] = {
    "is_computed": False,
    "gross_minor": 0,
    "deductions_minor": 0,
    "employer_contributions_minor": 0,
    "net_before_rounding_minor": 0,
    "rounding_minor": 0,
    "net_minor": 0,
    "previous_net_minor": None,
    "variance_percent": None,
    "variance_flagged": False,
    "variance_reason": None,
    "variance_acknowledged_by_user_id": None,
    "variance_acknowledged_at": None,
}

_RESET_RUN_TOTALS: dict[str, Any] = {
    "gross_minor": 0,
    "deductions_minor": 0,
    "employer_contributions_minor": 0,
    "net_minor": 0,
    "variance_flag_count": 0,
    "variance_open_count": 0,
    "computed_at": None,
    "computed_by_user_id": None,
    "approved_at": None,
    "approved_by_user_id": None,
    "previous_pay_run_id": None,
    "variance_threshold_percent": None,
}


class PayRunService:
    """Payroll Phase 5.2 — the monthly pay run of one legal entity (plan §3–4, FR-PAY-007/008/
    009/014/015/023/024/025).

    - **lock inputs** (`DRAFT → INPUTS_LOCKED`): refuses unless the entity's attendance period
      for exactly that month is `CLOSED` (PD-2); snapshots, per employee, the frozen summary, the
      salary per segment of the month (structure version + breakup, or daily rate), statutory
      applicability, payable overtime with multipliers, leave encashments and a bank reference.
      Nothing after this reads live data.
    - **compute** (`INPUTS_LOCKED`/`COMPUTED → COMPUTED`): `engine.compute_employee` over each
      snapshot; validation issues; variance against the entity's previous finalised run.
    - **approve** (`COMPUTED → APPROVED`): no employee with an error, every flagged variance
      acknowledged, the attendance period unchanged since the snapshot, and the approver is not
      the user who computed (D9).
    - **finalise** (`APPROVED → FINALISED`): immutable from here; the attendance period can no
      longer be reopened (decision 15). **mark paid** (`FINALISED → PAID`).
    - **rollback** to `DRAFT` or `INPUTS_LOCKED`, allowed only before `FINALISED`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PayRunRepository()
        self._settings = PayrollSettingService(session)
        self._salary_repo = EmployeeSalaryRepository()
        self._structure_repo = SalaryStructureRepository()
        self._component_repo = SalaryComponentRepository()
        self._structures = SalaryStructureService(session)
        self._adjustment_repo = PayAdjustmentRepository()
        self._arrear_repo = PayRunArrearRepository()
        self._audit = AuditService()

    # -- reads -----------------------------------------------------------------------

    async def _get_row(self, company_id: UUID, run_id: UUID) -> PayRun:
        row = await self._repo.get(self._session, company_id=company_id, run_id=run_id)
        if row is None:
            raise PayRunNotFoundError()
        return row

    async def get(self, company_id: UUID, run_id: UUID) -> PayRunRead:
        return pay_run_to_read(await self._get_row(company_id, run_id))

    async def list_runs(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        legal_entity_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[PayRunRead], int]:
        rows, total = await self._repo.page_for_company(
            self._session,
            company_id=company_id,
            page=page,
            legal_entity_id=legal_entity_id,
            status=status,
        )
        return [pay_run_to_read(row) for row in rows], total

    async def list_employees(
        self, company_id: UUID, run_id: UUID, *, page: PageParams
    ) -> tuple[list[PayRunEmployeeRead], int]:
        await self._get_row(company_id, run_id)
        rows, total = await self._repo.page_employees(
            self._session, company_id=company_id, run_id=run_id, page=page
        )
        return [pay_run_employee_to_read(row) for row in rows], total

    async def get_employee(
        self, company_id: UUID, run_id: UUID, employee_id: UUID
    ) -> PayRunEmployeeDetailRead:
        await self._get_row(company_id, run_id)
        row = await self._repo.get_employee(
            self._session, company_id=company_id, run_id=run_id, employee_id=employee_id
        )
        if row is None:
            raise PayRunEmployeeNotFoundError()
        lines = await self._repo.list_lines(
            self._session, company_id=company_id, run_id=run_id, employee_id=employee_id
        )
        return PayRunEmployeeDetailRead(
            **pay_run_employee_to_read(row).model_dump(),
            lines=[pay_run_line_to_read(line) for line in lines],
            snapshot=row.snapshot,
        )

    async def has_finalised_run_for_period(self, company_id: UUID, period_id: UUID) -> bool:
        """Decision 15 — `AttendancePeriodService.reopen` refuses when this is true."""
        return await self._repo.has_finalised_for_period(
            self._session, company_id=company_id, attendance_period_id=period_id
        )

    # -- helpers ---------------------------------------------------------------------

    async def _transition(
        self,
        run: PayRun,
        *,
        values: dict[str, Any],
        expected_version: int | None,
        from_statuses: tuple[str, ...],
    ) -> PayRun:
        updated = await self._repo.update(
            self._session,
            company_id=run.company_id,
            run_id=run.id,
            values=values,
            expected_version=expected_version,
            now=datetime.now(UTC),
            from_statuses=from_statuses,
        )
        if updated is not None:
            return updated
        latest = await self._get_row(run.company_id, run.id)
        if latest.status not in from_statuses:
            raise PayRunInvalidTransitionError(
                f"The pay run is {latest.status}; this action needs {' or '.join(from_statuses)}"
            )
        raise StalePayrollResourceError(
            "This pay run has been modified by another request",
            current=pay_run_to_read(latest).model_dump(mode="json"),
        )

    def _require_status(self, run: PayRun, *statuses: str) -> None:
        if run.status not in statuses:
            raise PayRunInvalidTransitionError(
                f"The pay run is {run.status}; this action needs {' or '.join(statuses)}"
            )

    async def _record(
        self,
        run_id: UUID,
        company_id: UUID,
        action: str,
        *,
        before: PayRunRead | None,
        after: PayRunRead | None,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        after_payload = after.model_dump(mode="json") if after is not None else None
        if extra and after_payload is not None:
            after_payload = {**after_payload, **extra}
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="pay_run",
            entity_id=run_id,
            before=before.model_dump(mode="json") if before is not None else None,
            after=after_payload,
            ip=ip_address,
            user_agent=user_agent,
        )

    async def _assert_attendance_unchanged(self, run: PayRun) -> None:
        from hrms.modules.attendance.service import AttendancePeriodService

        if run.attendance_period_id is None:
            raise PayRunAttendanceChangedError()
        state = await AttendancePeriodService(self._session).period_state(
            run.company_id, run.attendance_period_id
        )
        if state != ("CLOSED", run.attendance_period_version):
            raise PayRunAttendanceChangedError()

    async def _assert_inputs_unchanged(self, run: PayRun) -> None:
        """PD-4 — approval and finalisation are refused when anything the locked snapshot was
        built from has changed since. The snapshot is rebuilt from live data exactly as
        `lock_inputs` built it and compared with the stored one, so the check covers every input
        that reaches the engine — employment and pay basis, CTC, statutory profile, salary
        assignment, structure version, component flags, bank reference, statutory rates, the
        attendance summary and the set of employees — and cannot drift out of step with it.

        Two parts of the snapshot are deliberately not compared (`_fingerprint`): `arrears`, which
        has its own check at finalisation (`PayRunArrearsStaleError`) and carries a day
        correction recorded later to the next run, and the year-to-date TDS totals, which follow
        from finalised runs rather than from an edited input. Nothing is mutated here; the run
        stays as it was and must be rolled back to draft and locked again."""
        from hrms.modules.attendance.service import AttendancePeriodService

        inputs = await AttendancePeriodService(self._session).closed_period_for_month(
            run.company_id, run.legal_entity_id, run.period_start, run.period_end
        )
        if inputs is None:
            raise PayRunAttendanceChangedError()
        stored = {
            e.employee_id: e
            for e in await self._repo.list_employees(
                self._session, company_id=run.company_id, run_id=run.id
            )
        }
        live = {
            row["employee_id"]: row
            for row in await self._build_snapshots(
                run, inputs, datetime.now(UTC), with_arrears=False
            )
        }
        changes: list[dict[str, Any]] = []
        for employee_id in sorted(set(stored) | set(live), key=str):
            before = stored[employee_id].snapshot if employee_id in stored else None
            after = live[employee_id]["snapshot"] if employee_id in live else None
            if before is None or after is None:
                code = (
                    stored[employee_id].employee_code
                    if employee_id in stored
                    else live[employee_id]["employee_code"]
                )
                changes.append({
                    "employee_id": str(employee_id),
                    "employee_code": code,
                    "sections": ["EMPLOYEE_ADDED" if before is None else "EMPLOYEE_REMOVED"],
                })  # fmt: skip
                continue
            was, now = self._fingerprint(before), self._fingerprint(after)
            sections = sorted(
                key for key in was.keys() | now.keys() if was.get(key) != now.get(key)
            )
            if sections:
                changes.append({
                    "employee_id": str(employee_id),
                    "employee_code": stored[employee_id].employee_code,
                    "sections": sections,
                })  # fmt: skip
        if changes:
            raise PayRunInputsChangedError(changes)

    @staticmethod
    def _fingerprint(snapshot: dict[str, Any]) -> dict[str, str]:
        """One digest per snapshot section; see `_assert_inputs_unchanged` for what is left out."""
        sections = {k: v for k, v in snapshot.items() if k != "arrears"}
        tax = sections.get("income_tax")
        if isinstance(tax, dict):
            sections["income_tax"] = {k: v for k, v in tax.items() if not k.startswith("ytd_")}
        return {
            key: hashlib.sha256(
                json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()
            for key, value in sections.items()
        }

    # -- create / edit / delete ------------------------------------------------------

    @logged_operation("payroll.pay_run.create")
    async def create(
        self,
        company_id: UUID,
        body: PayRunCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        from hrms.modules.organisation.service import OrganisationService

        try:
            entity = await OrganisationService(self._session).get_legal_entity(
                company_id, body.legal_entity_id
            )
        except NotFoundError as exc:
            raise PayRunLegalEntityInvalidError() from exc
        if not entity.is_active:
            raise PayRunLegalEntityInvalidError()
        start, end, days = month_bounds(body.month)
        now = datetime.now(UTC)
        run_id = uuid4()
        try:
            async with self._session.begin_nested():
                row = await self._repo.insert(
                    self._session,
                    data={
                        "id": run_id,
                        "company_id": company_id,
                        "legal_entity_id": body.legal_entity_id,
                        "period_month": start,
                        "period_start": start,
                        "period_end": end,
                        "days_in_month": days,
                        "status": "DRAFT",
                        "pay_date": body.pay_date or default_pay_date(end),
                        "created_by_user_id": actor_user_id,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError as exc:
            raise PayRunAlreadyExistsError() from exc
        read = pay_run_to_read(row)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_CREATED",
            before=None,
            after=read,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return read

    async def update(
        self,
        company_id: UUID,
        run_id: UUID,
        body: PayRunUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        run = await self._get_row(company_id, run_id)
        before = pay_run_to_read(run)
        if body.pay_date < run.period_end:
            raise PayRunInvalidTransitionError("The pay date cannot be before the month ends")
        updated = await self._transition(
            run,
            values={"pay_date": body.pay_date},
            expected_version=expected_version,
            from_statuses=("DRAFT", "INPUTS_LOCKED", "COMPUTED", "APPROVED"),
        )
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_UPDATED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    @logged_operation("payroll.pay_run.delete")
    async def delete(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        run = await self._get_row(company_id, run_id)
        self._require_status(run, "DRAFT")
        before = pay_run_to_read(run)
        if not await self._repo.delete_draft(self._session, company_id=company_id, run_id=run_id):
            raise PayRunInvalidTransitionError("Only a DRAFT pay run can be deleted")
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_DELETED",
            before=before,
            after=None,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # -- lock inputs (snapshot) ------------------------------------------------------

    async def _segments(
        self,
        company_id: UUID,
        employee_id: UUID,
        spans: list[tuple[date, date]],
        components: dict[str, SalaryComponent],
        issues: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Splits the employee's days in this entity into segments over which employment, CTC,
        statutory profile, salary assignment and structure version are all constant, and resolves
        the pay of each."""
        from hrms.modules.employee.service import (
            EmployeeCompensationService,
            EmployeeStatutoryService,
        )

        if not spans:
            return []
        compensations = await EmployeeCompensationService(self._session).list_compensations(
            company_id, employee_id
        )
        statutories = await EmployeeStatutoryService(self._session).list_statutories(
            company_id, employee_id
        )
        salaries = await self._salary_repo.list_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        versions = await self._structure_repo.list_versions(
            self._session,
            company_id=company_id,
            structure_ids=sorted(
                {s.salary_structure_id for s in salaries if s.salary_structure_id is not None},
                key=str,
            ),
        )
        cuts: set[date] = set()
        dated: list[tuple[date | None, date | None]] = [
            *((r.effective_from, r.effective_to) for r in compensations),
            *((r.effective_from, r.effective_to) for r in statutories),
            *((r.effective_from, r.effective_to) for r in salaries),
            *((v.effective_from, v.effective_to) for v in versions if v.status == "PUBLISHED"),
        ]
        for start, end in dated:
            if start is not None:
                cuts.add(start)
            if end is not None:
                cuts.add(end + timedelta(days=1))

        segments: list[dict[str, Any]] = []
        for span_from, span_to in spans:
            points = sorted(c for c in cuts if span_from < c <= span_to)
            starts = [span_from, *points]
            for index, seg_from in enumerate(starts):
                seg_to = (
                    starts[index + 1] - timedelta(days=1) if index + 1 < len(starts) else span_to
                )
                segments.append(
                    await self._segment(
                        company_id, employee_id, seg_from, seg_to, components, issues
                    )
                )
        return segments

    async def _segment(
        self,
        company_id: UUID,
        employee_id: UUID,
        seg_from: date,
        seg_to: date,
        components: dict[str, SalaryComponent],
        issues: list[dict[str, str]],
    ) -> dict[str, Any]:
        from hrms.modules.employee.service import (
            EmployeeCompensationService,
            EmployeeStatutoryService,
            EmploymentService,
        )

        label = (
            seg_from.isoformat()
            if seg_from == seg_to
            else f"{seg_from.isoformat()} to {seg_to.isoformat()}"
        )
        segment: dict[str, Any] = {
            "from": seg_from.isoformat(),
            "to": seg_to.isoformat(),
            "employed_days": (seg_to - seg_from).days + 1,
            "pay_basis": None,
            "valid": False,
        }
        employment = await EmploymentService(self._session).get_employment_as_of(
            company_id, employee_id, seg_from
        )
        if employment is None:
            issues.append(_issue("EMPLOYMENT_MISSING", f"No employment covers {label}"))
            return segment
        segment["pay_basis"] = employment.pay_basis
        statutory = await EmployeeStatutoryService(self._session).get_statutory_as_of(
            company_id, employee_id, seg_from
        )
        pf = bool(statutory and statutory.is_pf_applicable)
        esi = bool(statutory and statutory.is_esi_applicable)
        segment.update(pf_applicable=pf, esi_applicable=esi)
        salary = await self._salary_repo.get_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=seg_from
        )
        if salary is None:
            issues.append(_issue("SALARY_MISSING", f"No salary is assigned for {label}"))
            return segment
        segment["employee_salary_id"] = str(salary.id)
        if employment.pay_basis == "DAILY_WAGE":
            if salary.daily_rate_minor is None:
                issues.append(_issue(
                    "SALARY_BASIS_MISMATCH",
                    f"Daily-wage employee has a salary structure, not a daily rate, for {label}",
                ))  # fmt: skip
                return segment
            segment.update(valid=True, daily_rate_minor=salary.daily_rate_minor)
            return segment
        if salary.salary_structure_id is None:
            issues.append(_issue(
                "SALARY_BASIS_MISMATCH",
                f"Monthly-paid employee has a daily rate, not a salary structure, for {label}",
            ))  # fmt: skip
            return segment
        compensation = await EmployeeCompensationService(self._session).get_compensation_as_of(
            company_id, employee_id, seg_from
        )
        if compensation is None:
            issues.append(_issue("CTC_MISSING", f"No CTC is recorded for {label}"))
            return segment
        try:
            version_id, breakup = await self._structures.breakup_as_of(
                company_id,
                salary.salary_structure_id,
                seg_from,
                annual_ctc_minor=compensation.annual_ctc_minor,
                pf_applicable=pf,
                esi_applicable=esi,
            )
        except SalaryBreakupUnavailableError as exc:
            issues.append(_issue("BREAKUP_FAILED", f"{exc.message} ({label})"))
            return segment
        except BreakupError as exc:
            issues.append(_issue("BREAKUP_FAILED", f"{exc} ({label})"))
            return segment
        segment.update(
            valid=True,
            salary_structure_id=str(salary.salary_structure_id),
            salary_structure_version_id=str(version_id),
            employee_compensation_id=str(compensation.id),
            annual_ctc_minor=compensation.annual_ctc_minor,
            lines=[
                {
                    "component_code": line.component_code,
                    "component_name": line.component_name,
                    "component_type": line.component_type,
                    "monthly_minor": line.monthly_minor,
                    "is_prorated": (
                        components[line.component_code].is_prorated
                        if line.component_code in components
                        else True
                    ),
                    "display_order": (
                        components[line.component_code].display_order
                        if line.component_code in components
                        else 0
                    ),
                    "is_pf_wage": (
                        line.component_code in components
                        and components[line.component_code].is_pf_wage
                    ),
                    "is_esi_wage": (
                        line.component_code in components
                        and components[line.component_code].is_esi_wage
                    ),
                    "basis": line.basis,
                }
                for line in breakup.lines
            ],
        )
        return segment

    async def _bank(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> dict[str, Any] | None:
        """A reference to the payout account — never the account number itself (last four digits
        only; the bank advice in 5.4 reads the encrypted record by id)."""
        from hrms.modules.employee.service import EmployeeBankService

        bank = await EmployeeBankService(self._session).get_bank_as_of(
            company_id, employee_id, as_of
        )
        if bank is None:
            return None
        account = bank.account_number_enc
        return {
            "employee_bank_id": str(bank.id),
            "payment_mode": bank.payment_mode,
            "bank_name": bank.bank_name,
            "ifsc": bank.ifsc,
            "account_last4": account[-4:] if account else None,
            "verification_status": bank.verification_status,
        }

    async def _statutory(
        self,
        company_id: UUID,
        employee_id: UUID,
        spans: list[tuple[date, date]],
        month_end: date,
        *,
        date_of_birth: date | None,
        gender: str | None,
    ) -> dict[str, Any]:
        """Phase 5.3 — what `statutory.compute_statutory` needs: the statutory profile as of the
        employee's last day in this entity in the month, the employee facts it depends on, and
        the rates in force at month end (PT and LWF for the profile's PT state)."""
        from hrms.modules.employee.service import EmployeeService, EmployeeStatutoryService

        as_of = max((end for _start, end in spans), default=month_end)
        profile = await EmployeeStatutoryService(self._session).get_statutory_as_of(
            company_id, employee_id, as_of
        )
        pt_state = profile.pt_state_code.upper() if profile and profile.pt_state_code else None
        profile_data = (
            {
                "statutory_id": str(profile.id),
                "is_pf_applicable": profile.is_pf_applicable,
                "pf_wage_ceiling_opt_out": profile.pf_wage_ceiling_opt_out,
                "vpf_amount": profile.vpf_amount,
                "vpf_percentage": (
                    str(profile.vpf_percentage) if profile.vpf_percentage is not None else None
                ),
                "is_esi_applicable": profile.is_esi_applicable,
                "esi_ip_number": profile.esi_ip_number,
                "pt_state_code": pt_state,
                "is_lwf_applicable": profile.is_lwf_applicable,
            }
            if profile is not None
            else None
        )
        rates = await StatutoryRateService(self._session).rates_for(company_id, month_end, pt_state)
        return {
            "month_end": month_end.isoformat(),
            "profile": profile_data,
            "employee": {
                "uan_number": await EmployeeService(self._session).get_uan_number(
                    company_id, employee_id
                ),
                "date_of_birth": date_of_birth.isoformat() if date_of_birth else None,
                "gender": gender.upper() if gender else None,
            },
            "rates": rates,
        }

    async def _income_tax(
        self,
        company_id: UUID,
        legal_entity_id: UUID,
        employee_id: UUID,
        spans: list[tuple[date, date]],
        month_end: date,
        period_month: date,
    ) -> dict[str, Any]:
        """Phase 5.6 — what `income_tax.compute_tds` needs: the employee's tax regime and
        whether they have a PAN on file, what has actually been paid and deducted so far this
        financial year in this legal entity's finalised runs, and the TDS slab rate in force."""
        from hrms.modules.employee.service import EmployeeService, EmployeeStatutoryService

        as_of = max((end for _start, end in spans), default=month_end)
        profile = await EmployeeStatutoryService(self._session).get_statutory_as_of(
            company_id, employee_id, as_of
        )
        profile_data = (
            {
                "tax_regime": profile.tax_regime,
                "has_pan": await EmployeeService(self._session).has_pan(company_id, employee_id),
            }
            if profile is not None
            else None
        )
        fy_start = financial_year_start(period_month)
        ytd = await self._repo.ytd_income_tax_totals(
            self._session,
            company_id=company_id,
            legal_entity_id=legal_entity_id,
            employee_id=employee_id,
            fy_start=fy_start,
            before_month=period_month,
        )
        rates = await StatutoryRateService(self._session).rates_for(company_id, month_end, None)
        return {
            "period_month": period_month.isoformat(),
            "profile": profile_data,
            "ytd_taxable_earnings_minor": ytd["gross_minor"],
            "ytd_tds_deducted_minor": ytd["tds_minor"],
            "rate": rates.get("TDS"),
        }

    # -- arrears (Phase 5.5) -------------------------------------------------------------

    async def _paid_for(self, prior: PayRun, employee_id: UUID) -> dict[str, dict[str, Any]]:
        """What has been paid for `prior`'s month: its own lines plus arrears for that month in
        finalised runs since, per component."""
        paid: dict[str, dict[str, Any]] = {}
        for line in await self._repo.list_lines(
            self._session, company_id=prior.company_id, run_id=prior.id, employee_id=employee_id
        ):
            if line.line_type == "ROUNDING" or line.component_code.startswith(ARREARS_PREFIX):
                continue
            paid[line.component_code] = {
                "amount_minor": line.amount_minor,
                "line_type": line.line_type,
                "component_name": line.component_name,
                "display_order": line.display_order,
            }
        extra = await self._arrear_repo.paid_for_month(
            self._session,
            company_id=prior.company_id,
            employee_id=employee_id,
            for_month=prior.period_month,
        )
        for code, amount in extra.items():
            entry = paid.setdefault(
                code,
                {"amount_minor": 0, "line_type": "EARNING", "component_name": code,
                 "display_order": 0},
            )  # fmt: skip
            entry["amount_minor"] += amount
        return paid

    async def _changed_since(self, company_id: UUID, employee_id: UUID, prior: PayRun) -> bool:
        """Whether any salary input covering `prior`'s month — CTC, statutory profile, salary
        assignment, or a structure version — was recorded after that run was finalised."""
        from hrms.modules.employee.service import (
            EmployeeCompensationService,
            EmployeeStatutoryService,
        )

        if prior.finalised_at is None:
            return False
        cutoff = prior.finalised_at
        start, end = prior.period_start, prior.period_end

        def overlaps(frm: date | None, to: date | None) -> bool:
            return frm is not None and frm <= end and (to is None or to >= start)

        def after_cutoff(stamp: str | datetime | None) -> bool:
            if stamp is None:
                return False
            value = (
                stamp if isinstance(stamp, datetime)
                else datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            )  # fmt: skip
            return value > cutoff

        for row in await EmployeeCompensationService(self._session).list_compensations(
            company_id, employee_id
        ):
            if overlaps(row.effective_from, row.effective_to) and after_cutoff(row.updated_at):
                return True
        for statutory in await EmployeeStatutoryService(self._session).list_statutories(
            company_id, employee_id
        ):
            if overlaps(statutory.effective_from, statutory.effective_to) and after_cutoff(
                statutory.updated_at
            ):
                return True
        salaries = await self._salary_repo.list_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        for salary in salaries:
            if overlaps(salary.effective_from, salary.effective_to) and after_cutoff(
                salary.updated_at
            ):
                return True
        structure_ids = sorted(
            {
                s.salary_structure_id
                for s in salaries
                if s.salary_structure_id is not None and overlaps(s.effective_from, s.effective_to)
            },
            key=str,
        )
        for version in await self._structure_repo.list_versions(
            self._session, company_id=company_id, structure_ids=structure_ids
        ):
            if (
                version.status == "PUBLISHED"
                and overlaps(version.effective_from, version.effective_to)
                and after_cutoff(version.published_at)
            ):
                return True
        return False

    @staticmethod
    def _segment_key(segments: list[dict[str, Any]]) -> list[Any]:
        return [
            (
                s.get("from"), s.get("to"), s.get("pay_basis"), s.get("valid"),
                s.get("daily_rate_minor"), bool(s.get("pf_applicable")),
                bool(s.get("esi_applicable")),
                sorted(
                    (line["component_code"], line["monthly_minor"], line.get("is_prorated"))
                    for line in s.get("lines", [])
                ),
            )
            for s in segments
        ]  # fmt: skip

    async def _arrears_for(
        self, run: PayRun, employee_id: UUID, components: dict[str, SalaryComponent]
    ) -> list[dict[str, Any]]:
        """FR-PAY-010 — earlier months of this legal entity (up to `ARREARS_LOOKBACK_MONTHS`)
        whose pay should now differ: a salary input recorded after the month was finalised
        (backdated revision), or a pending day correction (D7). Each is re-snapshotted with
        current salary data over the month's frozen attendance and statutory rates, alongside
        what has been paid for it; the engine pays the difference."""
        from hrms.modules.employee.service import EmployeeStatutoryService, EmploymentService

        company_id = run.company_id
        earliest = _add_months(run.period_month, -ARREARS_LOOKBACK_MONTHS)
        priors = [
            (prior, row)
            for prior, row in await self._repo.list_final_for_employee(
                self._session, company_id=company_id, employee_id=employee_id
            )
            if prior.legal_entity_id == run.legal_entity_id
            and earliest <= prior.period_month < run.period_month
        ]
        if not priors:
            return []
        # Every day correction counts towards a month's recompute — applied ones were already
        # paid, and leaving them out would reverse them; only pending ones trigger a recompute.
        corrections = await self._adjustment_repo.list_filtered(
            self._session,
            company_id=company_id,
            legal_entity_id=run.legal_entity_id,
            employee_id=employee_id,
        )
        items: list[dict[str, Any]] = []
        for prior, row in sorted(priors, key=lambda pair: pair[0].period_month):
            for_month = [a for a in corrections if a.source_pay_run_id == prior.id]
            adjustments = [a for a in for_month if a.status == "PENDING"]
            changed = await self._changed_since(company_id, employee_id, prior)
            if not adjustments and not changed:
                continue
            spans = [
                (max(joining, prior.period_start), min(last or prior.period_end, prior.period_end))
                for emp, le, joining, last in await EmploymentService(
                    self._session
                ).list_legal_entity_spans(
                    company_id,
                    date_from=prior.period_start,
                    date_to=prior.period_end,
                    employee_id=employee_id,
                )
                if le == run.legal_entity_id and emp == employee_id
            ]
            month_issues: list[dict[str, str]] = []
            segments = await self._segments(
                company_id, employee_id, spans, components, month_issues
            )
            statutory = dict(row.snapshot.get("statutory") or {
                "month_end": prior.period_end.isoformat(), "profile": None, "employee": {},
                "rates": {},
            })  # fmt: skip
            if row.snapshot.get("statutory") is not None:
                profile = await EmployeeStatutoryService(self._session).get_statutory_as_of(
                    company_id,
                    employee_id,
                    max((end for _s, end in spans), default=prior.period_end),
                )
                old_profile = statutory.get("profile") or {}
                statutory["profile"] = (
                    {
                        **old_profile,
                        "is_pf_applicable": profile.is_pf_applicable,
                        "pf_wage_ceiling_opt_out": profile.pf_wage_ceiling_opt_out,
                        "vpf_amount": profile.vpf_amount,
                        "vpf_percentage": (
                            str(profile.vpf_percentage)
                            if profile.vpf_percentage is not None
                            else None
                        ),
                        "is_esi_applicable": profile.is_esi_applicable,
                        "esi_ip_number": profile.esi_ip_number,
                        "is_lwf_applicable": profile.is_lwf_applicable,
                    }
                    if profile is not None
                    else None
                )
            same_salary = self._segment_key(segments) == self._segment_key(
                row.snapshot.get("segments", [])
            ) and statutory.get("profile") == (row.snapshot.get("statutory") or {}).get("profile")
            if not adjustments and same_salary:
                continue
            summary = dict(row.snapshot.get("summary") or {})
            delta = sum((a.paid_days_delta for a in for_month), Decimal(0))
            if summary.get("paid_days") is not None and delta:
                summary["paid_days"] = format(
                    (Decimal(summary["paid_days"]) + delta).normalize(), "f"
                )
            reasons = (["SALARY_CHANGED"] if not same_salary else []) + (
                ["DAYS_CORRECTED"] if adjustments else []
            )
            items.append({
                "month": prior.period_month.strftime("%Y-%m"),
                "pay_run_id": str(prior.id),
                "days_in_month": prior.days_in_month,
                "reasons": reasons,
                "adjustment_ids": [str(a.id) for a in adjustments],
                "snapshot": {
                    **row.snapshot,
                    "summary": summary,
                    "segments": segments,
                    "statutory": statutory,
                    "issues": month_issues,
                    "arrears": [],
                },
                "paid": await self._paid_for(prior, employee_id),
            })  # fmt: skip
        return items

    async def _build_snapshots(
        self,
        run: PayRun,
        inputs: "PayrollPeriodInputs",
        now: datetime,
        *,
        with_arrears: bool = True,
    ) -> list[dict[str, Any]]:
        from hrms.modules.employee.service import EmployeeService, EmploymentService
        from hrms.modules.leave.service import LeaveLedgerService

        company_id = run.company_id
        all_spans = await EmploymentService(self._session).list_legal_entity_spans(
            company_id, date_from=run.period_start, date_to=run.period_end
        )
        spans_by_employee: dict[UUID, list[tuple[UUID, date, date | None]]] = {}
        own_spans: dict[UUID, list[tuple[date, date]]] = {}
        for employee_id, legal_entity_id, joining, last_day in all_spans:
            spans_by_employee.setdefault(employee_id, []).append(
                (legal_entity_id, joining, last_day)
            )
            if legal_entity_id != run.legal_entity_id:
                continue
            start = max(joining, run.period_start)
            end = min(last_day, run.period_end) if last_day is not None else run.period_end
            if start <= end:
                own_spans.setdefault(employee_id, []).append((start, end))
        summaries = {s.employee_id: s for s in inputs.summaries}
        overtime: dict[UUID, list[dict[str, Any]]] = {}
        for employee_id, day_class, multiplier, minutes in inputs.overtime:
            overtime.setdefault(employee_id, []).append(
                {
                    "day_class": day_class,
                    "multiplier": (
                        format(multiplier.normalize(), "f") if multiplier is not None else None
                    ),
                    "minutes": minutes,
                }
            )
        encashments: dict[UUID, list[dict[str, Any]]] = {}
        for entry_id, employee_id, leave_type_id, days, effective in await LeaveLedgerService(
            self._session
        ).list_encashments_between(company_id, run.period_start, run.period_end):
            if _owning_entity(spans_by_employee.get(employee_id, []), effective) != (
                run.legal_entity_id
            ):
                continue
            encashments.setdefault(employee_id, []).append({
                "ledger_entry_id": str(entry_id), "leave_type_id": str(leave_type_id),
                "days": format(days.normalize(), "f"), "effective_date": effective.isoformat(),
            })  # fmt: skip
        components = {
            c.code: c
            for c in await self._component_repo.list_for_company(
                self._session, company_id=company_id
            )
        }

        employees = EmployeeService(self._session)
        rows: list[dict[str, Any]] = []
        for employee_id in sorted(set(own_spans) | set(summaries), key=str):
            issues: list[dict[str, str]] = []
            summary = summaries.get(employee_id)
            if summary is None:
                issues.append(_issue(
                    "NOT_IN_ATTENDANCE",
                    "Employed in this legal entity during the month but missing from the closed "
                    "attendance period's summary",
                ))  # fmt: skip
            segments = await self._segments(
                company_id, employee_id, own_spans.get(employee_id, []), components, issues
            )
            employee = await employees.get_employee(
                company_id, employee_id, scope=None, caller_employee_id=None
            )
            name = employee.display_name or " ".join(
                part for part in (employee.first_name, employee.last_name) if part
            )
            snapshot = {
                "summary": summary.model_dump(mode="json") if summary is not None else None,
                "segments": segments,
                "overtime": overtime.get(employee_id, []),
                "encashments": encashments.get(employee_id, []),
                "bank": await self._bank(company_id, employee_id, run.period_end),
                "statutory": await self._statutory(
                    company_id,
                    employee_id,
                    own_spans.get(employee_id, []),
                    run.period_end,
                    date_of_birth=employee.date_of_birth,
                    gender=employee.gender,
                ),
                "income_tax": await self._income_tax(
                    company_id,
                    run.legal_entity_id,
                    employee_id,
                    own_spans.get(employee_id, []),
                    run.period_end,
                    run.period_month,
                ),
                "arrears": (
                    await self._arrears_for(run, employee_id, components) if with_arrears else []
                ),
                "issues": issues,
            }
            valid = [s for s in segments if s["valid"]]
            rows.append({
                "id": uuid4(),
                "company_id": company_id,
                "pay_run_id": run.id,
                "employee_id": employee_id,
                "employee_code": employee.employee_code,
                "employee_name": name,
                "pay_basis": valid[-1]["pay_basis"] if valid else None,
                "paid_days": Decimal(summary.paid_days) if summary and summary.paid_days else None,
                "lop_days": Decimal(summary.lop_days) if summary else None,
                "payable_days": (
                    Decimal(summary.payable_days) if summary and summary.payable_days else None
                ),
                "snapshot": snapshot,
                "issues": issues,
                "has_error": any(i["severity"] == ERROR for i in issues),
                "created_at": now,
                "updated_at": now,
            })  # fmt: skip
        return rows

    @logged_operation("payroll.pay_run.lock_inputs")
    async def lock_inputs(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        from hrms.modules.attendance.service import AttendancePeriodService

        run = await self._get_row(company_id, run_id)
        self._require_status(run, "DRAFT")
        before = pay_run_to_read(run)
        inputs = await AttendancePeriodService(self._session).closed_period_for_month(
            company_id, run.legal_entity_id, run.period_start, run.period_end
        )
        if inputs is None:
            raise PayRunInputsUnavailableError()
        now = datetime.now(UTC)
        rows = await self._build_snapshots(run, inputs, now)
        updated = await self._transition(
            run,
            values={
                "status": "INPUTS_LOCKED",
                "attendance_period_id": inputs.attendance_period_id,
                "attendance_period_version": inputs.version,
                "inputs_locked_at": now,
                "inputs_locked_by_user_id": actor_user_id,
                "employee_count": len(rows),
                "error_count": sum(1 for r in rows if r["has_error"]),
                "warning_count": 0,
                "last_rollback_reason": None,
                **_RESET_RUN_TOTALS,
            },
            expected_version=expected_version,
            from_statuses=("DRAFT",),
        )
        await self._repo.insert_employees(self._session, rows=rows)
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_INPUTS_LOCKED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    # -- compute ---------------------------------------------------------------------

    @logged_operation("payroll.pay_run.compute")
    async def compute(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        run = await self._get_row(company_id, run_id)
        self._require_status(run, "INPUTS_LOCKED", "COMPUTED")
        before = pay_run_to_read(run)
        threshold = Decimal((await self._settings.get(company_id)).variance_threshold_percent)
        previous = await self._repo.get_previous_finalised(
            self._session,
            company_id=company_id,
            legal_entity_id=run.legal_entity_id,
            before=run.period_month,
        )
        previous_net: dict[UUID, int] = {}
        if previous is not None:
            previous_net = {
                e.employee_id: e.net_minor
                for e in await self._repo.list_employees(
                    self._session, company_id=company_id, run_id=previous.id
                )
            }
        employees = await self._repo.list_employees(
            self._session, company_id=company_id, run_id=run_id
        )

        now = datetime.now(UTC)
        updates: list[tuple[PayRunEmployee, dict[str, Any]]] = []
        line_rows: list[dict[str, Any]] = []
        totals = {"gross": 0, "deductions": 0, "employer": 0, "net": 0}
        errors = warnings = flagged_count = open_count = 0
        for employee in employees:
            result = compute_employee(
                employee_input_from_snapshot(employee.snapshot, run.days_in_month)
            )
            prev = previous_net.get(employee.employee_id)
            percent: Decimal | None = None
            flagged = False
            if prev is not None:
                if prev == 0:
                    flagged = result.net_minor != 0
                else:
                    percent = (Decimal(result.net_minor - prev) / Decimal(prev) * 100).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    flagged = abs(percent) > threshold
            # An acknowledgement survives a recompute only if the net pay it explained is unchanged.
            keep_ack = (
                flagged
                and employee.variance_reason is not None
                and employee.is_computed
                and employee.net_minor == result.net_minor
            )
            values = {
                "is_computed": True,
                "gross_minor": result.gross_minor,
                "deductions_minor": result.deductions_minor,
                "employer_contributions_minor": result.employer_contributions_minor,
                "net_before_rounding_minor": result.net_before_rounding_minor,
                "rounding_minor": result.rounding_minor,
                "net_minor": result.net_minor,
                "issues": [issue.to_dict() for issue in result.issues],
                "has_error": result.has_error,
                "previous_net_minor": prev,
                "variance_percent": percent,
                "variance_flagged": flagged,
                "variance_reason": employee.variance_reason if keep_ack else None,
                "variance_acknowledged_by_user_id": (
                    employee.variance_acknowledged_by_user_id if keep_ack else None
                ),
                "variance_acknowledged_at": employee.variance_acknowledged_at if keep_ack else None,
            }
            updates.append((employee, values))
            line_rows.extend(
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "pay_run_id": run_id,
                    "pay_run_employee_id": employee.id,
                    "employee_id": employee.employee_id,
                    "component_code": line.component_code,
                    "component_name": line.component_name,
                    "line_type": line.line_type,
                    "full_monthly_minor": line.full_monthly_minor,
                    "amount_minor": line.amount_minor,
                    "display_order": line.display_order,
                    "trace": line.trace,
                    "created_at": now,
                }
                for line in result.lines
            )
            totals["gross"] += result.gross_minor
            totals["deductions"] += result.deductions_minor
            totals["employer"] += result.employer_contributions_minor
            totals["net"] += result.net_minor
            errors += int(result.has_error)
            warnings += sum(1 for issue in result.issues if issue.severity == WARNING)
            flagged_count += int(flagged)
            open_count += int(flagged and not keep_ack)

        # The status-guarded run write goes first: if the run moved on, nothing else is written.
        updated = await self._transition(
            run,
            values={
                "status": "COMPUTED",
                "computed_at": now,
                "computed_by_user_id": actor_user_id,
                "approved_at": None,
                "approved_by_user_id": None,
                "variance_threshold_percent": threshold,
                "previous_pay_run_id": previous.id if previous is not None else None,
                "employee_count": len(employees),
                "gross_minor": totals["gross"],
                "deductions_minor": totals["deductions"],
                "employer_contributions_minor": totals["employer"],
                "net_minor": totals["net"],
                "error_count": errors,
                "warning_count": warnings,
                "variance_flag_count": flagged_count,
                "variance_open_count": open_count,
            },
            expected_version=expected_version,
            from_statuses=("INPUTS_LOCKED", "COMPUTED"),
        )
        for employee, values in updates:
            await self._repo.update_employee(
                self._session,
                company_id=company_id,
                run_id=run_id,
                row_id=employee.id,
                values=values,
                now=now,
            )
        await self._repo.replace_lines(
            self._session, company_id=company_id, run_id=run_id, rows=line_rows
        )
        # Phase 5.5 — which month and earlier run each arrears amount belongs to.
        arrear_parts = [
            (line, part)
            for line in line_rows
            if line["component_code"].startswith(ARREARS_PREFIX)
            for part in line["trace"]["parts"]
        ]
        paid_before = await self._arrear_repo.payment_counts(
            self._session,
            company_id=company_id,
            source_run_ids=sorted({UUID(part["pay_run_id"]) for _, part in arrear_parts}, key=str),
        )
        await self._arrear_repo.replace_for_run(
            self._session,
            company_id=company_id,
            run_id=run_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "pay_run_id": run_id,
                    "employee_id": line["employee_id"],
                    "for_month": date.fromisoformat(f"{part['month']}-01"),
                    "source_pay_run_id": UUID(part["pay_run_id"]),
                    "component_code": part["component_code"],
                    "line_type": line["line_type"],
                    "amount_minor": part["amount_minor"],
                    "payment_number": 1
                    + paid_before.get(
                        (line["employee_id"], UUID(part["pay_run_id"]), part["component_code"]), 0
                    ),
                    "created_at": now,
                }
                for line, part in arrear_parts
            ],
        )
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_COMPUTED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    async def acknowledge_variance(
        self,
        company_id: UUID,
        run_id: UUID,
        employee_id: UUID,
        body: PayRunVarianceAcknowledge,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunEmployeeRead:
        """FR-PAY-014 — a flagged change in net pay needs a reason before approval."""
        run = await self._get_row(company_id, run_id)
        self._require_status(run, "COMPUTED")
        row = await self._repo.get_employee(
            self._session, company_id=company_id, run_id=run_id, employee_id=employee_id
        )
        if row is None:
            raise PayRunEmployeeNotFoundError()
        if not row.variance_flagged:
            raise PayRunInvalidTransitionError("This employee's pay has no flagged variance")
        before = pay_run_employee_to_read(row)
        now = datetime.now(UTC)
        was_open = row.variance_reason is None
        updated_row = await self._repo.update_employee(
            self._session,
            company_id=company_id,
            run_id=run_id,
            row_id=row.id,
            values={
                "variance_reason": body.reason,
                "variance_acknowledged_by_user_id": actor_user_id,
                "variance_acknowledged_at": now,
            },
            now=now,
        )
        if updated_row is None:
            raise PayRunInvalidTransitionError("The pay run can no longer change")
        if was_open:
            await self._transition(
                run,
                values={"variance_open_count": max(run.variance_open_count - 1, 0)},
                expected_version=None,
                from_statuses=("COMPUTED",),
            )
        after = pay_run_employee_to_read(updated_row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_PAY_RUN_VARIANCE_ACKNOWLEDGED",
            entity_type="pay_run_employee",
            entity_id=row.id,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after

    # -- approve / finalise / paid ---------------------------------------------------

    @logged_operation("payroll.pay_run.approve")
    async def approve(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        run = await self._get_row(company_id, run_id)
        self._require_status(run, "COMPUTED")
        if actor_user_id is not None and actor_user_id == run.computed_by_user_id:
            raise PayRunMakerCheckerError()
        reasons: list[dict[str, Any]] = []
        if run.error_count:
            reasons.append({"code": "EMPLOYEE_ERRORS", "count": run.error_count,
                            "message": f"{run.error_count} employee(s) have errors"})  # fmt: skip
        if run.variance_open_count:
            reasons.append({
                "code": "VARIANCE_UNACKNOWLEDGED", "count": run.variance_open_count,
                "message": f"{run.variance_open_count} flagged variance(s) need a reason",
            })  # fmt: skip
        if reasons:
            raise PayRunBlockedError("This pay run cannot be approved yet", reasons=reasons)
        await self._assert_attendance_unchanged(run)
        await self._assert_inputs_unchanged(run)
        before = pay_run_to_read(run)
        updated = await self._transition(
            run,
            values={
                "status": "APPROVED",
                "approved_at": datetime.now(UTC),
                "approved_by_user_id": actor_user_id,
            },
            expected_version=expected_version,
            from_statuses=("COMPUTED",),
        )
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_APPROVED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    @logged_operation("payroll.pay_run.finalise")
    async def finalise(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        """Immutable from here (ADR-0005). The attendance period can no longer be reopened
        (decision 15) — later corrections are arrears (Phase 5.5)."""
        run = await self._get_row(company_id, run_id)
        self._require_status(run, "APPROVED")
        # PAY-A01 / PAY-A03 — lock order is payroll-finalise, then attendance-period-close
        # (shared); see `core/db/locks.py`. The first makes finalisations of one legal entity
        # take turns, so the arrears read below includes what a run that finalised first paid.
        # The second keeps the attendance period from being reopened until this run commits.
        # Everything is re-read after the locks: what was read before them may be stale.
        await lock_payroll_finalise(self._session, company_id, run.legal_entity_id)
        await lock_attendance_period_close(self._session, company_id, exclusive=False)
        await self._session.refresh(run)
        self._require_status(run, "APPROVED")
        await self._assert_attendance_unchanged(run)
        before = pay_run_to_read(run)
        # Phase 5.4 — freeze each payslip's header facts and leave balances while the run can
        # still be written; the status-guarded transition below then makes them permanent.
        payslips = PayslipService(self._session)
        now = datetime.now(UTC)
        employees = await self._repo.list_employees(
            self._session, company_id=company_id, run_id=run_id
        )
        # Phase 5.5 — nothing this run pays as arrears may have been paid since its inputs were
        # locked, and each day correction is applied exactly once.
        adjustment_ids: list[UUID] = []
        for employee in employees:
            for item in employee.snapshot.get("arrears", []):
                prior = await self._get_row(company_id, UUID(item["pay_run_id"]))
                if await self._paid_for(prior, employee.employee_id) != item["paid"]:
                    raise PayRunArrearsStaleError()
                adjustment_ids.extend(UUID(a) for a in item.get("adjustment_ids", []))
        # PD-4 — the snapshot is still what the inputs say now. Checked after the arrears so a
        # run overtaken by another's arrears payment reports that, not a generic change.
        await self._assert_inputs_unchanged(run)
        applied = await self._adjustment_repo.mark_applied(
            self._session,
            company_id=company_id,
            adjustment_ids=adjustment_ids,
            pay_run_id=run_id,
            now=now,
        )
        if applied != len(adjustment_ids):
            raise PayRunArrearsStaleError()
        try:
            await self._arrear_repo.mark_applied(
                self._session, company_id=company_id, run_id=run_id, now=now
            )
        except IntegrityError as exc:  # the database guard: this payment was already made
            raise PayRunArrearsStaleError() from exc
        for employee in employees:
            await self._repo.update_employee(
                self._session,
                company_id=company_id,
                run_id=run_id,
                row_id=employee.id,
                values={"payslip_details": await payslips.details(run, employee.employee_id)},
                now=now,
            )
        updated = await self._transition(
            run,
            values={
                "status": "FINALISED",
                "finalised_at": datetime.now(UTC),
                "finalised_by_user_id": actor_user_id,
            },
            expected_version=expected_version,
            from_statuses=("APPROVED",),
        )
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_FINALISED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        # The payslips are visible to employees from this point (`list_final_for_employee`).
        month = updated.period_month.strftime("%B %Y")
        await notify(
            self._session,
            company_id=company_id,
            recipients=await employee_user_ids(
                self._session, company_id, (e.employee_id for e in employees)
            ),
            type=PAYSLIP_AVAILABLE,
            title=f"Your payslip for {month} is ready",
            body="Open it to see your earnings, deductions and net pay.",
            dedupe_key=f"{PAYSLIP_AVAILABLE.code}:{run_id}",
            entity_type="pay_run",
            entity_id=run_id,
            action_url=f"{MY_PAYSLIPS_PATH}/{run_id}",
            action_label="View payslip",
        )
        return after

    @logged_operation("payroll.pay_run.mark_paid")
    async def mark_paid(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        run = await self._get_row(company_id, run_id)
        self._require_status(run, "FINALISED")
        before = pay_run_to_read(run)
        updated = await self._transition(
            run,
            values={
                "status": "PAID",
                "paid_at": datetime.now(UTC),
                "paid_by_user_id": actor_user_id,
            },
            expected_version=expected_version,
            from_statuses=("FINALISED",),
        )
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_PAID",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    # -- rollback --------------------------------------------------------------------

    @logged_operation("payroll.pay_run.rollback")
    async def rollback(
        self,
        company_id: UUID,
        run_id: UUID,
        body: PayRunRollback,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayRunRead:
        run = await self._get_row(company_id, run_id)
        allowed = _ROLLBACK_FROM[body.to_status]
        if run.status not in allowed:
            raise PayRunInvalidTransitionError(
                f"A {run.status} pay run cannot be rolled back to {body.to_status}"
            )
        before = pay_run_to_read(run)
        values: dict[str, Any] = {
            "status": body.to_status,
            "last_rollback_reason": body.reason,
            **_RESET_RUN_TOTALS,
        }
        if body.to_status == "DRAFT":
            values.update(
                attendance_period_id=None,
                attendance_period_version=None,
                inputs_locked_at=None,
                inputs_locked_by_user_id=None,
                employee_count=0,
                error_count=0,
                warning_count=0,
            )
        updated = await self._transition(
            run, values=values, expected_version=expected_version, from_statuses=allowed
        )
        await self._repo.delete_lines(self._session, company_id=company_id, run_id=run_id)
        await self._arrear_repo.delete_for_run(self._session, company_id=company_id, run_id=run_id)
        if body.to_status == "DRAFT":
            await self._repo.delete_employees(self._session, company_id=company_id, run_id=run_id)
        else:
            now = datetime.now(UTC)
            error_count = 0
            for employee in await self._repo.list_employees(
                self._session, company_id=company_id, run_id=run_id
            ):
                snapshot_issues = employee.snapshot.get("issues", [])
                has_error = any(i["severity"] == ERROR for i in snapshot_issues)
                error_count += int(has_error)
                await self._repo.update_employee(
                    self._session,
                    company_id=company_id,
                    run_id=run_id,
                    row_id=employee.id,
                    values={**_RESET_COMPUTED, "issues": snapshot_issues, "has_error": has_error},
                    now=now,
                )
            updated = await self._transition(
                updated,
                values={"error_count": error_count, "warning_count": 0},
                expected_version=None,
                from_statuses=("INPUTS_LOCKED",),
            )
        after = pay_run_to_read(updated)
        await self._record(
            run_id,
            company_id,
            "PAYROLL_PAY_RUN_ROLLED_BACK",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            extra={"rollback_reason": body.reason},
        )
        return after


# ---------------------------------------------------------------------------
# Phase 5.3 — statutory rates
# ---------------------------------------------------------------------------

#: Seeded per company on first use, **unverified** — compliance must check each against the
#: current notifications and verify it before a pay run using it can be approved (FR-PAY-005).
DEFAULT_STATUTORY_RATES: tuple[tuple[str, str | None, date, dict[str, Any], str], ...] = (
    (
        "PF",
        None,
        date(2014, 9, 1),
        {"employee_percent": "12", "employer_percent": "12", "eps_percent": "8.33",
         "wage_ceiling_minor": 1_500_000, "edli_percent": "0.5", "admin_percent": "0.5",
         "eps_age_limit": 58},
        "EPF & MP Act: 12 % / 12 %, EPS 8.33 % on wages up to ₹15,000 (from 1 Sep 2014), EDLI "
        "0.5 %, admin charges 0.5 % (from 1 Jun 2018; the ₹500 monthly establishment minimum is "
        "not applied per employee). Verify before use.",
    ),
    (
        "ESI",
        None,
        date(2019, 7, 1),
        {"employee_percent": "0.75", "employer_percent": "3.25",
         "wage_ceiling_minor": 2_100_000, "employee_exempt_daily_wage_minor": 17_600},
        "ESI Act: employee 0.75 %, employer 3.25 % (from 1 Jul 2019); wage ceiling ₹21,000; no "
        "employee share at an average daily wage up to ₹176. Verify before use.",
    ),
    (
        "PT",
        "MH",
        date(2023, 7, 1),
        {"slabs": [
            {"min_minor": 0, "max_minor": 750_000, "amount_minor": 0},
            {"min_minor": 750_001, "max_minor": 1_000_000, "amount_minor": 17_500},
            {"min_minor": 1_000_001, "max_minor": None, "amount_minor": 20_000,
             "month_amounts": {"2": 30_000}},
            {"min_minor": 0, "max_minor": 2_500_000, "amount_minor": 0, "gender": "FEMALE"},
            {"min_minor": 2_500_001, "max_minor": None, "amount_minor": 20_000,
             "gender": "FEMALE", "month_amounts": {"2": 30_000}},
        ]},
        "Maharashtra: up to ₹7,500 nil, ₹7,501–10,000 ₹175, above ₹10,000 ₹200 (₹300 in "
        "February); women up to ₹25,000 nil. Verify before use.",
    ),
    (
        "PT",
        "KA",
        date(2025, 4, 1),
        {"slabs": [
            {"min_minor": 0, "max_minor": 2_499_999, "amount_minor": 0},
            {"min_minor": 2_500_000, "max_minor": None, "amount_minor": 20_000,
             "month_amounts": {"2": 30_000}},
        ]},
        "Karnataka: below ₹25,000 nil, ₹25,000 and above ₹200 (₹300 in February, from 1 Apr "
        "2025). Verify before use.",
    ),
    (
        "TDS",
        None,
        date(2025, 4, 1),
        {"regime": "NEW", "standard_deduction_minor": 7_500_000,
         "rebate_taxable_income_limit_minor": 120_000_000, "cess_percent": "4",
         "surcharge_warning_income_minor": 500_000_000,
         "slabs": [
             {"min_minor": 0, "max_minor": 40_000_000, "percent": "0"},
             {"min_minor": 40_000_000, "max_minor": 80_000_000, "percent": "5"},
             {"min_minor": 80_000_000, "max_minor": 120_000_000, "percent": "10"},
             {"min_minor": 120_000_000, "max_minor": 160_000_000, "percent": "15"},
             {"min_minor": 160_000_000, "max_minor": 200_000_000, "percent": "20"},
             {"min_minor": 200_000_000, "max_minor": 240_000_000, "percent": "25"},
             {"min_minor": 240_000_000, "max_minor": None, "percent": "30"},
         ]},
        "New tax regime, FY 2025-26 slabs (from 1 Apr 2025): nil to ₹4L, 5% to ₹8L, 10% to ₹12L, "
        "15% to ₹16L, 20% to ₹20L, 25% to ₹24L, 30% above; standard deduction ₹75,000; full "
        "Section 87A rebate at or below ₹12L taxable (no marginal relief); 4% health & education "
        "cess; surcharge above ₹50L is not computed — only flagged. Verify before use.",
    ),
)  # fmt: skip


class StatutoryRateService:
    """Phase 5.3 — the effective-dated statutory rate master (FR-PAY-005, BR-10) and the rates a
    pay run snapshots. Rates are per company so each company records its own compliance sign-off
    (`verify`); any edit clears it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = StatutoryRateRepository()
        self._audit = AuditService()
        self._audit_reader = StatutoryAuditReader()

    async def _ensure_independent_verifier(
        self, company_id: UUID, row: StatutoryRate, verifier_user_id: UUID | None
    ) -> None:
        """Maker-checker on compliance sign-off. The rate row records only who verified, so the
        editors come from `audit_log` (every create/update/verify writes one row in the same
        transaction). Fails closed unless the trail provably explains the row:

        * the verifier must be known;
        * every audited actor needed must be known (no NULL actor on a create/update);
        * the audited history must reconcile with `row.version` (1 + updates + verifies, +1 when
          the rate was closed by a successor rate, which changes `effective_to` unaudited);
        * a rate with no audited create/update is accepted only if it is a seeded default that
          was never edited (the system, not a person, made it).

        The verifier is refused if they authored any create/update since the last verification."""
        if verifier_user_id is None:
            raise StatutoryRateEditorUnverifiableError()
        events = await self._audit_reader.list_rate_events(
            self._session, company_id=company_id, rate_id=row.id
        )
        edit_actions = ("PAYROLL_STATUTORY_RATE_CREATED", "PAYROLL_STATUTORY_RATE_UPDATED")
        edits = [e for e in events if e.action in edit_actions]
        updates = [e for e in edits if e.action == "PAYROLL_STATUTORY_RATE_UPDATED"]
        verifies = [e for e in events if e.action == "PAYROLL_STATUTORY_RATE_VERIFIED"]
        expected = 1 + len(updates) + len(verifies)
        reconciled = row.version == expected or (
            row.effective_to is not None and row.version == expected + 1
        )
        if not reconciled or any(e.actor_user_id is None for e in edits):
            raise StatutoryRateEditorUnverifiableError()
        if not edits and not (row.is_seeded and not updates):
            raise StatutoryRateEditorUnverifiableError()
        since = verifies[-1].occurred_at if verifies else None
        recent = [e for e in edits if since is None or e.occurred_at >= since]
        if any(e.actor_user_id == verifier_user_id for e in recent):
            raise StatutoryRateSelfVerificationError()

    async def ensure_defaults(self, company_id: UUID) -> None:
        existing = {
            (row.scheme, row.state_code)
            for row in await self._repo.list_for_company(self._session, company_id=company_id)
        }
        now = datetime.now(UTC)
        for scheme, state, effective_from, parameters, notes in DEFAULT_STATUTORY_RATES:
            if (scheme, state) in existing:
                continue
            try:
                async with self._session.begin_nested():
                    await self._repo.insert(
                        self._session,
                        data={
                            "id": uuid4(),
                            "company_id": company_id,
                            "scheme": scheme,
                            "state_code": state,
                            "effective_from": effective_from,
                            "parameters": validate_statutory_parameters(scheme, parameters),
                            "notes": notes,
                            "is_seeded": True,
                            "version": 1,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
            except IntegrityError:
                continue  # a concurrent request seeded it first

    async def list_rates(
        self, company_id: UUID, *, scheme: str | None = None
    ) -> list[StatutoryRateRead]:
        await self.ensure_defaults(company_id)
        rows = await self._repo.list_for_company(
            self._session, company_id=company_id, scheme=scheme
        )
        return [statutory_rate_to_read(row) for row in rows]

    async def _get_row(self, company_id: UUID, rate_id: UUID) -> StatutoryRate:
        row = await self._repo.get(self._session, company_id=company_id, rate_id=rate_id)
        if row is None:
            raise StatutoryRateNotFoundError()
        return row

    async def _record(
        self,
        company_id: UUID,
        rate_id: UUID,
        action: str,
        *,
        before: StatutoryRateRead | None,
        after: StatutoryRateRead,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="statutory_rate",
            entity_id=rate_id,
            before=before.model_dump(mode="json") if before is not None else None,
            after=after.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )

    async def create(
        self,
        company_id: UUID,
        body: StatutoryRateCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StatutoryRateRead:
        await self.ensure_defaults(company_id)
        now = datetime.now(UTC)
        current = await self._repo.get_open(
            self._session, company_id=company_id, scheme=body.scheme, state_code=body.state_code
        )
        if current is not None:
            if body.effective_from <= current.effective_from:
                raise StatutoryRateInvalidError(
                    "effective_from must be after the current rate's start "
                    f"({current.effective_from.isoformat()})"
                )
            await self._repo.update(
                self._session,
                company_id=company_id,
                rate_id=current.id,
                values={"effective_to": body.effective_from - timedelta(days=1)},
                expected_version=None,
                now=now,
            )
        rate_id = uuid4()
        try:
            async with self._session.begin_nested():
                row = await self._repo.insert(
                    self._session,
                    data={
                        "id": rate_id,
                        "company_id": company_id,
                        "scheme": body.scheme,
                        "state_code": body.state_code,
                        "effective_from": body.effective_from,
                        "parameters": body.parameters,
                        "notes": body.notes,
                        "is_seeded": False,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError as exc:
            raise StatutoryRateInvalidError(
                "Another rate for this scheme and state already covers effective_from"
            ) from exc
        read = statutory_rate_to_read(row)
        await self._record(
            company_id,
            rate_id,
            "PAYROLL_STATUTORY_RATE_CREATED",
            before=None,
            after=read,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return read

    async def update(
        self,
        company_id: UUID,
        rate_id: UUID,
        body: StatutoryRateUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StatutoryRateRead:
        """Corrects a rate in place. Pay runs keep the copy they snapshotted; the rate needs
        verifying again."""
        row = await self._get_row(company_id, rate_id)
        before = statutory_rate_to_read(row)
        values: dict[str, Any] = {"verified_at": None, "verified_by_user_id": None}
        if body.parameters is not None:
            try:
                values["parameters"] = validate_statutory_parameters(row.scheme, body.parameters)
            except ValueError as exc:
                raise StatutoryRateInvalidError(str(exc), field="parameters") from exc
        if "notes" in body.model_fields_set:
            values["notes"] = body.notes
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            rate_id=rate_id,
            values=values,
            expected_version=expected_version,
            now=datetime.now(UTC),
        )
        if updated is None:
            raise StalePayrollResourceError(
                "This statutory rate has been modified by another request",
                current=before.model_dump(mode="json"),
            )
        after = statutory_rate_to_read(updated)
        await self._record(
            company_id,
            rate_id,
            "PAYROLL_STATUTORY_RATE_UPDATED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    async def verify(
        self,
        company_id: UUID,
        rate_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StatutoryRateRead:
        """Compliance sign-off (FR-PAY-005): the actor confirms the rate matches the law in force
        for its dates."""
        row = await self._get_row(company_id, rate_id)
        await self._ensure_independent_verifier(company_id, row, actor_user_id)
        before = statutory_rate_to_read(row)
        updated = await self._repo.update(
            self._session,
            company_id=company_id,
            rate_id=rate_id,
            values={"verified_at": datetime.now(UTC), "verified_by_user_id": actor_user_id},
            expected_version=expected_version,
            now=datetime.now(UTC),
        )
        if updated is None:
            raise StalePayrollResourceError(
                "This statutory rate has been modified by another request",
                current=before.model_dump(mode="json"),
            )
        after = statutory_rate_to_read(updated)
        await self._record(
            company_id,
            rate_id,
            "PAYROLL_STATUTORY_RATE_VERIFIED",
            before=before,
            after=after,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return after

    async def rates_for(
        self, company_id: UUID, as_of: date, state_code: str | None
    ) -> dict[str, dict[str, Any] | None]:
        """The rates a pay run snapshots for one employee: PF, ESI and TDS in force on `as_of`,
        and PT and LWF for the employee's state."""
        await self.ensure_defaults(company_id)
        rates: dict[str, dict[str, Any] | None] = {}
        for scheme, state in (
            ("PF", None), ("ESI", None), ("TDS", None), ("PT", state_code), ("LWF", state_code)
        ):  # fmt: skip
            row = (
                None
                if scheme in ("PT", "LWF") and not state
                else await self._repo.get_as_of(
                    self._session,
                    company_id=company_id,
                    scheme=scheme,
                    state_code=state,
                    as_of=as_of,
                )
            )
            rates[scheme] = (
                {
                    "id": str(row.id),
                    "state_code": row.state_code,
                    "effective_from": row.effective_from.isoformat(),
                    "parameters": row.parameters,
                    "verified": row.verified_at is not None,
                }
                if row is not None
                else None
            )
        return rates


# ---------------------------------------------------------------------------
# Phase 5.4 — payslips and bank advice
# ---------------------------------------------------------------------------

_FINAL_STATUSES = ("FINALISED", "PAID")
_PAYSLIP_STATUSES = ("COMPUTED", "APPROVED", *_FINAL_STATUSES)


def _csv_cell(value: str) -> str:
    """Neutralises spreadsheet formula injection in a free-text cell."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@") else value


def _arrears_note(trace: dict[str, Any]) -> str:
    """ "Aug 2026: ₹5,000.00; Jul 2026: -₹200.00" — the month-wise breakup of an arrears line."""
    parts = []
    for part in trace.get("parts", []):
        label = date.fromisoformat(f"{part['month']}-01").strftime("%b %Y")
        amount = int(part["amount_minor"])
        sign = "-" if amount < 0 else ""
        parts.append(f"{label}: {sign}₹{abs(amount) // 100:,}.{abs(amount) % 100:02d}")
    return "; ".join(parts)


class PayslipService:
    """FR-PAY-017 — payslips. The figures come from the run's lines and snapshot; the header
    facts (designation, department, joining date, masked PAN, legal entity) and month-end leave
    balances are captured into `payslip_details` when the run is finalised, so a published
    payslip never changes. Employees see only their own, and only from finalised runs; HR can
    preview a computed run's payslips (`is_final` false)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PayRunRepository()
        self._audit = AuditService()

    async def details(self, run: PayRun, employee_id: UUID) -> dict[str, Any]:
        from hrms.modules.employee.service import (
            EmployeeAssignmentService,
            EmployeeService,
            EmploymentService,
        )
        from hrms.modules.leave.service import LeaveLedgerService
        from hrms.modules.organisation.service import OrganisationService

        company_id = run.company_id
        org = OrganisationService(self._session)
        entity = await org.get_legal_entity(company_id, run.legal_entity_id)
        company = await org.get_company_profile(company_id)
        assignment = await EmployeeAssignmentService(self._session).get_assignment_as_of(
            company_id, employee_id, run.period_end
        )
        designation = department = None
        if assignment is not None and assignment.designation_id is not None:
            designation = (await org.get_designation(company_id, assignment.designation_id)).title
        if assignment is not None and assignment.department_id is not None:
            department = (await org.get_department(company_id, assignment.department_id)).name
        employment = await EmploymentService(self._session).get_latest_employment_on_or_before(
            company_id, employee_id, run.period_end
        )
        balances = await LeaveLedgerService(self._session).balances_as_of(
            company_id, employee_id, run.period_end
        )
        return {
            "company_name": company.legal_name or company.name,
            "legal_entity": {
                "name": entity.name,
                "address": entity.registered_address,
                "pan": entity.pan,
                "tan": entity.tan,
            },
            "designation": designation,
            "department": department,
            "date_of_joining": employment.joining_date.isoformat() if employment else None,
            "pan_masked": await EmployeeService(self._session).get_masked_pan(
                company_id, employee_id
            ),
            "leave_balances": [
                {"code": code, "name": name, "balance": format(balance.normalize(), "f")}
                for code, name, balance in balances
            ],
        }

    async def _build(self, run: PayRun, row: PayRunEmployee) -> PayslipRead:
        details = row.payslip_details or await self.details(run, row.employee_id)
        lines = await self._repo.list_lines(
            self._session, company_id=run.company_id, run_id=run.id, employee_id=row.employee_id
        )

        def of(*types: str) -> list[PayslipLineRead]:
            return [
                PayslipLineRead(
                    component_code=line.component_code,
                    component_name=line.component_name,
                    full_monthly_minor=line.full_monthly_minor,
                    amount_minor=line.amount_minor,
                    note=_arrears_note(line.trace)
                    if line.component_code.startswith(ARREARS_PREFIX)
                    else None,
                )
                for line in lines
                if line.line_type in types
            ]

        bank = row.snapshot.get("bank") or {}
        statutory = row.snapshot.get("statutory") or {}
        profile = statutory.get("profile") or {}
        entity = details.get("legal_entity") or {}
        joining = details.get("date_of_joining")
        return PayslipRead(
            pay_run_id=run.id,
            month=run.period_month.strftime("%Y-%m"),
            period_start=run.period_start,
            period_end=run.period_end,
            pay_date=run.pay_date,
            status=run.status,
            is_final=run.status in _FINAL_STATUSES,
            company_name=details.get("company_name"),
            legal_entity_name=entity.get("name"),
            legal_entity_address=entity.get("address"),
            legal_entity_pan=entity.get("pan"),
            legal_entity_tan=entity.get("tan"),
            employee_id=row.employee_id,
            employee_code=row.employee_code,
            employee_name=row.employee_name,
            designation=details.get("designation"),
            department=details.get("department"),
            date_of_joining=date.fromisoformat(joining) if joining else None,
            pan_masked=details.get("pan_masked"),
            uan_number=(statutory.get("employee") or {}).get("uan_number"),
            esi_ip_number=profile.get("esi_ip_number")
            if profile.get("is_esi_applicable")
            else None,
            payment_mode=bank.get("payment_mode"),
            bank_name=bank.get("bank_name"),
            account_last4=bank.get("account_last4"),
            days_in_month=run.days_in_month,
            paid_days=format(row.paid_days.normalize(), "f") if row.paid_days is not None else None,
            lop_days=format(row.lop_days.normalize(), "f") if row.lop_days is not None else None,
            earnings=of("EARNING"),
            deductions=of("DEDUCTION", "ROUNDING"),
            employer_contributions=of("EMPLOYER_CONTRIBUTION"),
            gross_minor=row.gross_minor,
            deductions_minor=row.deductions_minor,
            net_minor=row.net_minor,
            net_in_words=rupees_in_words(row.net_minor),
            leave_balances=[
                PayslipLeaveBalanceRead(**balance) for balance in details.get("leave_balances", [])
            ],
        )

    @logged_operation("payroll.payslip.generate")
    async def get_for_run(self, company_id: UUID, run_id: UUID, employee_id: UUID) -> PayslipRead:
        """HR view (`PAYROLL.RUN_VIEW`) — any computed run; a preview until finalised."""
        run = await self._repo.get(self._session, company_id=company_id, run_id=run_id)
        if run is None:
            raise PayRunNotFoundError()
        if run.status not in _PAYSLIP_STATUSES:
            raise PayRunInvalidTransitionError("Payslips exist once the pay run is computed")
        row = await self._repo.get_employee(
            self._session, company_id=company_id, run_id=run_id, employee_id=employee_id
        )
        if row is None:
            raise PayRunEmployeeNotFoundError()
        return await self._build(run, row)

    async def list_own(
        self, company_id: UUID, employee_id: UUID | None
    ) -> list[PayslipSummaryRead]:
        if employee_id is None:
            return []
        rows = await self._repo.list_final_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [
            PayslipSummaryRead(
                pay_run_id=run.id,
                month=run.period_month.strftime("%Y-%m"),
                legal_entity_id=run.legal_entity_id,
                pay_date=run.pay_date,
                net_minor=employee.net_minor,
                status=run.status,
            )
            for run, employee in rows
        ]

    async def get_own(
        self, company_id: UUID, run_id: UUID, employee_id: UUID | None
    ) -> PayslipRead:
        """Self-service — only the caller's own payslip, only from a finalised run; anything
        else is indistinguishable from not found."""
        run = await self._repo.get(self._session, company_id=company_id, run_id=run_id)
        if employee_id is None or run is None or run.status not in _FINAL_STATUSES:
            raise PayRunNotFoundError("Payslip not found")
        row = await self._repo.get_employee(
            self._session, company_id=company_id, run_id=run_id, employee_id=employee_id
        )
        if row is None:
            raise PayRunNotFoundError("Payslip not found")
        return await self._build(run, row)

    async def bank_advice(
        self,
        company_id: UUID,
        run_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str]:
        """FR-PAY-018 — a generic bank transfer file (CSV) for a finalised run: every employee
        paid by bank transfer with a positive net pay. Built on demand from the encrypted bank
        record the snapshot references and never stored; each download is audited (without
        account numbers). Returns `(filename, csv text)`."""
        import csv
        import io

        from hrms.modules.employee.service import EmployeeBankService
        from hrms.modules.organisation.service import OrganisationService

        run = await self._repo.get(self._session, company_id=company_id, run_id=run_id)
        if run is None:
            raise PayRunNotFoundError()
        if run.status not in _FINAL_STATUSES:
            raise PayRunInvalidTransitionError("The bank advice exists once the run is finalised")
        banks = EmployeeBankService(self._session)
        month_label = run.period_month.strftime("%b %Y")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "Employee code", "Employee name", "Account holder", "Account number", "IFSC",
            "Bank", "Amount", "Narration",
        ])  # fmt: skip
        count = total = skipped = 0
        for row in await self._repo.list_employees(
            self._session, company_id=company_id, run_id=run_id
        ):
            bank = row.snapshot.get("bank") or {}
            if row.net_minor <= 0 or bank.get("payment_mode") != "BANK":
                skipped += int(row.net_minor > 0)
                continue
            record = await banks.get_bank(
                company_id, row.employee_id, UUID(bank["employee_bank_id"])
            )
            writer.writerow([
                _csv_cell(row.employee_code or ""),
                _csv_cell(row.employee_name or ""),
                _csv_cell(record.account_holder_name or row.employee_name or ""),
                record.account_number_enc or "",
                record.ifsc or "",
                _csv_cell(record.bank_name or ""),
                f"{row.net_minor // 100}.{row.net_minor % 100:02d}",
                f"Salary {month_label}",
            ])  # fmt: skip
            count += 1
            total += row.net_minor
        entity = await OrganisationService(self._session).get_legal_entity(
            company_id, run.legal_entity_id
        )
        slug = "".join(ch if ch.isalnum() else "-" for ch in entity.name.lower()).strip("-")
        filename = f"bank-advice-{slug or 'entity'}-{run.period_month.strftime('%Y-%m')}.csv"
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_BANK_ADVICE_DOWNLOADED",
            entity_type="pay_run",
            entity_id=run_id,
            after={"rows": count, "total_minor": total, "not_by_bank_transfer": skipped},
            ip=ip_address,
            user_agent=user_agent,
        )
        return filename, buffer.getvalue()


class PayAdjustmentService:
    """Phase 5.5 / D7 — corrections to a finalised month's paid days. The attendance period stays
    closed; the legal entity's next pay run recomputes that month with the correction and pays
    or recovers the difference as arrears. A pending correction can be withdrawn."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PayAdjustmentRepository()
        self._runs = PayRunRepository()
        self._audit = AuditService()

    async def list_adjustments(
        self,
        company_id: UUID,
        *,
        page: PageParams,
        source_pay_run_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[PayAdjustmentRead], int]:
        rows, total = await self._repo.page_filtered(
            self._session,
            company_id=company_id,
            page=page,
            source_pay_run_id=source_pay_run_id,
            legal_entity_id=legal_entity_id,
            status=status,
        )
        return [pay_adjustment_to_read(row) for row in rows], total

    @logged_operation("payroll.adjustment.create")
    async def create(
        self,
        company_id: UUID,
        body: PayAdjustmentCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PayAdjustmentRead:
        # Each correction is bounded by the sum of the earlier ones (PAY-B04): without this two
        # concurrent corrections could each pass the check and together exceed the payable days.
        await lock_pay_adjustment(
            self._session, company_id, body.source_pay_run_id, body.employee_id
        )
        run = await self._runs.get(
            self._session, company_id=company_id, run_id=body.source_pay_run_id
        )
        if run is None or run.status not in ("FINALISED", "PAID"):
            raise PayAdjustmentInvalidError(
                "Corrections are made against a finalised pay run — before finalising, reopen "
                "the attendance period instead",
                field="source_pay_run_id",
            )
        row = await self._runs.get_employee(
            self._session, company_id=company_id, run_id=run.id, employee_id=body.employee_id
        )
        if row is None or row.paid_days is None or row.payable_days is None:
            raise PayAdjustmentInvalidError(
                "This employee has no paid days in that pay run", field="employee_id"
            )
        earlier = await self._repo.list_filtered(
            self._session,
            company_id=company_id,
            source_pay_run_id=run.id,
            employee_id=body.employee_id,
        )
        corrected = row.paid_days + sum((a.paid_days_delta for a in earlier), Decimal(0))
        result = corrected + body.paid_days_delta
        if result < 0 or result > row.payable_days:
            raise PayAdjustmentInvalidError(
                f"Paid days would become {format(result.normalize(), 'f')}; they must stay "
                f"between 0 and {format(row.payable_days.normalize(), 'f')}"
            )
        now = datetime.now(UTC)
        adjustment = await self._repo.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "legal_entity_id": run.legal_entity_id,
                "employee_id": body.employee_id,
                "for_month": run.period_month,
                "source_pay_run_id": run.id,
                "paid_days_delta": body.paid_days_delta,
                "reason": body.reason,
                "status": "PENDING",
                "created_by_user_id": actor_user_id,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = pay_adjustment_to_read(adjustment)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_PAY_ADJUSTMENT_CREATED",
            entity_type="pay_adjustment",
            entity_id=adjustment.id,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def delete(
        self,
        company_id: UUID,
        adjustment_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        row = await self._repo.get(
            self._session, company_id=company_id, adjustment_id=adjustment_id
        )
        if row is None:
            raise PayAdjustmentNotFoundError()
        before = pay_adjustment_to_read(row)
        if not await self._repo.delete_pending(
            self._session, company_id=company_id, adjustment_id=adjustment_id
        ):
            raise PayAdjustmentInvalidError(
                "An applied correction has been paid and cannot be withdrawn — record an "
                "opposite correction instead",
                field="status",
            )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="PAYROLL_PAY_ADJUSTMENT_DELETED",
            entity_type="pay_adjustment",
            entity_id=adjustment_id,
            before=before.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )

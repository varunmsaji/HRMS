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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import NotFoundError
from hrms.core.rbac.types import DataScope
from hrms.modules.payroll.breakup import (
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
    PayRunAlreadyExistsError,
    PayRunAttendanceChangedError,
    PayRunBlockedError,
    PayRunEmployeeNotFoundError,
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
)
from hrms.modules.payroll.models import (
    PayRun,
    PayRunEmployee,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureLine,
    SalaryStructureVersion,
)
from hrms.modules.payroll.repository import (
    EmployeeSalaryRepository,
    PayrollSettingRepository,
    PayRunRepository,
    SalaryComponentRepository,
    SalaryStructureRepository,
)
from hrms.modules.payroll.schemas import (
    EmployeeSalaryBreakupRead,
    EmployeeSalaryBulkAssign,
    EmployeeSalaryBulkResult,
    EmployeeSalaryBulkSkip,
    EmployeeSalaryCreate,
    EmployeeSalaryRead,
    PayrollSettingRead,
    PayrollSettingUpdate,
    PayRunCreate,
    PayRunEmployeeDetailRead,
    PayRunEmployeeRead,
    PayRunRead,
    PayRunRollback,
    PayRunUpdate,
    PayRunVarianceAcknowledge,
    SalaryBreakupLineRead,
    SalaryBreakupPreviewInput,
    SalaryBreakupRead,
    SalaryComponentCreate,
    SalaryComponentRead,
    SalaryComponentUpdate,
    SalaryStructureCreate,
    SalaryStructureLineInput,
    SalaryStructureRead,
    SalaryStructureUpdate,
    SalaryStructureVersionCreate,
    SalaryStructureVersionPublish,
    SalaryStructureVersionRead,
    employee_salary_to_read,
    pay_run_employee_to_read,
    pay_run_line_to_read,
    pay_run_to_read,
    payroll_setting_to_read,
    salary_component_to_read,
    salary_structure_line_to_read,
    salary_structure_to_read,
    salary_structure_version_to_read,
)
from hrms.shared.business_time import business_today

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
        structure = await self._structure_repo.get(
            self._session, company_id=company_id, structure_id=body.salary_structure_id
        )
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
        legal_entity_id: UUID | None = None,
        status: str | None = None,
    ) -> list[PayRunRead]:
        rows = await self._repo.list_for_company(
            self._session, company_id=company_id, legal_entity_id=legal_entity_id, status=status
        )
        return [pay_run_to_read(row) for row in rows]

    async def list_employees(self, company_id: UUID, run_id: UUID) -> list[PayRunEmployeeRead]:
        await self._get_row(company_id, run_id)
        rows = await self._repo.list_employees(self._session, company_id=company_id, run_id=run_id)
        return [pay_run_employee_to_read(row) for row in rows]

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

    # -- create / edit / delete ------------------------------------------------------

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

    async def _build_snapshots(
        self, run: PayRun, inputs: "PayrollPeriodInputs", now: datetime
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
        await self._assert_attendance_unchanged(run)
        before = pay_run_to_read(run)
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
        return after

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

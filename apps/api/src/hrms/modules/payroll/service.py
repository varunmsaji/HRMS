"""Business logic for the Payroll module — the public interface for other modules.

Phase 5.1 (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`): salary components, salary
structures (draft → publish, effective-dated) and employee salary assignment, plus the CTC
breakup built on the pure `breakup.compute_breakup`.

Defaults (decisions D1/D2) are seeded per company on first use rather than by a migration, so a
new company and an existing one get exactly the same rows from one definition:
the five system components, and — only while the company has no structure at all — two
published structures, `STANDARD` (HRA 40 % of Basic) and `STANDARD_METRO` (HRA 50 %)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
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
from hrms.modules.payroll.exceptions import (
    EmployeeSalaryInvalidError,
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
    SalaryComponent,
    SalaryStructure,
    SalaryStructureLine,
    SalaryStructureVersion,
)
from hrms.modules.payroll.repository import (
    EmployeeSalaryRepository,
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
    salary_component_to_read,
    salary_structure_line_to_read,
    salary_structure_to_read,
    salary_structure_version_to_read,
)
from hrms.shared.business_time import business_today

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

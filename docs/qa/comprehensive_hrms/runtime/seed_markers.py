"""Create the two Batch S tenants through OrganisationService.register_company.

Run only from the QA runtime directory with qa.env sourced. Writes identifiers to
../evidence_schema_2026-10-26/fixtures.json and passwords to fixture-secrets.env.
Does not perform HTTP.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from hrms.core.config.settings import get_settings
from hrms.core.db.session import session_scope
from hrms.modules.employee.schemas import EmployeeCreate
from hrms.modules.employee.service import EmployeeService
from hrms.modules.identity.service import IdentityService
from hrms.core.db.models.identity import Company, Role, User, UserCompany, UserRole
from hrms.modules.organisation.schemas import CompanyRegistrationRequest
from hrms.modules.organisation.service import OrganisationService
from hrms.modules.platform.models import EmailLog
from hrms.seed.plan_catalogue import seed_plan_catalogue

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence_schema_2026-10-26"
SECRETS = Path(__file__).resolve().parent / "fixture-secrets.env"
TOKEN_RE = re.compile(r"/verify-email/([A-Za-z0-9_\-]+)")

TENANTS = (
    {
        "marker": "MARKER-FOUNDRY",
        "name": "QA Foundry MARKER-FOUNDRY",
        "email": "founder.a@example.com",
        "first_name": "MARKER-FOUNDRY",
        "last_name": "Admin",
        "employee_first_name": "MARKER-FOUNDRY",
    },
    {
        "marker": "MARKER-NORTHWIND",
        "name": "QA Northwind MARKER-NORTHWIND",
        "email": "founder.b@example.com",
        "first_name": "MARKER-NORTHWIND",
        "last_name": "Admin",
        "employee_first_name": "MARKER-NORTHWIND",
    },
)


def _assert_target() -> None:
    if (EVIDENCE / "fixtures.json").exists():
        raise SystemExit("fixtures already written; refusing to register again")
    parts = urlsplit(os.environ["DATABASE_URL"])
    if (parts.hostname, parts.port, parts.path) != ("127.0.0.1", 15433, "/hrms_qa_20261026"):
        raise SystemExit("ISOLATION BLOCKED seed database target")
    if os.environ.get("EMAIL_PROVIDER") != "logging":
        raise SystemExit("ISOLATION BLOCKED seed email provider")
    settings = get_settings()
    target = urlsplit(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
    if (target.hostname, target.port, target.path) != ("127.0.0.1", 15433, "/hrms_qa_20261026"):
        raise SystemExit("ISOLATION BLOCKED settings database target")
    if settings.email_provider != "logging":
        raise SystemExit("ISOLATION BLOCKED settings email provider")


def _password() -> str:
    return secrets.token_urlsafe(18) + "a9"


async def _main() -> None:
    _assert_target()
    async with session_scope() as session:
        await seed_plan_catalogue(session)

    passwords: dict[str, str] = {}
    for spec in TENANTS:
        password = _password()
        passwords[spec["email"]] = password
        body = CompanyRegistrationRequest(
            name=spec["name"],
            admin_first_name=spec["first_name"],
            admin_last_name=spec["last_name"],
            admin_email=spec["email"],
            admin_password=password,
        )
        async with session_scope() as session:
            await OrganisationService(session).register_company(
                body, ip_address="127.0.0.1", user_agent="qa-schema-seed"
            )

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(EmailLog.recipient, EmailLog.provider, EmailLog.status, EmailLog.text_body)
            )
        ).all()
        if any(provider != "logging" or status != "LOGGED_ONLY" for _, provider, status, _ in rows):
            raise SystemExit("ISOLATION BLOCKED email log is not logging-only")
        tokens = {}
        for recipient, _provider, _status, text_body in rows:
            match = TOKEN_RE.search(text_body or "")
            if match:
                tokens[recipient] = match.group(1)
        identity = IdentityService(session)
        for spec in TENANTS:
            raw = tokens.get(spec["email"])
            if not raw:
                raise SystemExit(f"SEED BLOCKED verification token missing for {spec['email']}")
            await identity.verify_email(raw)

    employees: dict[str, str | None] = {}
    employee_errors: dict[str, str] = {}
    for spec in TENANTS:
        async with session_scope() as session:
            company = (
                await session.execute(select(Company).where(Company.name == spec["name"]))
            ).scalar_one()
        try:
            async with session_scope(company_id=str(company.id)) as session:
                created = await EmployeeService(session).create_employee(
                    company.id,
                    EmployeeCreate(
                        first_name=spec["employee_first_name"],
                        last_name="Employee",
                    ),
                    actor_user_id=None,
                )
            employees[spec["marker"]] = str(created.id)
        except Exception as exc:  # recorded for the review; no invented row
            employees[spec["marker"]] = None
            employee_errors[spec["marker"]] = type(exc).__name__

    fixtures = []
    async with session_scope() as session:
        companies = (await session.execute(select(Company))).scalars().all()
        for company in companies:
            memberships = (
                await session.execute(
                    select(UserCompany).where(UserCompany.company_id == company.id)
                )
            ).scalars().all()
            rows = []
            for item in memberships:
                user = await session.get(User, item.user_id)
                roles = (
                    await session.execute(
                        select(Role.code)
                        .join(UserRole, UserRole.role_id == Role.id)
                        .where(UserRole.user_company_id == item.id)
                    )
                ).scalars().all()
                rows.append(
                    {
                        "user_id": str(item.user_id),
                        "email": user.email if user is not None else None,
                        "email_verified": user.email_verified_at is not None if user else False,
                        "membership_status": item.status,
                        "roles": list(roles),
                    }
                )
            fixtures.append(
                {
                    "company_id": str(company.id),
                    "company_name": company.name,
                    "company_status": company.status,
                    "memberships": rows,
                }
            )

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    payload = {
        "database": "hrms_qa_20261026",
        "employees": employees,
        "employee_errors": employee_errors,
        "companies": fixtures,
        "emails": [spec["email"] for spec in TENANTS],
    }
    (EVIDENCE / "fixtures.json").write_text(json.dumps(payload, indent=2) + "\n")
    secret_lines = [f"{email}={password}" for email, password in passwords.items()]
    SECRETS.write_text("\n".join(secret_lines) + "\n")
    os.chmod(SECRETS, 0o600)
    print("SEED_OK")
    print(json.dumps({"employees": employees, "employee_errors": employee_errors, "company_count": len(fixtures)}))


if __name__ == "__main__":
    asyncio.run(_main())

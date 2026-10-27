"""Finish Batch S fixtures after registration: verify email, set a known password, create one employee.

Uses IdentityService resend/verify and forgot/reset. Captures the logging sender's stderr in
memory and does not write raw tokens. Does not perform HTTP.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from hrms.core.config.settings import get_settings
from hrms.core.db.models.identity import Company, Role, User, UserCompany, UserRole
from hrms.core.db.session import session_scope
from hrms.modules.employee.schemas import EmployeeCreate
from hrms.modules.employee.service import EmployeeService
from hrms.modules.identity.service import IdentityService
from hrms.modules.platform.models import EmailLog

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence_schema_2026-10-26"
SECRETS = Path(__file__).resolve().parent / "fixture-secrets.env"
TOKEN_RE = re.compile(r"/(?:verify-email|reset-password)/([A-Za-z0-9_\-]+)")

TENANTS = (
    {
        "marker": "MARKER-FOUNDRY",
        "name": "QA Foundry MARKER-FOUNDRY",
        "email": "founder.a@example.com",
    },
    {
        "marker": "MARKER-NORTHWIND",
        "name": "QA Northwind MARKER-NORTHWIND",
        "email": "founder.b@example.com",
    },
)


def _assert_target() -> None:
    if (EVIDENCE / "fixtures.json").exists():
        raise SystemExit("fixtures already written; refusing to create more rows")
    parts = urlsplit(os.environ["DATABASE_URL"])
    if (parts.hostname, parts.port, parts.path) != ("127.0.0.1", 15433, "/hrms_qa_20261026"):
        raise SystemExit("ISOLATION BLOCKED seed database target")
    settings = get_settings()
    if settings.email_provider != "logging":
        raise SystemExit("ISOLATION BLOCKED settings email provider")


def _password() -> str:
    return secrets.token_urlsafe(18) + "a9"


async def _capture(action) -> str:
    buffer = io.StringIO()
    previous = sys.stderr
    sys.stderr = buffer
    try:
        await action()
    finally:
        sys.stderr = previous
    match = TOKEN_RE.search(buffer.getvalue())
    if match is None:
        raise SystemExit("SEED BLOCKED logging sender did not emit a token link")
    return match.group(1)


async def _main() -> None:
    _assert_target()
    passwords: dict[str, str] = {}
    for spec in TENANTS:
        email = spec["email"]

        async def resend(email: str = email) -> None:
            async with session_scope() as session:
                await IdentityService(session).resend_verification_email(email)

        token = await _capture(resend)
        async with session_scope() as session:
            await IdentityService(session).verify_email(token)

        password = _password()

        async def forgot(email: str = email) -> None:
            async with session_scope() as session:
                await IdentityService(session).forgot_password(email)

        reset_token = await _capture(forgot)
        async with session_scope() as session:
            await IdentityService(session).reset_password(reset_token, password)
        passwords[email] = password

    employees: dict[str, str | None] = {}
    employee_errors: dict[str, str] = {}
    for spec in TENANTS:
        async with session_scope() as session:
            company = (
                await session.execute(select(Company).where(Company.name == spec["name"]))
            ).scalar_one()
            admin = (
                await session.execute(select(User).where(User.email == spec["email"]))
            ).scalar_one()
            company_id = company.id
            actor_id = admin.id
        try:
            async with session_scope(company_id=str(company_id)) as session:
                created = await EmployeeService(session).create_employee(
                    company_id,
                    EmployeeCreate(first_name=spec["marker"], last_name="Employee"),
                    actor_user_id=actor_id,
                )
            employees[spec["marker"]] = str(created.id)
        except Exception as exc:  # recorded; no invented row
            employees[spec["marker"]] = None
            employee_errors[spec["marker"]] = f"{type(exc).__name__}: {exc}"

    fixtures = []
    async with session_scope() as session:
        companies = (await session.execute(select(Company).order_by(Company.name))).scalars().all()
        logs = (
            await session.execute(select(EmailLog.provider, EmailLog.status))
        ).all()
        for company in companies:
            memberships = (
                await session.execute(select(UserCompany).where(UserCompany.company_id == company.id))
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
                        "email_verified": bool(user and user.email_verified_at),
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
        "email_log_counts": {},
    }
    for provider, status in logs:
        payload["email_log_counts"][f"{provider}:{status}"] = (
            payload["email_log_counts"].get(f"{provider}:{status}", 0) + 1
        )
    (EVIDENCE / "fixtures.json").write_text(json.dumps(payload, indent=2) + "\n")
    SECRETS.write_text("".join(f"{email}={password}\n" for email, password in passwords.items()))
    os.chmod(SECRETS, 0o600)
    print("SEED_OK")
    print(json.dumps({"employees": employees, "employee_errors": employee_errors, "email_log_counts": payload["email_log_counts"], "companies": fixtures}))


if __name__ == "__main__":
    asyncio.run(_main())

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from hrms.core.db.models.identity import Company, User
from hrms.core.db.session import get_session_factory
from hrms.modules.identity.schemas import CompanySummary, TokenResponseData
from hrms.modules.identity.service import IdentityService

VALID_PASSWORD = "CorrectHorse9"


def _payload(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    body = {
        "name": f"Rollback Co {unique}",
        "admin_first_name": "Priya",
        "admin_last_name": "Sharma",
        "admin_email": f"rollback-{unique}@acme.example",
        "admin_password": VALID_PASSWORD,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_registration_atomicity_rollback_on_late_failure(
    seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force a failure at the very last step (token issuance, after every other insert has
    happened) and prove the entire transaction — Company, User, and everything between —
    rolls back together, not just the failing step.

    Uses a locally-built client with `raise_app_exceptions=False`: the shared `client`
    fixture defaults to re-raising unhandled exceptions into the test (useful for catching
    bugs elsewhere), but that's exactly what this test deliberately triggers — a real
    deployed server (Starlette's `ServerErrorMiddleware`) would catch it and return 500,
    which is the behaviour under test here.
    """
    from entrypoints.api import app

    async def _boom(
        self: IdentityService,
        *,
        user_id: Any,
        company_id: Any,
        companies: list[CompanySummary],
        ip_address: str | None,
        user_agent: str | None,
        audit_action: str,
        token_family_id: Any = None,
        existing_session_id: Any = None,
    ) -> TokenResponseData:
        raise RuntimeError("simulated failure after all prior inserts")

    monkeypatch.setattr(IdentityService, "issue_tokens_for", _boom)

    payload = _payload()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/companies/register", json=payload)
    assert response.status_code == 500

    factory = get_session_factory()
    async with factory() as session:
        companies = (
            (await session.execute(select(Company).where(Company.name == payload["name"])))
            .scalars()
            .all()
        )
        assert companies == [], "Company must not survive a failure later in the transaction"

        users = (
            (
                await session.execute(
                    select(User).where(User.email == payload["admin_email"].lower())
                )
            )
            .scalars()
            .all()
        )
        assert users == [], "User must not survive a failure later in the transaction"

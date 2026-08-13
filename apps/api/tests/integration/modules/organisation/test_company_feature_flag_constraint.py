from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from hrms.core.db.models.identity import Company
from hrms.core.db.session import get_session_factory, session_scope
from hrms.modules.organisation.models import CompanyFeatureFlag


@pytest.fixture
async def company() -> AsyncGenerator[Company, None]:
    now = datetime.now(UTC)
    row = Company(id=uuid4(), name="Feature Flag Test Co", created_at=now, updated_at=now)
    factory = get_session_factory()
    async with factory() as session:
        session.add(row)
        await session.commit()

    yield row

    async with factory() as session:
        await session.execute(
            delete(CompanyFeatureFlag).where(CompanyFeatureFlag.company_id == row.id)
        )
        await session.execute(delete(Company).where(Company.id == row.id))
        await session.commit()


@pytest.mark.asyncio
async def test_company_feature_flag_creation(company: Company) -> None:
    now = datetime.now(UTC)

    async with session_scope(company_id=str(company.id)) as session:
        session.add(
            CompanyFeatureFlag(
                id=uuid4(),
                company_id=company.id,
                feature_code="ADVANCED_REPORTING",
                is_enabled=True,
                created_at=now,
                updated_at=now,
            )
        )

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('app.company_id', :cid, true)"), {"cid": str(company.id)}
        )
        row = (
            await session.execute(
                select(CompanyFeatureFlag).where(CompanyFeatureFlag.company_id == company.id)
            )
        ).scalar_one()
        assert row.feature_code == "ADVANCED_REPORTING"
        assert row.is_enabled is True
        assert row.overrides_plan is False
        assert row.version == 1


@pytest.mark.asyncio
async def test_company_feature_flag_duplicate_code_rejected(company: Company) -> None:
    now = datetime.now(UTC)

    async with session_scope(company_id=str(company.id)) as session:
        session.add(
            CompanyFeatureFlag(
                id=uuid4(),
                company_id=company.id,
                feature_code="ADVANCED_REPORTING",
                created_at=now,
                updated_at=now,
            )
        )

    with pytest.raises(IntegrityError):
        async with session_scope(company_id=str(company.id)) as session:
            session.add(
                CompanyFeatureFlag(
                    id=uuid4(),
                    company_id=company.id,
                    feature_code="ADVANCED_REPORTING",
                    created_at=now,
                    updated_at=now,
                )
            )


@pytest.mark.asyncio
async def test_company_feature_flag_invalid_company_fk_rejected() -> None:
    now = datetime.now(UTC)
    bogus_company_id = uuid4()

    with pytest.raises(IntegrityError):
        async with session_scope(company_id=str(bogus_company_id)) as session:
            session.add(
                CompanyFeatureFlag(
                    id=uuid4(),
                    company_id=bogus_company_id,
                    feature_code="ADVANCED_REPORTING",
                    created_at=now,
                    updated_at=now,
                )
            )


@pytest.mark.asyncio
async def test_company_feature_flag_rls_policy_configured() -> None:
    """Verifies RLS is enabled/forced with the standard tenant policy via the catalog.

    Not a session-level behavioural test: the `hrms` role used by this test suite is a
    superuser with `rolbypassrls = true` (pre-existing environment configuration, not
    introduced by this task), so RLS is transparently bypassed for any query issued by
    this connection regardless of `FORCE ROW LEVEL SECURITY`. A catalog check is the
    only assertion that is actually meaningful under that role.
    """
    factory = get_session_factory()
    async with factory() as session:
        relrowsecurity, relforcerowsecurity = (
            await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'company_feature_flag'"
                )
            )
        ).one()
        assert relrowsecurity is True
        assert relforcerowsecurity is True

        policy_qual = (
            await session.execute(
                text(
                    "SELECT qual FROM pg_policies "
                    "WHERE tablename = 'company_feature_flag' AND policyname = 'tenant_isolation'"
                )
            )
        ).scalar_one()
        assert policy_qual == "(company_id = (current_setting('app.company_id'::text, true))::uuid)"

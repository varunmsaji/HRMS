"""Read-only dump of the system roles and their (permission, data_scope) grants for a freshly registered synthetic tenant."""
import json, os
from pathlib import Path
import pytest
from sqlalchemy import text
from tests.integration.modules.attendance.test_employee_default_role_attendance import _tenant, _teardown
from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio

async def test_dump_roles(client, seeded_plan_catalogue):
    t = await _tenant(client)
    try:
        async with get_session_factory()() as s:
            rows = (await s.execute(text("SELECT r.code role, r.is_system, p.code perm, rp.data_scope scope FROM role r JOIN role_permission rp ON rp.role_id = r.id JOIN permission p ON p.id = rp.permission_id WHERE r.company_id = :c ORDER BY 1,3"), {"c": str(t.company_id)})).mappings().all()
            allp = (await s.execute(text("SELECT code FROM permission ORDER BY 1"))).scalars().all()
        out = {"grants": [dict(r) for r in rows], "all_permissions": list(allp)}
        Path(os.environ["QA_ARTIFACTS"], "role_grants.json").write_text(json.dumps(out, indent=1))
    finally:
        await _teardown(t)

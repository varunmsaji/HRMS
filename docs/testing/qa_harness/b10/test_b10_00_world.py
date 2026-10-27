"""World smoke test: builds the fixture and records every principal's effective permissions and scopes (evidence for the role matrix)."""
import json
import pytest
from world import build_world, drop_world, perms_of, scopes_of, rec, seed_attendance

pytestmark = pytest.mark.asyncio


async def test_world_builds_and_roles_resolve(client, seeded_plan_catalogue, monkeypatch):
    w = await build_world(client)
    try:
        out = {}
        for who in ("M1", "M2", "BX", "BY", "E1", "E2", "E3", "HR", "ADMIN", "PAY", "CUSTV", "CUSTS", "B_ADMIN"):
            sc = await scopes_of(w, who)
            out[who] = {"n_permissions": len(sc), "scopes": sorted({s for v in sc.values() for s in v}), "has": sorted(sc)[:80]}
        rec("B10-WORLD", "principals", principals=out)
        me = {who: (await client.get("/v1/auth/me", headers=w.h(who))).status_code for who in w.people}
        rec("B10-WORLD", "login works for every principal", me=me)
        assert all(v == 200 for v in me.values()), me
        assert out["M1"]["scopes"] == ["REPORTEE_TREE", "SELF"] or "REPORTEE_TREE" in out["M1"]["scopes"]
        assert "BRANCH" in out["BX"]["scopes"] and "COMPANY" in out["HR"]["scopes"]
        seeded = await seed_attendance(client, w)
        rec("B10-WORLD", "attendance seeded", **seeded)
    finally:
        await drop_world(w, monkeypatch)

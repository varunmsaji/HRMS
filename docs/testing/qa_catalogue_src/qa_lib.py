"""Shared helper for the QA catalogue generator. Cases are authored as Python calls to C()."""
CASES = []
_D = {}


def defaults(**kw):
    """Set per-area defaults (applied to subsequent C() calls until changed)."""
    _D.clear()
    _D.update(kw)


def C(id, feature, req, exp, steps, *, module=None, src="", type=None, pri=None, pre=None, role=None,
      data=None, inv="", neg="", auto=None, live=(), tests=(), defect="", amb="", env=None,
      risk="", status=None, actual="", evidence="", inherited=None):
    d = dict(_D)
    row = dict(
        case_id=id, module=module or d.get("module", ""), feature=feature, requirement=req,
        rule_source=src or d.get("src", ""), test_type=type or d.get("type", "API-E2E"),
        priority=pri or d.get("pri", "P1"), preconditions=pre or d.get("pre", ""),
        role_tenant=role or d.get("role", ""), test_data=data or d.get("data", ""),
        steps=steps, expected=exp, actual=actual, db_invariants=inv, negative_assertions=neg,
        status=status or d.get("status", "NOT_RUN"), automation=auto or d.get("auto", "NOT_AUTOMATED"), evidence=evidence,
        defect_ref=defect, ambiguity=amb, env_required=env or d.get("env", "PRIVATE_STACK"),
        shared_resource_risk=risk, live_checks=";".join(live), test_globs=";".join(tests),
    )
    assert id not in {c["case_id"] for c in CASES}, f"duplicate case id {id}"
    CASES.append(row)

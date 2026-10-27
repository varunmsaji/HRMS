"""Read-only: authorization inventory of every route (no DB, no network).  For each operation: the permission code, whether the DataScope
returned by the permission dependency is actually bound to a handler parameter that is not an ignored '_...' name, and which other
dependencies guard it."""
import inspect, json, sys
from fastapi.routing import APIRoute
from hrms.app import create_app

app = create_app()
rows = []
def walk(dep, acc):
    for d in dep.dependencies:
        walk(d, acc)
    call = d_call = dep.call
    if call is not None:
        fn = call
        cl = getattr(fn, "__closure__", None)
        if cl and getattr(fn, "__name__", "") == "dependency" and getattr(fn, "__qualname__", "").startswith("require_permission"):
            for c in cl:
                try:
                    v = c.cell_contents
                except ValueError:
                    continue
                if isinstance(v, str):
                    acc["perm"].append(v)
        name = getattr(fn, "__qualname__", str(fn))
        if "get_current_platform_admin" in name: acc["platform"] = True
        if "get_current_user" in name: acc["auth"] = True
        if "require_idempotency_key" in name: acc["idem"] = True
def all_routes(rs, prefix=""):
    for r in rs:
        if isinstance(r, APIRoute):
            yield prefix, r
        elif type(r).__name__ == "_IncludedRouter":
            ic = r.include_context
            yield from all_routes(r.original_router.routes, prefix + (ic.prefix or ""))
for prefix, r in all_routes(app.routes):
    acc = {"perm": [], "platform": False, "auth": False, "idem": False}
    walk(r.dependant, acc)
    # parameter names bound to a require_permission dependency
    scope_params = []
    for d in r.dependant.dependencies:
        if d.call is not None and getattr(d.call, "__qualname__", "").startswith("require_permission") and d.name:
            scope_params.append(d.name)
    for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
        rows.append({"method": m, "path": prefix + r.path, "perm": sorted(set(acc["perm"])), "scope_param": scope_params, "scope_used": any(not p.startswith("_") for p in scope_params),
                     "platform": acc["platform"], "auth": acc["auth"] or bool(acc["perm"]) or acc["platform"], "idempotency": acc["idem"], "tags": list(r.tags or [])})
json.dump(rows, open("/artifacts/route_authz_inventory.json", "w"), indent=1)
print("operations", len(rows), "with permission", sum(1 for r in rows if r["perm"]), "authenticated-only (no permission)", sum(1 for r in rows if r["auth"] and not r["perm"] and not r["platform"]),
      "platform", sum(1 for r in rows if r["platform"]), "public", sum(1 for r in rows if not r["auth"]))

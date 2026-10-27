"""Read-only: list OpenAPI routes (no DB, no network)."""
from hrms.app import create_app
a = create_app()
spec = a.openapi()
n = 0
for p, ops in sorted(spec["paths"].items()):
    for m, op in ops.items():
        if m in ("get", "post", "put", "patch", "delete"):
            n += 1
            print(m.upper(), p, "SEC" if op.get("security") else "nosec")
print("TOTAL", n)

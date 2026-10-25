#!/usr/bin/env python3
"""Regenerates the machine-derived parts of docs/api from the live FastAPI application.

Run from the repository root with the API virtualenv (no database or Redis is needed - the app is
only imported and `app.openapi()` is called, nothing is served):

    apps/api/.venv/bin/python -I docs/api/tools/build_api_docs.py

Writes:
    docs/api/openapi.json                  enriched OpenAPI 3.1 document (x-hrms-* extensions)
    docs/api/ENDPOINT_INVENTORY.md         master registry of every route
    docs/api/modules/<module>.md           per-endpoint reference
    docs/api/models/<module>.md            data dictionary per module
    docs/api/ERROR_CODES.md                every AppError subclass (code, status, module)
    docs/api/PERMISSIONS.md                permission catalogue + which routes use each code
    docs/api/postman/*.json                Postman collection + environment template

Nothing here is hand-edited; the narrative documents (AUTHENTICATION.md etc.) are written by hand.
Examples are derived from the OpenAPI schemas and are labelled as such - they are NOT recordings of
real server responses.
"""

from __future__ import annotations

import collections
import copy
import importlib
import inspect
import json
import pkgutil
import re
import sys
from pathlib import Path

import os

# Importing the app only builds the route table; force a safe, secret-free configuration so the
# generator never depends on (or reads) a developer's real environment.
for _k, _v in {"ENVIRONMENT": "development", "EMAIL_PROVIDER": "logging", "LOG_TO_FILES": "false",
               "FACE_VERIFICATION_PROVIDER": "disabled", "COMPANY_APPROVAL_REQUIRED": "true"}.items():
    os.environ[_k] = _v

ROOT = Path(__file__).resolve().parents[3]
API_SRC = ROOT / "apps" / "api" / "src"
OUT = ROOT / "docs" / "api"
sys.path.insert(0, str(API_SRC))

from fastapi.routing import APIRoute  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import hrms  # noqa: E402
from hrms.app import create_app  # noqa: E402
from hrms.core.errors.base import AppError  # noqa: E402

app = create_app()
OPENAPI = app.openapi()
SCHEMAS = OPENAPI["components"]["schemas"]

# --------------------------------------------------------------------------------------------
# 1. Route introspection
# --------------------------------------------------------------------------------------------


def _closure(fn):
    out = {}
    if getattr(fn, "__closure__", None):
        for n, c in zip(fn.__code__.co_freevars, fn.__closure__):
            try:
                out[n] = c.cell_contents
            except ValueError:
                pass
    return out


def _walk(dep, acc, seen):
    for d in dep.dependencies:
        if d.call is None or id(d) in seen:
            continue
        seen.add(id(d))
        acc.append(d.call)
        _walk(d, acc, seen)


PERM_CONSTS: dict[str, str] = {}
PERMISSIONS: list[dict] = []
for mod in pkgutil.iter_modules(hrms.modules.__path__):
    try:
        pm = importlib.import_module(f"hrms.modules.{mod.name}.permissions")
    except ModuleNotFoundError:
        continue
    for n, v in vars(pm).items():
        if n.isupper() and isinstance(v, str) and "." in v and v.upper() == v:
            PERM_CONSTS[n] = v
        if isinstance(v, (list, tuple)) and v and isinstance(v[0], tuple) and len(v[0]) == 3:
            for code, group, desc in v:
                if isinstance(code, str):
                    PERMISSIONS.append({"code": code, "group": group, "desc": desc, "module": mod.name})
PERM_CODES = {p["code"] for p in PERMISSIONS} | set(PERM_CONSTS.values())


def _helper_sources(fn) -> str:
    """Source of the handler plus any same-module `_helper(` functions it calls (one level)."""
    try:
        src = inspect.getsource(fn)
    except OSError:
        return ""
    mod = inspect.getmodule(fn)
    extra = ""
    for name in set(re.findall(r"\b(_[a-z_]+)\(", src)):
        h = getattr(mod, name, None)
        if inspect.isfunction(h) and h.__module__ == mod.__name__:
            try:
                extra += inspect.getsource(h)
            except OSError:
                pass
    return src + extra


ROUTES: list[dict] = []
for ir in app.routes:
    orig = getattr(ir, "original_router", None)
    if orig is None:
        items = [(ir, "")] if isinstance(ir, APIRoute) else []
    else:
        pre = ir.include_context.prefix
        items = [(r, pre) for r in orig.routes if isinstance(r, APIRoute)]
    for r, pre in items:
        calls: list = []
        _walk(r.dependant, calls, set())
        quals = [getattr(c, "__qualname__", "") for c in calls]
        static_perms = []
        for c in calls:
            if getattr(c, "__qualname__", "").startswith("require_permission."):
                static_perms.append(_closure(c).get("code"))
        rate = []
        for c in calls:
            q = getattr(c, "__qualname__", "")
            if q.startswith(("rate_limit.", "rate_limit_by_ip_and_email.")):
                cv = _closure(c)
                rate.append(f"{cv.get('bucket')}: {cv.get('limit')}/{cv.get('window_seconds')}s"
                            + (" per IP+email" if "by_ip_and_email" in q else " per IP"))
            elif q.startswith("face_request_rate_limit."):
                cv = _closure(c)
                rate.append(f"{cv.get('bucket')}: setting `{cv.get('setting_name')}` per tenant+IP per 60s")
        src = _helper_sources(r.endpoint)
        inhandler = sorted({PERM_CONSTS[n] for n in re.findall(r"\b([A-Z][A-Z_]+)\b", src)
                            if n in PERM_CONSTS} - set(static_perms))
        platform = any(q == "get_current_platform_admin" for q in quals)
        tenant_auth = any(q == "get_current_user" for q in quals)
        public_token = any(q == "get_onboarding_case_from_token" for q in quals)
        try:
            srcfile = Path(inspect.getsourcefile(r.endpoint)).resolve().relative_to(ROOT)
            line = inspect.getsourcelines(r.endpoint)[1]
        except Exception:
            srcfile, line = None, None
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            ROUTES.append({
                "method": m, "path": pre + r.path, "name": r.name, "tags": r.tags,
                "status": r.status_code, "static_perms": static_perms, "inhandler_perms": inhandler,
                "rate": rate, "platform": platform, "tenant_auth": tenant_auth,
                "public_token": public_token, "idem": "require_idempotency_key" in quals,
                "src": str(srcfile) if srcfile else None, "line": line,
                "doc": inspect.getdoc(r.endpoint) or "",
                "module": (str(srcfile).split("/")[5] if srcfile and "modules" in str(srcfile) else "core"),
            })

ROUTES.sort(key=lambda r: (r["module"], r["path"], r["method"]))
OPS = {(r["method"], r["path"]): OPENAPI["paths"][r["path"]][r["method"].lower()] for r in ROUTES
       if r["path"] in OPENAPI["paths"] and r["method"].lower() in OPENAPI["paths"][r["path"]]}
MISSING_FROM_OPENAPI = [(r["method"], r["path"]) for r in ROUTES if (r["method"], r["path"]) not in OPS]
EXTRA_IN_OPENAPI = [
    (m.upper(), p) for p, o in OPENAPI["paths"].items() for m in o
    if m.upper() not in {"PARAMETERS"} and not any(r["method"] == m.upper() and r["path"] == p for r in ROUTES)
]
assert not MISSING_FROM_OPENAPI and not EXTRA_IN_OPENAPI, (MISSING_FROM_OPENAPI, EXTRA_IN_OPENAPI)

# --------------------------------------------------------------------------------------------
# 2. Tests and Flutter-app cross references (heuristic, textual)
# --------------------------------------------------------------------------------------------


def _norm(p: str) -> str:
    p = re.sub(r"\{[^{}]*\}", "{}", p)
    p = re.sub(r"\$\{[^{}]*\}|\$[A-Za-z_][A-Za-z0-9_]*", "{}", p)
    p = p.split("?")[0].rstrip("/")
    return re.sub(r"^/v1", "", p) or "/"


def _matches(template: str, literal: str) -> bool:
    a, b = template.strip("/").split("/"), literal.strip("/").split("/")
    return len(a) == len(b) and all(x == y or x == "{}" or y == "{}" for x, y in zip(a, b))


TEST_DIR = ROOT / "apps" / "api" / "tests"
test_direct: dict[tuple[str, str], set[str]] = collections.defaultdict(set)  # (METHOD, path) -> files
test_paths: dict[str, set[str]] = collections.defaultdict(set)
call_re = re.compile(r"\.(get|post|put|patch|delete|request)\(\s*(?:\"(?:(?:GET|POST|PUT|PATCH|DELETE)\",\s*)?)?", re.S)
lit_re = re.compile(r"""f?(?:"(/(?:v1/)?[A-Za-z0-9_\-/{}\[\]'.()$ ,:=]*?)"|'(/(?:v1/)?[A-Za-z0-9_\-/{}.()$ ,:=]*?)')""")
for f in sorted(TEST_DIR.rglob("*.py")):
    txt = f.read_text(errors="ignore")
    rel = str(f.relative_to(ROOT))
    for m in re.finditer(r"""\.(get|post|put|patch|delete)\(\s*f?(["'])(/[^"'\n]*?)\2""", txt):
        test_direct[(m.group(1).upper(), _norm(m.group(3)))].add(rel)
    for m in re.finditer(r"""\.request\(\s*(["'])([A-Z]+)\1\s*,\s*f?(["'])(/[^"'\n]*?)\3""", txt):
        test_direct[(m.group(2), _norm(m.group(4)))].add(rel)
    for m in re.finditer(r"""f?"(/v1/[^"\s]*)\"""", txt):
        test_paths[_norm(m.group(1))].add(rel)


def test_refs(method: str, path: str) -> tuple[str, list[str]]:
    n = _norm(path)
    direct = sorted({f for (mm, pp), fs in test_direct.items() if mm == method and _matches(n, pp) for f in fs})
    if direct:
        return "direct", direct
    ref = sorted({f for pp, fs in test_paths.items() if _matches(n, pp) for f in fs})
    return ("path-only", ref) if ref else ("none", [])


MOBILE_DIR = ROOT / "apps" / "mobile" / "lib"
mobile_lits: dict[str, set[str]] = collections.defaultdict(set)
for f in sorted(MOBILE_DIR.rglob("*.dart")):
    txt = f.read_text(errors="ignore")
    rel = str(f.relative_to(ROOT))
    for m in re.finditer(r"""['"](/[A-Za-z0-9_\-/${}.]+)""", txt):
        lit = _norm(m.group(1))
        if lit not in ("/", ""):
            mobile_lits[lit].add(rel)


def mobile_refs(path: str) -> list[str]:
    n = _norm(path)
    return sorted({f for lit, fs in mobile_lits.items() if _matches(n, lit) for f in fs})


# --------------------------------------------------------------------------------------------
# 3. Classification
# --------------------------------------------------------------------------------------------

SELF_ANY = {"LEAVE.APPLICATION_SUBMIT", "LEAVE.BALANCE_VIEW", "ATTENDANCE.REGULARIZATION_REQUEST", "ATTENDANCE.PUNCH", "PAYROLL.PAYSLIP_VIEW_OWN"}
SELF_CODES = {"ATTENDANCE.PUNCH", "ATTENDANCE.VIEW", "PAYROLL.PAYSLIP_VIEW_OWN", "EMPLOYEE.VIEW"}
APPROVE_HINT = ("APPROVE", "REASSIGN", "REVIEW", "ACTIVATE", "PUNCH_ON_BEHALF", "VIEW_ALL", "RUN_VIEW")


def auth_kind(r) -> str:
    if r["platform"]:
        return "Platform-admin Bearer"
    if r["public_token"]:
        return "Public (secret token in path)"
    if r["tenant_auth"] or r["static_perms"]:
        return "Tenant Bearer"
    return "Public"


def mobile_tier(r) -> tuple[str, str]:
    p = r["path"]
    if r["platform"] or p.startswith("/v1/platform"):
        return "X", "No - platform console (separate super-admin token)"
    if p.startswith("/health"):
        return "X", "No - infrastructure probe"
    if auth_kind(r) in ("Public", "Public (secret token in path)"):
        return "A", "Yes - pre-login / public"
    perms = set(r["static_perms"]) | set(r["inhandler_perms"])
    if not perms or p.startswith("/v1/auth"):
        return "A", "Yes - any signed-in user (self-service)"
    if perms & SELF_ANY:
        return "A", "Yes - employee self-service (data-scope limited; on-behalf variants need COMPANY scope)"
    if any(c.endswith((".MANAGE",)) or c in {"ATTENDANCE.LOCK", "ATTENDANCE.UNLOCK", "ATTENDANCE.RECOMPUTE",
           "ATTENDANCE.LEAVE_PROJECTION_SYNC", "EMPLOYEE.BULK_IMPORT"} or c.startswith(
           ("PAYROLL.SETUP", "PAYROLL.STATUTORY", "PAYROLL.RUN_PROCESS", "PAYROLL.RUN_APPROVE")) for c in perms):
        return "C", "Admin / back-office configuration (permission-gated)"
    if all(c in SELF_CODES or c.endswith(("SUBMIT", "BALANCE_VIEW", "REGULARIZATION_REQUEST",
                                           "BALANCE_VIEW_ALL")) for c in perms) and not any(h in " ".join(perms) for h in APPROVE_HINT[:5]):
        return "A", "Yes - employee self-service (data-scope limited)"
    return "B", "Manager / HR workflow (permission-gated)"


# --------------------------------------------------------------------------------------------
# 4. Schema rendering helpers
# --------------------------------------------------------------------------------------------

SAMPLE_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
UUID_POOL = [
    "3fa85f64-5717-4562-b3fc-2c963f66afa6", "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "b3f1c2d4-8a6e-4c1b-9d52-0e7a4f5b6c10", "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
]


def ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def resolve(s):
    while isinstance(s, dict) and "$ref" in s:
        s = SCHEMAS[ref_name(s["$ref"])]
    return s


def non_null(s):
    """Strip `anyOf: [X, null]` -> (X, nullable)."""
    if isinstance(s, dict) and "anyOf" in s:
        opts = [o for o in s["anyOf"] if o.get("type") != "null"]
        nullable = len(opts) != len(s["anyOf"])
        if len(opts) == 1:
            merged = dict(opts[0])
            for k in ("description", "default", "title"):
                if k in s and k not in merged:
                    merged[k] = s[k]
            return merged, nullable
        return {"anyOf": opts, **{k: v for k, v in s.items() if k != "anyOf"}}, nullable
    return s, False


def type_str(s, link_prefix: str = "") -> str:
    s, _ = non_null(s)
    if "$ref" in s:
        n = ref_name(s["$ref"])
        if n in ENUM_LOOKUP:
            return "enum " + "/".join(f"`{v}`" for v in ENUM_LOOKUP[n])
        if n not in MODEL_MODULE:
            return f"`{n}`"
        owner = MODEL_MODULE[n]
        if link_prefix:  # called from modules/<x>.md
            href = f"../models/{owner}.md#{anchor(n)}"
        else:  # called from models/<x>.md
            href = f"#{anchor(n)}" if owner == CUR_MODEL[0] else f"{owner}.md#{anchor(n)}"
        return f"[{n}]({href})"
    if "enum" in s:
        return "enum " + "/".join(f"`{v}`" for v in s["enum"])
    if "const" in s:
        return f"const `{s['const']}`"
    if "anyOf" in s or "oneOf" in s:
        return " \\| ".join(type_str(o, link_prefix) for o in s.get("anyOf", s.get("oneOf")))
    t = s.get("type")
    if t == "array":
        return f"array&lt;{type_str(s.get('items', {}), link_prefix)}&gt;"
    if t == "string":
        fmt = s.get("format")
        if "pattern" in s and "\\d*\\.?\\d*" in s["pattern"]:
            return "decimal (JSON **string**)"
        return f"string({fmt})" if fmt else "string"
    if t == "object":
        ap = s.get("additionalProperties")
        if isinstance(ap, dict) and ap:
            return f"map&lt;string, {type_str(ap, link_prefix)}&gt;"
        return "object"
    if t == "number" and "format" not in s:
        return "number"
    return t or "any"


def constraints(s) -> str:
    s, _ = non_null(s)
    out = []
    for k, label in (("minLength", "minLength"), ("maxLength", "maxLength"), ("minimum", "min"), ("maximum", "max"),
                     ("exclusiveMinimum", ">"), ("exclusiveMaximum", "<"), ("minItems", "minItems"),
                     ("maxItems", "maxItems"), ("multipleOf", "multipleOf")):
        if k in s:
            out.append(f"{label}={s[k]}")
    if "pattern" in s and "\\d*\\.?\\d*" not in s["pattern"]:
        out.append(f"pattern=`{s['pattern']}`")
    return ", ".join(out)


def anchor(name: str) -> str:
    return name.lower()


CUR_MODEL = [None]
ENUM_LOOKUP: dict[str, list] = {n: s["enum"] for n, s in SCHEMAS.items() if "enum" in s and "properties" not in s}

# schema name -> owning module (for linking)
MODEL_MODULE: dict[str, str] = {}
CLASS_BY_NAME: dict[str, type] = {}
def _all_module_names():
    # Filesystem walk: several packages (e.g. modules/identity) have no __init__.py, which
    # pkgutil.walk_packages silently skips.
    for f in sorted((API_SRC / "hrms").rglob("*.py")):
        if f.name == "__init__.py" or "__pycache__" in f.parts:
            continue
        yield ".".join(f.relative_to(API_SRC).with_suffix("").parts)


for _name in _all_module_names():
    try:
        mod = importlib.import_module(_name)
    except Exception:
        continue
    for n, v in vars(mod).items():
        if inspect.isclass(v) and issubclass(v, BaseModel) and v.__module__ == mod.__name__ and n in SCHEMAS:
            parts = mod.__name__.split(".")
            owner = parts[2] if len(parts) > 2 and parts[1] == "modules" else ("shared" if parts[1] == "shared" else parts[1])
            MODEL_MODULE.setdefault(n, owner)
for n in SCHEMAS:
    if n not in MODEL_MODULE:
        MODEL_MODULE[n] = "shared"
for n in list(SCHEMAS):
    if n.startswith(("DataEnvelope_", "ListEnvelope_")) or n in ("HTTPValidationError", "ValidationError"):
        MODEL_MODULE.pop(n, None)


def prop_table(schema, link_prefix="", only_required=False) -> list[str]:
    schema = resolve(schema)
    props = schema.get("properties", {})
    req = set(schema.get("required", []))
    if not props:
        return []
    lines = ["| Field | Required | Type | Nullable | Constraints / default | Description |", "|---|---|---|---|---|---|"]
    for name, ps in props.items():
        inner, nullable = non_null(ps)
        c = constraints(ps)
        d = ps.get("default", inner.get("default", None))
        if "default" in ps or "default" in inner:
            c = (c + ", " if c else "") + f"default=`{json.dumps(d)}`"
        desc = (ps.get("description") or inner.get("description") or "").replace("\n", " ").replace("|", "\\|")
        lines.append(f"| `{name}` | {'yes' if name in req else 'no'} | {type_str(ps, link_prefix)} | "
                     f"{'yes' if nullable else 'no'} | {c or '-'} | {desc or '-'} |")
    return lines


def example(s, name: str = "", depth: int = 0, all_props: bool = False):
    s = resolve(s)
    if depth > 4:
        return None
    if "example" in s:
        return s["example"]
    if "examples" in s and s["examples"]:
        return s["examples"][0]
    if "default" in s and s["default"] is not None:
        return s["default"]
    if "const" in s:
        return s["const"]
    if "enum" in s:
        return s["enum"][0]
    if "anyOf" in s or "oneOf" in s:
        opts = [o for o in s.get("anyOf", s.get("oneOf")) if o.get("type") != "null"]
        return example(opts[0], name, depth, all_props) if opts else None
    if "allOf" in s:
        return example(s["allOf"][0], name, depth, all_props)
    t = s.get("type")
    if t == "object" or "properties" in s:
        props = s.get("properties", {})
        req = set(s.get("required", []))
        out = {}
        for k, v in props.items():
            if k in req or all_props or len(props) <= 8:
                out[k] = example(v, k, depth + 1, all_props)
        return out
    if t == "array":
        item = example(s.get("items", {}), name, depth + 1, all_props)
        return [item] if item is not None else []
    if t == "boolean":
        return True
    if t == "integer":
        lo = s.get("minimum", s.get("exclusiveMinimum", 0) + 1 if "exclusiveMinimum" in s else 1)
        return max(lo, 1) if "maximum" not in s else min(max(lo, 1), s["maximum"])
    if t == "number":
        return s.get("minimum", 1.5)
    if t == "string":
        fmt = s.get("format")
        if fmt == "uuid":
            return UUID_POOL[sum(map(ord, name)) % len(UUID_POOL)]
        if fmt == "date":
            return "2026-01-15"
        if fmt == "date-time":
            return "2026-01-15T09:30:00Z"
        if fmt == "email":
            return "person@example.com"
        if fmt == "time":
            return "09:00:00"
        pat = s.get("pattern", "")
        if "\\d*\\.?\\d*" in pat:
            return "1.00"
        n = name.lower()
        base = ("person@example.com" if "email" in n else "Asia/Kolkata" if n == "timezone" else
                "2026-01-15" if n.endswith("date") else "09:00" if "time" in n else "INR" if n == "currency" else
                "IN" if n == "country_code" else "Example " + (name.replace("_", " ") or "text"))
        if "minLength" in s and len(base) < s["minLength"]:
            base = base + "x" * (s["minLength"] - len(base))
        if "maxLength" in s and len(base) > s["maxLength"]:
            base = base[: s["maxLength"]]
        return base
    return None


def envelope_parts(op: dict, code: str):
    resp = op["responses"].get(code, {})
    sch = resp.get("content", {}).get("application/json", {}).get("schema")
    if not sch:
        return None, None, None
    env = resolve(sch)
    props = env.get("properties", {})
    data = props.get("data")
    return data, ("pagination" in props), env


# --------------------------------------------------------------------------------------------
# 5. Error catalogue
# --------------------------------------------------------------------------------------------

ERR_CLASSES: dict[tuple[str, str], dict] = {}
for _name in _all_module_names():
    try:
        importlib.import_module(_name)
    except Exception:
        pass


def _subs(c):
    for s in c.__subclasses__():
        yield s
        yield from _subs(s)


for c in _subs(AppError):
    parts = c.__module__.split(".")
    owner = parts[2] if len(parts) > 2 and parts[1] == "modules" else ("shared" if parts[1] == "shared" else parts[1])
    ERR_CLASSES[(c.__module__, c.__name__)] = {
        "cls": c.__name__, "code": c.code, "status": c.status_code, "owner": owner, "module": c.__module__,
        "doc": " ".join(inspect.cleandoc(c.__dict__.get("__doc__") or "").split())[:240], "headers": c.headers,
    }
ERRORS = sorted(ERR_CLASSES.values(), key=lambda e: (e["owner"], e["status"], e["code"], e["cls"]))

# --------------------------------------------------------------------------------------------
# 6. Markdown: endpoint reference
# --------------------------------------------------------------------------------------------

MODULE_TITLES = {
    "identity": ("Identity & Authentication", "Login, token refresh, password reset, email verification, session identity."),
    "organisation": ("Organisation & Company", "Company registration/profile, legal entities, branches, departments, designations, grades, shifts, holiday & work calendars, policy assignments, dashboard."),
    "employee": ("Employees", "Employee records and their sub-resources: employments, assignments, compensation, statutory, bank, education, experience, dependents, documents."),
    "employee_import": ("Employee Bulk Import", "CSV/XLSX bulk import batches."),
    "attendance": ("Attendance", "Punches (manual and face), attendance days, policies, rosters, regularization, overtime, periods, leave projections, face enrollment."),
    "leave": ("Leave", "Leave types/policies/year settings, ledger and balances, applications and approvals."),
    "payroll": ("Payroll", "Salary components/structures, pay runs, payslips, statutory rates, adjustments."),
    "onboarding": ("Onboarding", "HR-side onboarding cases and the public candidate portal (token links)."),
    "account_invite": ("Account Invites & Users", "Inviting employees/users, role assignment, public invite acceptance."),
    "platform": ("Platform Console", "Super-admin console. NOT part of the tenant mobile API surface."),
    "health": ("Health", "Liveness/readiness probes."),
}
SLUG = {k: k for k in MODULE_TITLES}


def md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def slug(method: str, path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{method} {path}".lower()).strip("-")


def curl_for(r, op, body_ex) -> str:
    url = "$BASE_URL" + r["path"]
    url = re.sub(r"\{([a-z_]+)\}", lambda m: "<" + m.group(1) + ">", url)
    q = [p for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")]
    if q:
        url += "?" + "&".join(f"{p['name']}=<{p['name']}>" for p in q)
    lines = [f"curl -X {r['method']} \"{url}\""]
    if auth_kind(r) == "Tenant Bearer" or auth_kind(r).startswith("Platform"):
        lines.append("  -H \"Authorization: Bearer $ACCESS_TOKEN\"")
    for p in op.get("parameters", []):
        if p["in"] == "header" and p["name"] == "If-Match" and p.get("required"):
            lines.append("  -H \"If-Match: <resource version>\"")
    if r["idem"]:
        lines.append("  -H \"Idempotency-Key: $(uuidgen)\"")
    rb = op.get("requestBody")
    if rb:
        ct = next(iter(rb["content"]))
        if ct == "application/json":
            lines.append("  -H \"Content-Type: application/json\"")
            lines.append("  -d '" + json.dumps(body_ex, separators=(",", ":")) + "'")
        else:
            sch = resolve(rb["content"][ct]["schema"])
            for k, v in sch.get("properties", {}).items():
                vs = non_null(v)[0]
                if vs.get("format") == "binary" or (vs.get("type") == "array" and vs.get("items", {}).get("format") == "binary"):
                    lines.append(f"  -F \"{k}=@./{k}.jpg\"")
                else:
                    lines.append(f"  -F \"{k}={example(v, k)}\"")
    return " \\\n".join(lines)


#: Hand-verified (read from identity/organisation service code) error rows for the auth surface.
#: (status, code, meaning, mobile action, retry-safe)
ENDPOINT_ERRORS: dict[tuple[str, str], list[tuple[str, str, str, str, str]]] = {
    ("POST", "/v1/auth/login"): [
        ("401", "INVALID_CREDENTIALS", "Unknown email, wrong password, account not ACTIVE, user has no company membership, or `company_id` is not one of the user's companies. Deliberately indistinguishable.", "Show 'Invalid email or password'.", "yes"),
        ("423", "ACCOUNT_LOCKED", "5 consecutive bad passwords lock the account for 15 minutes (`locked_until`). Checked before the password.", "Show lockout message; do not auto-retry. Platform admin can unlock a company admin.", "no (wait 15 min)"),
        ("403", "EMAIL_NOT_VERIFIED", "Password was correct but `email_verified_at` is null.", "Offer 'Resend verification' (`POST /v1/auth/email/resend-verification`).", "after verifying"),
        ("403", "COMPANY_REJECTED / COMPANY_TERMINATED", "The selected company may not sign in. (`COMPANY_PENDING_APPROVAL` / `COMPANY_SUSPENDED` may sign in, read-only.)", "Show company-state screen.", "no"),
    ],
    ("POST", "/v1/auth/token/refresh"): [
        ("401", "INVALID_TOKEN", "No refresh token supplied (no cookie and no body), unknown/expired/revoked token, ended session, inactive user, lost membership. Re-presenting an already-rotated token revokes the whole token family and session.", "Clear local session and go to sign-in.", "no"),
        ("403", "COMPANY_REJECTED / COMPANY_TERMINATED", "Company can no longer be used.", "Sign out, show company-state screen.", "no"),
    ],
    ("POST", "/v1/auth/password/forgot"): [
        ("202", "(success, always)", "Returns `{\"accepted\": true}` whether or not the email exists (anti-enumeration). The email link points at `{web_app_base_url}/reset-password/<token>`.", "Show 'If the account exists, an email was sent'.", "yes")],
    ("POST", "/v1/auth/password/reset"): [
        ("422", "VALIDATION_ERROR (details[].code=WEAK_PASSWORD)", "Password < 8 or > 128 chars, no letter or no digit, or on the common-password blocklist.", "Show the rule.", "yes (after fix)"),
        ("401", "INVALID_TOKEN", "Reset token unknown, expired (2 h), or already used.", "Ask user to request a new link.", "no"),
    ],
    ("POST", "/v1/auth/email/verify"): [("401", "INVALID_TOKEN", "Verification token unknown, expired (24 h) or already used.", "Offer resend.", "no")],
    ("POST", "/v1/auth/email/resend-verification"): [("202", "(success, always)", "Returns `{\"accepted\": true}` regardless of account existence.", "Neutral confirmation.", "yes")],
    ("GET", "/v1/auth/companies/{company_id}"): [("404", "NOT_FOUND", "`company_id` differs from the caller's own company (or does not exist).", "-", "no")],
    ("POST", "/v1/companies/register"): [
        ("422", "REQUEST_VALIDATION_ERROR", "`timezone` not in `allowed_company_timezones` (see registration-config), `company_size` not an allowed band, currency/country not alphabetic.", "Populate pickers from `GET /v1/companies/registration-config`.", "yes (after fix)"),
        ("409", "CONFLICT", "An account with the admin email already exists (message: 'An account with this email already exists').", "Show field error / offer sign-in.", "no"),
        ("422", "VALIDATION_ERROR (details[0].code=WEAK_PASSWORD, field admin_password)", "Password < 8 or > 128 chars, no letter/digit, or common password.", "Show the rule.", "yes (after fix)")],
}


def generic_errors(r, op) -> list[tuple[str, str, str, str, str]]:
    """(status, code, meaning, mobile action, retry-safe) - only conditions derivable from the dependency graph."""
    rows = []
    kind = auth_kind(r)
    if kind in ("Tenant Bearer",) or kind.startswith("Platform"):
        rows.append(("401", "UNAUTHORIZED / INVALID_TOKEN", "Missing, malformed, expired or revoked access token, inactive user, ended session, or invalid company membership.", "Refresh once (`POST /v1/auth/token/refresh`), replay; if refresh fails go to sign-in.", "yes (after refresh)"))
    if r["static_perms"] or r["inhandler_perms"]:
        rows.append(("403", "PERMISSION_DENIED", "The caller's roles do not grant the required permission (`" + "`, `".join(r["static_perms"] + r["inhandler_perms"]) + "`).", "Hide/disable the action; do not retry.", "no"))
    if kind == "Tenant Bearer" and r["method"] not in ("GET", "HEAD") and not r["path"].startswith("/v1/auth/"):
        rows.append(("403", "COMPANY_PENDING_APPROVAL / COMPANY_SUSPENDED", "Company is read-only; writes refused (also COMPANY_REJECTED / COMPANY_TERMINATED for any request).", "Show read-only banner; do not retry.", "no"))
    if any(p["name"] == "X-Company-Id" for p in op.get("parameters", [])) and kind == "Tenant Bearer":
        rows.append(("404", "NOT_FOUND", "Also returned (with `Resource not found`) when `X-Company-Id` is sent and differs from the token's company.", "Omit the header or send the token's `company_id`.", "no"))
    if any(p["name"] == "If-Match" for p in op.get("parameters", [])):
        rows.append(("422", "REQUEST_VALIDATION_ERROR / INVALID_IF_MATCH", "`If-Match` header missing, or not an integer version (`3`, `\"3\"`, `W/\"3\"`).", "Send the `version` from the last read.", "yes (after fix)"))
        rows.append(("409", "STALE_RESOURCE (see module error list)", "Version in `If-Match` no longer matches the stored row.", "Re-fetch, re-apply the user's edit, resubmit with the new version.", "after re-fetch"))
    if r["idem"]:
        rows.append(("422", "IDEMPOTENCY_KEY_REQUIRED / IDEMPOTENCY_KEY_INVALID", "`Idempotency-Key` missing or not 8-128 chars of `A-Za-z0-9._:-`.", "Generate a UUID per user action.", "yes (after fix)"))
        rows.append(("409", "IDEMPOTENCY_KEY_CONFLICT", "Same key already used with a different request body/actor.", "Use a new key for a new action.", "no"))
    if op.get("parameters") or op.get("requestBody"):
        rows.append(("422", "REQUEST_VALIDATION_ERROR", "Body/query/path failed schema validation; `details[]` has `field` (dotted location) + `code` + `message`.", "Map `details[].field` onto form fields.", "yes (after fix)"))
    if r["rate"]:
        rows.append(("429", "RATE_LIMITED", "Rate limit exceeded (" + "; ".join(r["rate"]) + "). `Retry-After` header set.", "Back off for `Retry-After` seconds.", "yes (after wait)"))
        rows.append(("503", "RATE_LIMITER_UNAVAILABLE", "Redis unavailable behind the limiter (fails closed). `Retry-After: 5`.", "Retry with backoff.", "yes"))
    rows = ENDPOINT_ERRORS.get((r["method"], r["path"]), []) + rows
    rows.append(("503", "DATABASE_BUSY", "Lock/statement timeout, deadlock or serialization failure (transaction rolled back). `Retry-After: 2`.", "Retry with backoff.", "yes"))
    rows.append(("500", "INTERNAL_ERROR", "Unhandled server error. Body carries `request_id` for support.", "Show generic error + `request_id`. For writes, re-read state before retrying (outcome of a lost response is unknown).", "reads: yes; writes: only if idempotent"))
    return rows


def write_module_docs():
    by_mod = collections.defaultdict(list)
    for r in ROUTES:
        by_mod[r["module"]].append(r)
    (OUT / "modules").mkdir(parents=True, exist_ok=True)
    for mod, rs in by_mod.items():
        title, blurb = MODULE_TITLES.get(mod, (mod, ""))
        L = [f"# {title} - endpoint reference", "", f"> {blurb}", "",
             "Generated by [`tools/build_api_docs.py`](../tools/build_api_docs.py) from the running FastAPI app "
             "(routes, dependencies, Pydantic schemas) - not hand-written. Examples are **schema-derived and illustrative; "
             "they were not executed against a server** unless a section says otherwise. "
             "Common conventions (envelope, pagination, headers, errors) are in [API_OVERVIEW.md](../API_OVERVIEW.md) and "
             "[ERROR_HANDLING.md](../ERROR_HANDLING.md); the models linked below are in "
             f"[models/{mod}.md](../models/{mod}.md).", "",
             f"**{len(rs)} operations.** Legend - *Tier*: A core mobile / B manager-HR workflow / C admin configuration / X not for mobile.", ""]
        L += ["| # | Method | Path | Summary | Tier | Permission |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(rs, 1):
            op = OPS[(r["method"], r["path"])]
            perms = ", ".join(r["static_perms"] + [p + " (in-handler)" for p in r["inhandler_perms"]]) or "-"
            L.append(f"| {i} | {r['method']} | [`{r['path']}`](#{slug(r['method'], r['path'])}) | {md_escape(op.get('summary',''))} | {mobile_tier(r)[0]} | {perms} |")
        L.append("")
        # module-specific error codes
        errs = [e for e in ERRORS if e["owner"] == mod]
        if errs:
            L += [f"## Domain error codes raised by this module ({len(errs)})", "",
                  "Codes below are defined in this module's exception classes. Which endpoint raises which code is not "
                  "statically mapped by this document (it depends on service logic); treat the list as the module's "
                  "vocabulary and branch on `error.code`. Full catalogue: [ERROR_CODES.md](../ERROR_CODES.md).", "",
                  "| Status | Code | Class | Notes |", "|---|---|---|---|"]
            for e in errs:
                L.append(f"| {e['status']} | `{e['code']}` | `{e['cls']}` | {md_escape(e['doc']) or '-'} |")
            L.append("")
        L.append("---")
        for r in rs:
            op = OPS[(r["method"], r["path"])]
            tier, tier_text = mobile_tier(r)
            tstat, tfiles = test_refs(r["method"], r["path"])
            mrefs = mobile_refs(r["path"])
            L += ["", f"## {r['method']} {r['path']}", f'<a id="{slug(r["method"], r["path"])}"></a>', "",
                  f"**{op.get('summary','')}**", ""]
            purpose = r["doc"] or "No docstring on the handler; purpose inferred from the route name/summary only."
            L += ["### Endpoint overview", "", "| | |", "|---|---|",
                  f"| Method / path | `{r['method']} {r['path']}` |",
                  f"| Authentication | {auth_kind(r)} |",
                  f"| Required permission(s) | {', '.join('`'+p+'`' for p in r['static_perms']) or 'none at route level'}"
                  + (f" (+ resolved inside handler: {', '.join('`'+p+'`' for p in r['inhandler_perms'])})" if r['inhandler_perms'] else "") + " |",
                  f"| Rate limit | {'; '.join(r['rate']) or 'none declared on this route (a global middleware only covers the onboarding upload path)'} |",
                  f"| Idempotency-Key | {'**required**' if r['idem'] else 'not used'} |",
                  f"| Success status | {r['status'] or 'see responses'} |",
                  f"| Mobile suitability | **{tier}** - {tier_text} |",
                  f"| Referenced by Flutter app | {', '.join('`'+m.replace('apps/mobile/lib/','')+'`' for m in mrefs[:4]) or 'no textual reference found'}{' (+%d more)' % (len(mrefs)-4) if len(mrefs)>4 else ''} |",
                  f"| Source | [`{r['src']}:{r['line']}`](../../../{r['src']}#L{r['line']}) |",
                  f"| Automated tests | {tstat}" + (": " + ", ".join(f"`{Path(f).name}`" for f in tfiles[:3]) + (f" (+{len(tfiles)-3})" if len(tfiles) > 3 else "") if tfiles else "") + " |", "",
                  "**Purpose / behaviour (from source docstring):**", "", purpose, ""]
            # parameters
            params = [p for p in op.get("parameters", [])]
            if params:
                L += ["### Request specification - parameters", "",
                      "| Name | In | Required | Type | Constraints / default | Description |", "|---|---|---|---|---|---|"]
                for p in params:
                    sch = p.get("schema", {})
                    req = p.get("required", False)
                    if p["name"] == "Idempotency-Key" and r["idem"]:
                        req = True
                    inner, _ = non_null(sch)
                    d = f", default=`{json.dumps(inner.get('default'))}`" if "default" in inner else ""
                    L.append(f"| `{p['name']}` | {p['in']} | {'yes' if req else 'no'} | {type_str(sch, '../models/'+mod+'.md')} | {(constraints(sch) + d).strip(', ') or '-'} | {md_escape(p.get('description','') or '-')} |")
                L.append("")
            body_ex = None
            rb = op.get("requestBody")
            if rb:
                ct = next(iter(rb["content"]))
                sch = rb["content"][ct]["schema"]
                L += [f"### Request body (`{ct}`, {'required' if rb.get('required') else 'optional'})", ""]
                tn = ref_name(sch["$ref"]) if "$ref" in sch else None
                if tn:
                    L.append(f"Schema: [{tn}](../models/{MODEL_MODULE.get(tn, mod)}.md#{anchor(tn)})")
                    L.append("")
                tbl = prop_table(sch, f"../models/{MODEL_MODULE.get(tn, mod)}.md")
                L += tbl + [""] if tbl else ["_No fields._", ""]
                if ct == "application/json":
                    body_ex = example(sch, tn or "")
            L += ["### Request example (schema-derived, not executed)", "", "```bash", curl_for(r, op, body_ex), "```", ""]
            if body_ex is not None and rb and next(iter(rb["content"])) == "application/json":
                L += ["```json", json.dumps(body_ex, indent=2), "```", ""]
            # success response
            L += ["### Successful response", ""]
            success = [c for c in op["responses"] if c.startswith("2")]
            for code in success:
                data, paged, env = envelope_parts(op, code)
                L.append(f"**{code}** - " + op["responses"][code].get("description", ""))
                if env is None:
                    L += ["", "No JSON body is declared (binary download, empty body or `204`). See notes.", ""]
                    continue
                if data is not None:
                    dn = non_null(data)[0]
                    item = dn.get("items", dn) if dn.get("type") == "array" else dn
                    tn = ref_name(item["$ref"]) if "$ref" in item else None
                    L += ["", f"Envelope: `{{ \"data\": {'[ ... ]' if dn.get('type')=='array' else '{ ... }'}, " + ("\"pagination\": {...}, " if paged else "") + "\"meta\": {\"request_id\", \"server_time\"} }`"
                          + (f" - `data` item is [{tn}](../models/{MODEL_MODULE.get(tn, mod)}.md#{anchor(tn)})" if tn else ""), ""]
                    if tn:
                        L += prop_table(item, f"../models/{MODEL_MODULE.get(tn, mod)}.md") + [""]
                    elif item.get("properties"):
                        L += prop_table(item, f"../models/{mod}.md") + [""]
                    ex = example(data, tn or "", all_props=True)
                    full = {"data": ex}
                    if paged:
                        full["pagination"] = {"page": 1, "per_page": 25, "total": 1, "total_pages": 1, "next_cursor": None}
                    full["meta"] = {"request_id": "req_0123456789abcdef", "server_time": "2026-01-15T09:30:00Z"}
                    L += ["```json", json.dumps(full, indent=2)[:6000], "```", ""]
            # errors
            L += ["### Error responses", "",
                  "All errors use the envelope `{\"error\": {\"code\", \"message\", \"details\": [], \"request_id\"}}` "
                  "(see [ERROR_HANDLING.md](../ERROR_HANDLING.md)). Conditions derivable from this route's dependency graph:", "",
                  "| Status | Code | Meaning / trigger | Recommended client behaviour | Safe to retry |", "|---|---|---|---|---|"]
            for st, code, meaning, act, retry in generic_errors(r, op):
                L.append(f"| {st} | `{code}` | {md_escape(meaning)} | {md_escape(act)} | {retry} |")
            L.append(f"\nDomain-specific 404/409/422 codes for this module: see the [module error list](#domain-error-codes-raised-by-this-module-{len(errs)}).\n" if errs else "")
            # notes
            notes = []
            if r["method"] in ("PATCH", "PUT", "DELETE") and any(p["name"] == "If-Match" for p in params):
                notes.append("Optimistic concurrency: send the resource's current `version` in `If-Match` (bare integer or ETag form).")
            if "versions" in r["path"] and r["method"] == "POST" and r["path"].endswith("/publish"):
                notes.append("Publishing is a state transition (DRAFT -> PUBLISHED); it cannot be undone via this API.")
            if r["status"] == 202:
                notes.append("Asynchronous: the server queued work; poll the related GET to observe progress.")
            if any(c.startswith("2") and "content" not in op["responses"][c] for c in op["responses"]):
                notes.append("Empty or non-JSON success body.")
            if r["method"] == "DELETE" and not (r["status"] == 204):
                notes.append("Soft-delete/deactivate: returns the updated resource rather than `204` (per handler docstring convention) unless the declared success status says otherwise.")
            notes.append("Verified = taken from route/dependency/schema introspection of the running app. Anything about runtime side effects beyond the docstring above is **not** asserted here.")
            L += ["### Implementation notes", ""] + [f"- {n}" for n in notes] + ["", "---"]
        (OUT / "modules" / f"{mod}.md").write_text("\n".join(L) + "\n")


# --------------------------------------------------------------------------------------------
# 7. Model dictionaries
# --------------------------------------------------------------------------------------------


def write_models():
    (OUT / "models").mkdir(exist_ok=True)
    by_mod = collections.defaultdict(list)
    for n, m in MODEL_MODULE.items():
        by_mod[m].append(n)
    for mod, names in by_mod.items():
        CUR_MODEL[0] = mod
        L = [f"# Data models - {mod}", "",
             "Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list "
             "(for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "
             "\"Server-generated\" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart "
             "(derived by name match - an inference, not a declared flag).", ""]
        for n in sorted(names):
            s = SCHEMAS[n]
            L += [f"## {n}", f'<a id="{anchor(n)}"></a>', ""]
            desc = " ".join((s.get("description") or "").split())
            if desc:
                L += [desc, ""]
            if "enum" in s and "properties" not in s:
                L += ["Enumeration: " + ", ".join(f"`{v}`" for v in s["enum"]), ""]
                continue
            tbl = prop_table(s, "")
            L += tbl + [""] if tbl else ["_No properties (free-form or alias)._", ""]
            if n.endswith("Read"):
                base = n[:-4]
                for sib in (base + "Create", base + "Update"):
                    if sib in SCHEMAS:
                        extra = sorted(set(s.get("properties", {})) - set(SCHEMAS[sib].get("properties", {})))
                        if extra:
                            L += [f"Server-generated / read-only vs `{sib}`: " + ", ".join(f"`{e}`" for e in extra), ""]
                        break
        (OUT / "models" / f"{mod}.md").write_text("\n".join(L) + "\n")



def write_enums():
    """OpenAPI types many closed vocabularies as plain `string`; the allowed values live in
    module-level tuples/frozensets that validators check. Collect those (names + values) so a
    client has the vocabulary. Whether a given field uses a given constant is NOT inferred."""
    L = ["# String vocabularies declared only in validators (generated)", "",
         "The OpenAPI schema types these fields as `string`. The tuples below are module-level constants in each "
         "module's `schemas.py` / `models.py` / `service.py` that validators or DB check constraints use. "
         "**Which request/response field consumes which constant is not mapped here** - match by name "
         "(e.g. `_PUNCH_DIRECTIONS` -> `direction`) and confirm in the linked source.", ""]
    found = collections.defaultdict(list)
    for name in _all_module_names():
        if not name.startswith("hrms.modules."):
            continue
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        owner = name.split(".")[2]
        for n, v in vars(mod).items():
            if n.startswith("__") or not n.lstrip("_").isupper():
                continue
            if isinstance(v, (tuple, frozenset, set, list)) and v and all(isinstance(x, str) for x in v) \
                    and all(re.fullmatch(r"[A-Z0-9_]+", x) for x in v) and 2 <= len(v) <= 60:
                vals = sorted(v) if isinstance(v, (frozenset, set)) else list(v)
                found[owner].append((name.split(".")[-1], n, vals))
    for owner in sorted(found):
        L += [f"## {owner}", "", "| Constant | File | Values |", "|---|---|---|"]
        for fname, n, vals in sorted(found[owner], key=lambda x: (x[1], x[0])):
            L.append(f"| `{n}` | `{owner}/{fname}.py` | {', '.join('`'+x+'`' for x in vals)} |")
        L.append("")
    (OUT / "models" / "ENUMS.md").write_text("\n".join(L) + "\n")

# --------------------------------------------------------------------------------------------
# 8. Inventory, errors, permissions
# --------------------------------------------------------------------------------------------


def write_inventory():
    by_mod = collections.defaultdict(list)
    for r in ROUTES:
        by_mod[r["module"]].append(r)
    mc = collections.Counter(r["method"] for r in ROUTES)
    tier = collections.Counter(mobile_tier(r)[0] for r in ROUTES)
    ts = collections.Counter(test_refs(r["method"], r["path"])[0] for r in ROUTES)
    ms = sum(1 for r in ROUTES if mobile_refs(r["path"]))
    L = ["# Endpoint inventory", "",
         "Complete registry of every HTTP operation registered by `hrms.app.create_app()`; generated by "
         "[`tools/build_api_docs.py`](tools/build_api_docs.py) (the script asserts that the introspected route list and "
         "`app.openapi()` agree 1:1, so no route is silently skipped).", "",
         f"**Total: {len(ROUTES)} operations on {len(set(r['path'] for r in ROUTES))} paths.** "
         f"Methods: " + ", ".join(f"{k} {v}" for k, v in sorted(mc.items())) + ".", "",
         "Mobile tiers: " + ", ".join(f"{k}={v}" for k, v in sorted(tier.items())) +
         " (A core mobile, B manager/HR workflow, C admin configuration, X not for mobile). "
         "Tiers are an editorial classification derived from permission codes, not a backend flag.", "",
         f"Test cross-reference (textual match of method+path in `apps/api/tests`): "
         + ", ".join(f"{k}={v}" for k, v in ts.items()) + ". "
         "`direct` = a test calls that method+path; `path-only` = the path string appears but the verb could not be matched; "
         "`none` = no textual reference. **This is not proof that the endpoint's behaviour is asserted**, only that a test touches it.", "",
         f"Flutter app (`apps/mobile/lib`) textual references: {ms} of {len(ROUTES)} operations have a matching path literal.", "",
         "All paths are relative to the API origin (e.g. `http://localhost:8000`). Health probes are unversioned; everything else is under `/v1`.", "",
         "## Summary by module", "", "| Module | Doc | Ops | GET | POST | PUT | PATCH | DELETE |", "|---|---|---|---|---|---|---|---|"]
    for mod, rs in sorted(by_mod.items()):
        c = collections.Counter(r["method"] for r in rs)
        L.append(f"| {MODULE_TITLES.get(mod,(mod,))[0]} | [modules/{mod}.md](modules/{mod}.md) | {len(rs)} | {c['GET']} | {c['POST']} | {c['PUT']} | {c['PATCH']} | {c['DELETE']} |")
    L.append("")
    for mod, rs in sorted(by_mod.items()):
        L += [f"## {MODULE_TITLES.get(mod,(mod,))[0]}", "",
              "| Method | Path | Summary | Auth | Permission | Tier | Idem. | Rate limit | App | Tests |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            op = OPS[(r["method"], r["path"])]
            perms = "<br>".join(r["static_perms"] + [p + "*" for p in r["inhandler_perms"]]) or "-"
            ts_, _ = test_refs(r["method"], r["path"])
            L.append(f"| {r['method']} | [`{r['path']}`](modules/{mod}.md#{slug(r['method'], r['path'])}) | {md_escape(op.get('summary',''))} | "
                     f"{auth_kind(r)} | {perms} | {mobile_tier(r)[0]} | {'req' if r['idem'] else '-'} | "
                     f"{'yes' if r['rate'] else '-'} | {'yes' if mobile_refs(r['path']) else '-'} | {ts_} |")
        L.append("")
    L += ["`*` = permission resolved inside the handler (body- or role-dependent), not by a route dependency.", ""]
    (OUT / "ENDPOINT_INVENTORY.md").write_text("\n".join(L) + "\n")


def write_errors():
    L = ["# Error code catalogue (generated)", "",
         f"Every `AppError` subclass importable from `hrms` ({len(ERRORS)} classes, {len({e['code'] for e in ERRORS})} distinct codes). "
         "Generated by [`tools/build_api_docs.py`](tools/build_api_docs.py). Envelope shape and client strategy: [ERROR_HANDLING.md](ERROR_HANDLING.md). "
         "Where one `code` is raised by several classes they are listed on separate rows.", ""]
    for owner in sorted({e["owner"] for e in ERRORS}):
        es = [e for e in ERRORS if e["owner"] == owner]
        L += [f"## {owner} ({len(es)})", "", "| Status | Code | Class | Notes |", "|---|---|---|---|"]
        for e in es:
            h = f" Header: `{', '.join(f'{k}: {v}' for k, v in e['headers'].items())}`." if e["headers"] else ""
            L.append(f"| {e['status']} | `{e['code']}` | `{e['cls']}` | {md_escape(e['doc'])}{h} |")
        L.append("")
    (OUT / "ERROR_CODES.md").write_text("\n".join(L) + "\n")


def write_permissions():
    use = collections.defaultdict(list)
    for r in ROUTES:
        for p in r["static_perms"] + r["inhandler_perms"]:
            use[p].append(f"{r['method']} {r['path'].replace('/v1','')}")
    L = ["# Permission catalogue (generated)", "",
         "Permission codes registered by each module's `permissions.py`, with the routes that reference them "
         "(`*` = resolved inside the handler). Scope levels granted per role (`SELF`, `REPORTEES`, `REPORTEE_TREE`, `BRANCH`, `COMPANY`) "
         "are data (`role_permission.data_scope`), not code - see [AUTHENTICATION.md](AUTHENTICATION.md#7-authorization-roles-permissions-data-scope).", "",
         "| Code | Module | Description | Routes |", "|---|---|---|---|"]
    seen = set()
    for p in sorted(PERMISSIONS, key=lambda x: x["code"]):
        if p["code"] in seen:
            continue
        seen.add(p["code"])
        rt = use.get(p["code"], [])
        L.append(f"| `{p['code']}` | {p['module']} | {md_escape(p['desc'])} | {'<br>'.join(rt[:8]) + (f'<br>(+{len(rt)-8} more)' if len(rt)>8 else '') if rt else '-'} |")
    others = sorted(set(use) - seen)
    if others:
        L += ["", "Codes referenced by routes but not in a module `*_PERMISSIONS` list: " + ", ".join(f"`{o}`" for o in others)]
    (OUT / "PERMISSIONS.md").write_text("\n".join(L) + "\n")


# --------------------------------------------------------------------------------------------
# 9. Enriched OpenAPI + Postman
# --------------------------------------------------------------------------------------------


def write_openapi():
    spec = copy.deepcopy(OPENAPI)
    spec["info"]["title"] = "HRMS API"
    spec["info"]["description"] = (
        "Enriched from `app.openapi()` by docs/api/tools/build_api_docs.py. Adds: servers, per-operation `x-hrms-*` "
        "metadata (permissions, rate limits, source), `Idempotency-Key` marked required where the dependency enforces it, "
        "and the shared error envelope on 4xx/5xx. FastAPI's generated schema alone under-reports these. "
        "Success responses are the generated ones, unmodified. Hand-written conventions: docs/api/API_OVERVIEW.md.")
    spec["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development (apps/mobile default; Android emulator uses http://10.0.2.2:8000)"},
        {"url": "https://{staging_host}", "description": "Staging - host NOT defined anywhere in this repository", "variables": {"staging_host": {"default": "staging.example.invalid"}}},
        {"url": "https://{production_host}", "description": "Production - host NOT defined anywhere in this repository", "variables": {"production_host": {"default": "api.example.invalid"}}},
    ]
    comps = spec["components"]
    comps["schemas"]["ErrorDetail"] = {"type": "object", "required": ["code", "message"], "properties": {
        "field": {"type": ["string", "null"]}, "code": {"type": "string"}, "message": {"type": "string"},
        "context": {"type": ["object", "null"], "additionalProperties": True}}}
    comps["schemas"]["ErrorBody"] = {"type": "object", "required": ["code", "message", "request_id"], "properties": {
        "code": {"type": "string"}, "message": {"type": "string"},
        "details": {"type": "array", "items": {"$ref": "#/components/schemas/ErrorDetail"}},
        "request_id": {"type": "string"}, "documentation_url": {"type": ["string", "null"]}}}
    comps["schemas"]["ErrorEnvelope"] = {"type": "object", "required": ["error"], "properties": {"error": {"$ref": "#/components/schemas/ErrorBody"}}}
    comps["securitySchemes"] = {
        "HTTPBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                       "description": "Tenant access token (HS256, `type=access`, 15 min default) from POST /v1/auth/login. Platform-console routes use a different JWT (`type=platform`, `aud=platform`) sent the same way - the two are not interchangeable."},
        "RefreshCookie": {"type": "apiKey", "in": "cookie", "name": "hrms_refresh",
                          "description": "HttpOnly refresh cookie set by login/register/accept/refresh; Path=/v1/auth. Only POST /v1/auth/token/refresh and /v1/auth/logout receive it."},
    }
    err = {"description": "Error envelope", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}}}
    for r in ROUTES:
        op = spec["paths"][r["path"]][r["method"].lower()]
        for p in op.get("parameters", []):
            if p["name"] == "Idempotency-Key" and r["idem"]:
                p["required"] = True
                p["description"] = "Required. 8-128 chars of A-Za-z0-9._:- ; reuse the same key to retry the same request."
        # FastAPI's own 422 is `HTTPValidationError`; the real handler returns the ErrorEnvelope.
        if "422" in op["responses"]:
            op["responses"]["422"] = {"description": "Validation error (REQUEST_VALIDATION_ERROR or a domain 422 code)", **{"content": err["content"]}}
        for st, why in (("401", "UNAUTHORIZED / INVALID_TOKEN"),):
            if auth_kind(r) == "Tenant Bearer" or r["platform"]:
                op["responses"].setdefault(st, {"description": why, "content": err["content"]})
        if r["static_perms"] or r["inhandler_perms"]:
            op["responses"].setdefault("403", {"description": "PERMISSION_DENIED (or COMPANY_* when the company is read-only/blocked)", "content": err["content"]})
        if r["rate"]:
            op["responses"].setdefault("429", {"description": "RATE_LIMITED; Retry-After header", "content": err["content"],
                                               "headers": {"Retry-After": {"schema": {"type": "integer"}}}})
        op["responses"].setdefault("503", {"description": "DATABASE_BUSY / RATE_LIMITER_UNAVAILABLE; Retry-After header", "content": err["content"]})
        op["responses"].setdefault("default", {"description": "Other error (INTERNAL_ERROR 500, domain 404/409/422 codes)", "content": err["content"]})
        if auth_kind(r) in ("Public", "Public (secret token in path)"):
            op["security"] = []
        elif r["platform"]:
            op["security"] = [{"HTTPBearer": []}]
        op["x-hrms-auth"] = auth_kind(r)
        op["x-hrms-permissions"] = r["static_perms"]
        if r["inhandler_perms"]:
            op["x-hrms-permissions-in-handler"] = r["inhandler_perms"]
        if r["rate"]:
            op["x-hrms-rate-limit"] = r["rate"]
        op["x-hrms-mobile-tier"] = mobile_tier(r)[0]
        op["x-hrms-source"] = f"{r['src']}:{r['line']}"
    # Replace FastAPI's generic validation error schemas with a pointer so nothing references a shape the server never sends.
    (OUT / "openapi.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    return spec


def pm_item(r, op):
    body_ex = None
    req = {"method": r["method"], "header": [], "url": {}}
    path = r["path"]
    raw = "{{base_url}}" + re.sub(r"\{([a-z_]+)\}", r"{{\1}}", path)
    q = [p for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")]
    req["url"] = {"raw": raw + ("?" + "&".join(f"{p['name']}=" for p in q) if q else ""),
                  "host": ["{{base_url}}"], "path": [x for x in re.sub(r"\{([a-z_]+)\}", r"{{\1}}", path).split("/") if x],
                  "query": [{"key": p["name"], "value": "", "description": (p.get("description") or "")} for p in q]}
    if auth_kind(r) == "Tenant Bearer":
        req["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}]}
    elif r["platform"]:
        req["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{platform_token}}", "type": "string"}]}
    else:
        req["auth"] = {"type": "noauth"}
    for p in op.get("parameters", []):
        if p["in"] == "header" and p["name"] == "If-Match":
            req["header"].append({"key": "If-Match", "value": "{{resource_version}}"})
    if r["idem"]:
        req["header"].append({"key": "Idempotency-Key", "value": "{{$guid}}"})
    rb = op.get("requestBody")
    if rb:
        ct = next(iter(rb["content"]))
        sch = rb["content"][ct]["schema"]
        if ct == "application/json":
            body_ex = example(sch, ref_name(sch["$ref"]) if "$ref" in sch else "")
            req["header"].append({"key": "Content-Type", "value": "application/json"})
            req["body"] = {"mode": "raw", "raw": json.dumps(body_ex, indent=2), "options": {"raw": {"language": "json"}}}
        else:
            fields = []
            for k, v in resolve(sch).get("properties", {}).items():
                vs = non_null(v)[0]
                if vs.get("format") == "binary" or vs.get("items", {}).get("format") == "binary":
                    fields.append({"key": k, "type": "file", "src": []})
                else:
                    fields.append({"key": k, "type": "text", "value": str(example(v, k))})
            req["body"] = {"mode": "formdata", "formdata": fields}
    item = {"name": f"{r['method']} {path.replace('/v1','')}  - {op.get('summary','')}", "request": req}
    if r["path"] == "/v1/auth/login":
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": [
            "const j = pm.response.json();",
            "if (j.data) { pm.environment.set('access_token', j.data.access_token); pm.environment.set('company_id', j.data.company_id); }"]}}]
    if r["path"] == "/v1/platform/auth/login":
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": [
            "const j = pm.response.json(); if (j.access_token || (j.data && j.data.access_token)) pm.environment.set('platform_token', j.access_token || j.data.access_token);"]}}]
    return item


def write_postman():
    (OUT / "postman").mkdir(exist_ok=True)
    folders = collections.defaultdict(list)
    for r in ROUTES:
        folders[r["module"]].append(pm_item(r, OPS[(r["method"], r["path"])]))
    coll = {
        "info": {"name": "HRMS API (generated)", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                 "description": "Generated from the live FastAPI app by docs/api/tools/build_api_docs.py. Request bodies are schema-derived placeholders and have NOT been executed; replace ids/values. Run 'POST /auth/login' first - its test script stores access_token and company_id. The refresh token is an HttpOnly cookie: enable Postman's cookie jar."},
        "item": [{"name": MODULE_TITLES.get(m, (m,))[0], "item": items} for m, items in sorted(folders.items())],
        "variable": [],
    }
    env = {"name": "HRMS local (template)", "values": [
        {"key": k, "value": v, "enabled": True, "type": "secret" if "token" in k else "default"}
        for k, v in [("base_url", "http://localhost:8000"), ("access_token", ""), ("platform_token", ""), ("company_id", ""),
                     ("resource_version", "1"), ("employee_id", ""), ("run_id", ""), ("application_id", ""), ("token", "")]],
        "_postman_variable_scope": "environment"}
    (OUT / "postman" / "hrms-api.postman_collection.json").write_text(json.dumps(coll, indent=2) + "\n")
    (OUT / "postman" / "hrms-local.postman_environment.json").write_text(json.dumps(env, indent=2) + "\n")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    write_openapi()
    write_module_docs()
    write_models()
    write_enums()
    write_inventory()
    write_errors()
    write_permissions()
    write_postman()
    c = collections.Counter(r["method"] for r in ROUTES)
    print(json.dumps({
        "operations": len(ROUTES), "paths": len({r["path"] for r in ROUTES}), "methods": dict(c),
        "by_module": dict(collections.Counter(r["module"] for r in ROUTES)),
        "tiers": dict(collections.Counter(mobile_tier(r)[0] for r in ROUTES)),
        "tests": dict(collections.Counter(test_refs(r["method"], r["path"])[0] for r in ROUTES)),
        "mobile_refs": sum(1 for r in ROUTES if mobile_refs(r["path"])),
        "error_classes": len(ERRORS), "distinct_codes": len({e["code"] for e in ERRORS}),
        "permissions": len({p["code"] for p in PERMISSIONS}), "schemas": len(SCHEMAS),
    }, indent=1))

"""Static inventory of permission-gated route handlers and whether each one USES the data scope its
permission was granted with.

Why: `require_permission(code)` only proves the caller holds `code` and returns the granted
`DataScope`; filtering by that scope is the handler's job. A handler that binds the scope to a
parameter it never reads (DEF-B6-02, DEF-B10-01) silently turns a SELF/REPORTEES/BRANCH grant into a
company-wide one. This module finds those handlers with the `ast` module (no regexes), covering:

* declarative: `Depends(require_permission(X))`, directly, via a module-level `Annotated[...]` alias
  (`_RunApprove`), as a default value, or in the decorator's `dependencies=[...]` (no parameter at
  all, so the scope can never be used);
* scope-returning dependencies other than `require_permission` (any parameter annotated
  `DataScope`, e.g. `_attendance_view_scope`, `_combined_balance_scope`);
* imperative: `x = await rbac.resolve_data_scope(...)` where `x` is never read.

"Uses the scope" means the bound name is read anywhere in the handler body (including being
forwarded to a service). It cannot prove the callee filters correctly - that stays the job of the
runtime scope tests - but it does catch the exact defect class found in B6/B10.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "hrms"
_HTTP = {"get", "post", "put", "patch", "delete"}


@dataclass(frozen=True)
class Handler:
    module: str
    function: str
    method: str
    path: str
    permissions: tuple[str, ...]  # codes (or "<dependency:name>") gating the handler
    scope_params: tuple[str, ...]  # parameter names carrying a scope
    ignored: tuple[str, ...]  # permissions whose scope the handler never reads
    line: int = field(default=0, compare=False)

    @property
    def key(self) -> str:
        return f"{self.module}:{self.function}"


def permission_constants() -> dict[str, str]:
    """`NAME = "DOMAIN.CODE"` assignments in every module under `hrms` (permission code files)."""
    consts: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and "." in node.value.value
                and node.value.value.upper() == node.value.value
                and node.targets[0].id.isupper()
            ):
                consts[node.targets[0].id] = node.value.value
    return consts


def _perm_arg(call: ast.Call, consts: dict[str, str]) -> str:
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return consts.get(arg.id, f"<dynamic:{arg.id}>")
    return "<unresolved>"


def _is_call_to(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def _dependency_permissions(
    node: ast.AST, consts: dict[str, str], aliases: dict[str, str]
) -> list[str]:
    """Permission codes (and custom scope dependencies) referenced anywhere inside `node`."""
    found: list[str] = []
    for sub in ast.walk(node):
        if _is_call_to(sub, "require_permission") and isinstance(sub, ast.Call) and sub.args:
            found.append(_perm_arg(sub, consts))
        elif isinstance(sub, ast.Name) and sub.id in aliases:
            found.append(aliases[sub.id])
        elif (
            isinstance(sub, ast.Call)
            and _is_call_to(sub, "Depends")
            and sub.args
            and isinstance(sub.args[0], ast.Name)
            and sub.args[0].id.startswith("_")
            and sub.args[0].id.endswith("scope")
        ):
            found.append(f"<dependency:{sub.args[0].id}>")
    return found


def _mentions_datascope(annotation: ast.AST | None) -> bool:
    return annotation is not None and any(
        isinstance(n, ast.Name) and n.id == "DataScope" for n in ast.walk(annotation)
    )


def _reads(function: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
        for stmt in function.body
        for n in ast.walk(stmt)
    )


def _route_info(function: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[str, str] | None:
    for dec in function.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in _HTTP
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
        ):
            return dec.func.attr.upper(), str(dec.args[0].value)
    return None


def scan_source(source: str, module: str, consts: dict[str, str]) -> list[Handler]:
    tree = ast.parse(source)
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                perms = _dependency_permissions(node.value, consts, {})
                if perms:
                    aliases[target.id] = perms[0]
    handlers: list[Handler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        route = _route_info(node)
        if route is None:
            continue
        permissions: list[str] = []
        scope_params: list[str] = []
        ignored: list[str] = []
        args = node.args
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        defaults = [None] * (len(args.args) + len(args.posonlyargs) - len(args.defaults))
        defaults += list(args.defaults) + list(args.kw_defaults)
        for param, default in zip(params, defaults, strict=False):
            perms: list[str] = []
            if param.annotation is not None:
                perms += _dependency_permissions(param.annotation, consts, aliases)
            if default is not None:
                perms += _dependency_permissions(default, consts, aliases)
            if not perms and _mentions_datascope(param.annotation):
                perms = [f"<dependency:{param.arg}>"]
            if not perms:
                continue
            permissions += perms
            scope_params.append(param.arg)
            if not _reads(node, param.arg):
                ignored += perms
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "dependencies":
                        for perm in _dependency_permissions(kw.value, consts, aliases):
                            permissions.append(perm)
                            ignored.append(perm)  # no parameter exists to carry the scope
        for sub in ast.walk(node):  # imperative: `x = await rbac.resolve_data_scope(.., CODE)`
            if (
                isinstance(sub, ast.Assign)
                and isinstance(sub.value, ast.Await)
                and _is_call_to(sub.value.value, "resolve_data_scope")
                and isinstance(sub.value.value, ast.Call)
                and sub.value.value.args
                and isinstance(sub.targets[0], ast.Name)
            ):
                code = _perm_arg_last(sub.value.value, consts)
                permissions.append(code)
                scope_params.append(sub.targets[0].id)
                if not _reads(node, sub.targets[0].id):
                    ignored.append(code)
        if permissions:
            handlers.append(
                Handler(
                    module=module,
                    function=node.name,
                    method=route[0],
                    path=route[1],
                    permissions=tuple(dict.fromkeys(permissions)),
                    scope_params=tuple(scope_params),
                    ignored=tuple(dict.fromkeys(ignored)),
                    line=node.lineno,
                )
            )
    return handlers


def _perm_arg_last(call: ast.Call, consts: dict[str, str]) -> str:
    arg = call.args[-1]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return consts.get(arg.id, f"<dynamic:{arg.id}>")
    return "<unresolved>"


def scan_repo() -> list[Handler]:
    consts = permission_constants()
    handlers: list[Handler] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name not in {"router.py"} and not path.name.endswith("_router.py"):
            continue
        module = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        handlers += scan_source(path.read_text(), module, consts)
    return handlers

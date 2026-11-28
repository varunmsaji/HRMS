#!/usr/bin/env python3
"""CI guard: an exception's own text must not be copied into something a user can see.

The API's contract is that an unexpected failure reaches the client as a fixed message plus a
support reference (`core/errors/handlers.py`), and the exception text stays in the server log. That
guarantee has two ways to be broken from inside a handler: building another exception from the
caught one's text (`raise SomeError(str(exc))`), and storing or returning that text as *data*
(`message = str(exc)` written to a row that an endpoint later returns - the bulk-import leak,
EH-B-01). This script finds both with the `ast` module, so it is not fooled by comments, strings,
tests or logging code.

What is checked - inside an `except ... as NAME:` handler only, in `src/hrms` (excluding the
error-handling and observability packages, which exist to deal in exception text):

* a TAINTED expression is `str(NAME)`, `repr(NAME)`, an f-string that interpolates `NAME`, or
  `NAME.message` / `NAME.args` / `NAME.detail` / `NAME.orig` (`client_message` is the safe form and
  is not tainted);
* it is a violation when a tainted expression is
    - an argument of a call to a class named `*Error` / `*Exception`,
    - the value of a keyword argument or dict key named `message`, `detail`, `error`,
      `error_message`, `reason`, `description` or `msg`, or
    - assigned to a variable with one of those names,
  unless the enclosing call is a logging call (`logger.*`, `safe_log`, `print`).

False positives are handled by `ALLOWLIST` below. Every entry names the file, the exact expression
and WHY it is safe; an entry that no longer matches anything fails the run, so the list cannot rot.

Usage: `python scripts/check_error_exposure.py` (from `apps/api`). Exit status 1 on any violation.
"""

import ast
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
SRC = API_ROOT / "src" / "hrms"

#: Packages whose job is to handle exception text (logging, the envelope handlers, the file sink).
EXCLUDED_PREFIXES = ("core/errors/", "core/observability/", "seed/")

SINK_NAMES = frozenset(
    {"message", "detail", "error", "error_message", "reason", "description", "msg"}
)
TAINTING_ATTRS = frozenset({"message", "args", "detail", "orig"})
LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical"})
LOG_FUNCTIONS = frozenset({"safe_log", "print"})
LOGGER_NAMES = frozenset({"_logger", "logger", "log", "_log"})


@dataclass(frozen=True)
class Allowed:
    path: str
    expression: str
    reason: str


#: Each entry was read and judged safe. `expression` is `ast.unparse` of the tainted expression.
ALLOWLIST: tuple[Allowed, ...] = (
    Allowed(
        "modules/payroll/service.py",
        "str(exc)",
        "BreakupError/ValueError raised by payroll.breakup / payroll validators with a fixed, "
        "written sentence (e.g. 'A salary structure needs at least one line'); no input echoed. "
        "Pydantic validation errors take the `_validation_summary` path instead.",
    ),
    Allowed(
        "modules/organisation/service.py",
        "str(exc)",
        "ValueError from validate_schedule_timezone: a fixed sentence about the timezone, "
        "shown to the admin who typed it.",
    ),
    Allowed(
        "modules/organisation/service.py",
        "[{'field': 'timezone', 'code': 'INVALID_SHIFT_VERSION_TIMEZONE', 'message': str(exc)}]",
        "The same validate_schedule_timezone ValueError, repeated as the field-level detail.",
    ),
    Allowed(
        "modules/attendance/face_service.py",
        "str(exc)",
        "LivenessImageError: every raise site in attendance/liveness.py is a fixed sentence "
        "('A frame could not be decoded.').",
    ),
    Allowed(
        "modules/attendance/face_comparison_admin.py",
        "f'The shadow provider rejected the first photo: {exc}'",
        "FaceProviderError: every raise site in the three providers is a fixed sentence and "
        "never carries the provider's own response (see FaceProviderFailedError's docstring).",
    ),
    Allowed(
        "modules/attendance/face_comparison_admin.py",
        "f'The shadow provider rejected a photo: {exc}'",
        "Same FaceProviderError case as the previous entry (second photo of the enrolment).",
    ),
    Allowed(
        "modules/attendance/opensource_face/embedding_service.py",
        "str(exc)",
        "AssetError names a model asset file; wrapped in EmbeddingUnavailableError, which the "
        "engine catches and re-raises as a fixed FaceProviderError - it is never a response.",
    ),
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    expression: str
    sink: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.expression}  ->  {self.sink}"


def _is_tainted(node: ast.AST, name: str) -> bool:
    """True when `node` is, or contains, the exception text of `name`."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            if sub.func.id in {"str", "repr"} and any(_names(a, name) for a in sub.args):
                return True
        if isinstance(sub, ast.FormattedValue) and _names(sub.value, name):
            return True
        if (
            isinstance(sub, ast.Attribute)
            and sub.attr in TAINTING_ATTRS
            and isinstance(sub.value, ast.Name)
            and sub.value.id == name
        ):
            return True
    return False


def _names(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _is_logging_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in LOG_FUNCTIONS
    if isinstance(func, ast.Attribute) and func.attr in LOG_METHODS:
        base = func.value
        if isinstance(base, ast.Name):
            return base.id in LOGGER_NAMES
        return isinstance(base, ast.Attribute) and base.attr in LOGGER_NAMES
    return False


def _is_error_class_call(call: ast.Call) -> bool:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return name.endswith(("Error", "Exception"))


def _handler_findings(handler: ast.ExceptHandler, path: str) -> list[Violation]:
    name = handler.name
    if not name:
        return []
    found: list[Violation] = []
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and not _is_logging_call(node):
                if _is_error_class_call(node):
                    for arg in [*node.args, *(k.value for k in node.keywords)]:
                        if _is_tainted(arg, name):
                            found.append(
                                Violation(path, arg.lineno, ast.unparse(arg), "error constructor")
                            )
                for kw in node.keywords:
                    if kw.arg in SINK_NAMES and _is_tainted(kw.value, name):
                        found.append(
                            Violation(path, kw.value.lineno, ast.unparse(kw.value), f"{kw.arg}=")
                        )
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value in SINK_NAMES
                        and _is_tainted(value, name)
                    ):
                        found.append(
                            Violation(path, value.lineno, ast.unparse(value), f"'{key.value}':")
                        )
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id in SINK_NAMES
                        and _is_tainted(node.value, name)
                    ):
                        found.append(
                            Violation(path, node.lineno, ast.unparse(node.value), f"{target.id} =")
                        )
    return _dedupe(found)


def _dedupe(items: list[Violation]) -> list[Violation]:
    seen: set[tuple[str, int, str]] = set()
    out: list[Violation] = []
    for v in items:
        key = (v.path, v.line, v.expression)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def check_source(source: str, path: str = "modules/example.py") -> list[Violation]:
    """Violations in one module's source, before the allowlist is applied."""
    tree = ast.parse(source)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            found.extend(_handler_findings(node, path))
    return _dedupe(found)


def scan(src: Path = SRC) -> tuple[list[Violation], list[Allowed]]:
    """(violations not covered by the allowlist, allowlist entries that matched nothing)."""
    violations: list[Violation] = []
    for file in sorted(src.rglob("*.py")):
        rel = file.relative_to(src).as_posix()
        if rel.startswith(EXCLUDED_PREFIXES):
            continue
        violations.extend(check_source(file.read_text(), rel))
    used: Counter[tuple[str, str]] = Counter()
    remaining: list[Violation] = []
    for v in violations:
        match = next(
            (a for a in ALLOWLIST if a.path == v.path and a.expression == v.expression), None
        )
        if match is None:
            remaining.append(v)
        else:
            used[(match.path, match.expression)] += 1
    stale = [a for a in ALLOWLIST if (a.path, a.expression) not in used]
    return remaining, stale


def main() -> int:
    violations, stale = scan()
    for v in violations:
        print(f"VIOLATION {v.format()}")
    for a in stale:
        print(f"STALE ALLOWLIST ENTRY {a.path}: {a.expression}  (matches nothing - remove it)")
    if violations:
        print(
            f"\n{len(violations)} place(s) copy an exception's text into a user-visible value.\n"
            "Use a fixed message (and log the exception with `safe_log(..., exc_info=exc)`), or "
            "`exc.client_message` for an AppError. If the text is genuinely a curated sentence, "
            "add an entry with the reason to ALLOWLIST in scripts/check_error_exposure.py."
        )
    if violations or stale:
        return 1
    print("check_error_exposure: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

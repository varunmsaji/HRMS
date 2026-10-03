"""Exports JSON fixtures for every response schema in the backend, in two variants:

  <module>.<Schema>.full.json    every field populated
  <module>.<Schema>.sparse.json  every nullable field null (what a half-filled record looks like)

`test/contract_fixtures_test.dart` feeds them through the mobile app's `fromJson` factories, so a
field typed differently (Decimal arrives as a string), a renamed key, or a non-null cast of a
nullable field fails offline, with no backend running and no seed data needed.

Run from the repo root (needs the API's virtualenv):

    apps/api/.venv/bin/python apps/mobile/tool/export_contract_fixtures.py
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

MODULES = ["attendance", "employee", "identity", "leave", "onboarding", "organisation", "payroll", "account_invite", "employee_import"]
OUT = Path(__file__).resolve().parents[1] / "test" / "fixtures" / "contract"


def sample(node: dict, defs: dict, sparse: bool, depth: int = 0, name: str = ""):
    if depth > 6:
        return None
    if "$ref" in node:
        return sample(defs[node["$ref"].split("/")[-1]], defs, sparse, depth + 1, name)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return node["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in node:
            options = [o for o in node[key] if o.get("type") != "null"]
            if len(options) != len(node[key]) and sparse:
                return None
            return sample(options[0], defs, sparse, depth + 1, name) if options else None
    if "allOf" in node:
        return sample(node["allOf"][0], defs, sparse, depth + 1, name)
    kind = node.get("type")
    if kind == "string":
        fmt = node.get("format")
        if fmt == "uuid":
            return str(UUID(int=0x1234))
        if fmt == "date":
            return "2026-01-15"
        if fmt == "date-time":
            return "2026-01-15T10:00:00Z"
        if fmt == "time":
            return "09:00:00"
        if fmt == "email":
            return "a@example.com"
        if "decimal" in str(node.get("pattern", "")).lower() or node.get("pattern", "").startswith("^(?!^[-+.]*$)"):
            return "1.50"
        # Timestamps/dates the backend types as plain `str` — recognise them by name.
        if name.endswith("_at"):
            return "2026-01-15T10:00:00Z"
        if name == "date" or name.endswith("_date") or name.endswith("_on"):
            return "2026-01-15"
        return "x"
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if kind == "array":
        return [sample(node.get("items", {}), defs, sparse, depth + 1, name)]
    if kind == "object" or "properties" in node:
        props = node.get("properties", {})
        return {key: sample(spec, defs, sparse, depth + 1, key) for key, spec in props.items()}
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    written = 0
    required: dict[str, list[str]] = {}
    for module in MODULES:
        schemas = importlib.import_module(f"hrms.modules.{module}.schemas")
        for name, cls in vars(schemas).items():
            if not (inspect.isclass(cls) and issubclass(cls, BaseModel) and cls.__module__ == schemas.__name__):
                continue
            try:
                schema = cls.model_json_schema(mode="serialization")
            except Exception:
                continue
            defs = schema.get("$defs", {})
            try:
                required[f"{module}.{name}"] = sorted(cls.model_json_schema(mode="validation").get("required", []))
            except Exception:
                pass
            for variant, sparse in (("full", False), ("sparse", True)):
                (OUT / f"{module}.{name}.{variant}.json").write_text(
                    json.dumps(sample(schema, defs, sparse), indent=1, sort_keys=True) + "\n"
                )
            written += 1
    (OUT / "_required.json").write_text(json.dumps(required, indent=1, sort_keys=True) + "\n")
    print(f"wrote fixtures for {written} schemas to {OUT}")


if __name__ == "__main__":
    main()

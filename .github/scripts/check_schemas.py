"""Validate the shared JSON files against their schemas.

- shared/rules/*.json against shared/rules/schema.json, plus the source rule (a value needs url and verified_on)
- shared/assumptions.json against shared/assumptions.schema.json
- pipeline/lot_schema.json and the two schemas above are valid JSON Schema (draft 2020-12)

Exit code 1 lists every problem.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline import rules  # noqa: E402


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def schema_errors(rel: str) -> list[str]:
    try:
        Draft202012Validator.check_schema(load(rel))
    except Exception as e:  # noqa: BLE001
        return [f"{rel}: not a valid JSON Schema: {e}"]
    return []


def main() -> int:
    problems: list[str] = []
    for rel in ("shared/rules/schema.json", "shared/assumptions.schema.json", "pipeline/lot_schema.json"):
        problems += schema_errors(rel)

    names = rules.rule_names()
    for name in names:
        data = load(f"shared/rules/{name}.json")
        problems += [f"shared/rules/{name}.json: {e}" for e in rules.validate(data)]

    sch = load("shared/assumptions.schema.json")
    data = load("shared/assumptions.json")
    problems += [f"shared/assumptions.json: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
                 for e in Draft202012Validator(sch).iter_errors(data)]

    for p in problems:
        print(p)
    print(f"{len(names)} rule files, assumptions and the lot schema checked: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

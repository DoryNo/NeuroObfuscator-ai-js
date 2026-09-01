from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from common import read_jsonl, write_jsonl
from importlib.util import module_from_spec, spec_from_file_location


def load_formatter():
    path = Path(__file__).with_name("07_format_for_training.py")
    spec = spec_from_file_location("format_for_training", path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rejected-plan examples from validation failures.")
    parser.add_argument("--input", type=Path, default=Path("data/candidates/validated.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/final/hard_negatives.jsonl"))
    parser.add_argument("--limit", type=int, default=1500)
    args = parser.parse_args()
    formatter = load_formatter()
    allowed = {"transformed_execution_error", "output_mismatch", "apply_error"}
    candidates = [record for record in read_jsonl(args.input)
                  if not record.get("tests_passed") and record.get("reason") in allowed]
    candidates.sort(key=lambda record: (record.get("reason", ""), record.get("id", "")))
    selected: list[dict] = []
    used_ids: set[str] = set()
    # Round-robin failure reasons to prevent one failure mode dominating the artifact.
    by_reason: dict[str, list[dict]] = {}
    for record in candidates:
        by_reason.setdefault(record.get("reason", "unknown"), []).append(record)
    while len(selected) < args.limit and by_reason:
        for reason in list(sorted(by_reason)):
            bucket = by_reason.get(reason, [])
            if not bucket:
                by_reason.pop(reason, None)
                continue
            record = bucket.pop(0)
            if record["id"] in used_ids:
                continue
            used_ids.add(record["id"])
            seed = record.get("plan", {}).get("seed", 42)
            selected.append({
                "id": f"negative:{record['id']}",
                "source_id": record["id"],
                "instruction": formatter.build_instruction(record["original_code"], record["features"], seed),
                "output": json.dumps(record["plan"], separators=(",", ":")),
                "label": "reject",
                "failure_reason": reason,
                "failing_transform": record.get("failing_transform"),
                "metadata": {
                    "source": record.get("source_type", "unknown"),
                    "repository": record.get("repository"),
                    "generator_type": record.get("generator_type"),
                    "complexity_class": formatter._complexity_class(record["features"].get("cyclomatic_complexity", 1)),
                    "cyclomatic_complexity": record["features"].get("cyclomatic_complexity", 1),
                    "intensity": record.get("plan", {}).get("intensity", "medium"),
                },
            })
    write_jsonl(args.output, selected)
    print(f"hard_negatives={len(selected)} reasons={dict(Counter(r['failure_reason'] for r in selected))} output={args.output}")


if __name__ == "__main__":
    main()

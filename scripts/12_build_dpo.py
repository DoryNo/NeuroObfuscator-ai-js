from __future__ import annotations

import argparse
import json
from collections import defaultdict
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from common import read_jsonl, write_jsonl


def load_formatter():
    path = Path(__file__).with_name("07_format_for_training.py")
    spec = spec_from_file_location("format_for_training", path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DPO chosen/rejected plan pairs.")
    parser.add_argument("--input", type=Path, default=Path("data/candidates/scored.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/final/dpo_pairs.jsonl"))
    parser.add_argument("--min-gap", type=float, default=0.05)
    parser.add_argument("--conditional", action="store_true",
                        help="v7: group by (function, intensity) and put 'Target intensity' into the prompt")
    parser.add_argument("--drop-contradictions", action="store_true",
                        help="v7: exclude R2b/R4 candidates from pair building")
    args = parser.parse_args()
    formatter = load_formatter()
    if args.drop_contradictions:
        spec6 = spec_from_file_location("score_and_select", Path(__file__).with_name("06_score_and_select.py"))
        module6 = module_from_spec(spec6)
        assert spec6 and spec6.loader
        spec6.loader.exec_module(module6)
        has_contradiction = module6.has_contradiction
    else:
        has_contradiction = None
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for record in read_jsonl(args.input):
        if record.get("tests_passed") and record.get("obfuscated_code") and record.get("metrics", {}).get("score") is not None:
            if has_contradiction is not None and has_contradiction(record):
                continue
            if args.conditional:
                key = (record["id"], record.get("plan", {}).get("intensity", "medium"))
            else:
                key = (record["id"],)
            groups[key].append(record)

    pairs = []
    for key, records in groups.items():
        if len(records) < 2:
            continue
        chosen = max(records, key=lambda record: record["metrics"]["score"])
        rejected = min(records, key=lambda record: record["metrics"]["score"])
        gap = chosen["metrics"]["score"] - rejected["metrics"]["score"]
        if gap < args.min_gap:
            continue
        seed = chosen.get("plan", {}).get("seed", 42)
        # Align rejected's seed with the prompt seed (built from chosen) so
        # preference training does not see contradictory seeds; plan parameters stay untouched.
        rejected_plan = {**rejected["plan"], "seed": seed}
        intensity = chosen.get("plan", {}).get("intensity", "medium")
        target_intensity = intensity if args.conditional else None
        function_id = key[0]
        pair_id = f"dpo:{function_id}@{intensity}" if args.conditional else f"dpo:{function_id}"
        pairs.append({
            "id": pair_id,
            "source_id": function_id,
            "prompt": formatter.build_instruction(
                chosen["original_code"], chosen["features"], seed,
                target_intensity=target_intensity,
            ),
            "chosen": json.dumps(chosen["plan"], separators=(",", ":")),
            "rejected": json.dumps(rejected_plan, separators=(",", ":")),
            "chosen_score": chosen["metrics"]["score"],
            "rejected_score": rejected["metrics"]["score"],
            "score_gap": gap,
            "metadata": {
                "source": chosen.get("source_type", "unknown"),
                "repository": chosen.get("repository"),
                "generator_type": chosen.get("generator_type"),
                "complexity_class": formatter._complexity_class(chosen["features"].get("cyclomatic_complexity", 1)),
                "cyclomatic_complexity": chosen["features"].get("cyclomatic_complexity", 1),
                "intensity": intensity,
                "score": chosen["metrics"]["score"],
            },
        })
    pairs.sort(key=lambda pair: pair["id"])
    write_jsonl(args.output, pairs)
    print(f"dpo_pairs={len(pairs)} output={args.output}")


if __name__ == "__main__":
    main()

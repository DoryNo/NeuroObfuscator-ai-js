"""Audit contradictions between prompt rules and generated plans.

Checks each formatted record (train/val/test v4) for plans whose enabled
transforms violate the rules stated in the system prompt:

  R1. string_encode requires string_count > 0
  R2. operator_sub recommended only when operator_count > 2  (hard violation
      when operator_count <= 0: nothing to substitute)
  R3. dead_code count must be within 1-5 and not over-bloat tiny functions
      (line_count <= 5 with count >= 4 -> warning)
  R4. opaque_predicates on light intensity functions (cc <= 2) -> warning,
      prompt says "Use for medium/heavy intensity"
  R5. order array must respect canonical ordering
  R6. output seed must equal the instruction seed

Usage:
    python scripts/10_audit_contradictions.py \
        --inputs data/final_v4/train.jsonl data/final_v4/val.jsonl data/final_v4/test.jsonl \
        --report reports/contradictions_report.json

With --clean, writes contradiction-free copies next to the inputs
(<name>.clean.jsonl) and drops violating records.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import read_jsonl, write_jsonl

CANONICAL_ORDER = ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]

CODE_RE = re.compile(r"=== CODE ===\n(.*?)\n=== END CODE ===", re.S)
FEATURES_RE = re.compile(r"=== AST FEATURES ===\n(.*?)\n=== END AST FEATURES ===", re.S)
SEED_RE = re.compile(r"seed=(\d+)")


def parse_record(record: dict) -> dict | None:
    ins = record.get("instruction", "")
    code_m = CODE_RE.search(ins)
    feat_m = FEATURES_RE.search(ins)
    seed_m = SEED_RE.search(ins)
    if not (code_m and feat_m):
        return None
    try:
        features = json.loads(feat_m.group(1))
        plan = json.loads(record["output"])
    except (json.JSONDecodeError, KeyError):
        return None
    return {
        "id": record.get("id"),
        "features": features,
        "plan": plan,
        "instruction_seed": int(seed_m.group(1)) if seed_m else None,
        "code": code_m.group(1),
    }


def check_record(parsed: dict) -> list[str]:
    """Return a list of violation codes (empty = clean)."""
    violations: list[str] = []
    f = parsed["features"]
    plan = parsed["plan"]
    order = plan.get("order", [])

    # R1: string_encode without strings
    if "string_encode" in order and f.get("string_count", 0) == 0:
        violations.append("R1:string_encode_without_strings")

    # R2a: operator_sub with no operators at all (hard)
    if "operator_sub" in order and f.get("operator_count", 0) <= 0:
        violations.append("R2a:operator_sub_no_operators")
    # R2b: operator_sub against stated rule operator_count > 2 (soft)
    elif "operator_sub" in order and f.get("operator_count", 0) <= 2:
        violations.append("R2b:operator_sub_le2_ops")

    # R3: dead_code bloat on tiny functions
    params = plan.get("params", {}) or {}
    dc_count = params.get("dead_code", {}).get("count") if isinstance(params.get("dead_code"), dict) else None
    line_count = f.get("line_count", 0)
    if "dead_code" in order and line_count <= 5 and isinstance(dc_count, int) and dc_count >= 4:
        violations.append("R3:dead_code_bloat_tiny")

    # R4: opaque_predicates on light complexity
    cc = f.get("cyclomatic_complexity", 1)
    if "opaque_predicates" in order and cc <= 2:
        violations.append("R4:opaque_on_light")

    # R5: canonical order respected
    idx = [CANONICAL_ORDER.index(t) for t in order if t in CANONICAL_ORDER]
    if idx != sorted(idx):
        violations.append("R5:order_canonical")
    unknown = [t for t in order if t not in CANONICAL_ORDER]
    if unknown:
        violations.append("R5:unknown_transform")

    # R6: seed consistency — seed is no longer part of the model output
    # (runtime injects it), so only check the instruction still carries one.
    if parsed["instruction_seed"] is None:
        violations.append("R6:seed_missing_in_prompt")

    return violations


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", nargs="+", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=Path("reports/contradictions_report.json"))
    ap.add_argument("--clean", action="store_true", help="write <name>.clean.jsonl beside each input")
    ap.add_argument("--hard-only", action="store_true",
                    help="drop only hard violations (R1,R2a,R2b,R5,R6); keep soft ones like R4")
    args = ap.parse_args()

    summary: dict[str, dict] = {}
    for path in args.inputs:
        records = list(read_jsonl(path))
        per_violation: Counter = Counter()
        violating_ids: defaultdict[str, list] = defaultdict(list)
        clean_records: list[dict] = []
        unparsed = 0
        hard_rules = {"R1", "R2a", "R2b", "R5", "R6"}
        for rec in records:
            parsed = parse_record(rec)
            if parsed is None:
                unparsed += 1
                continue
            violations = check_record(parsed)
            is_hard = any(v.split(":")[0] in hard_rules for v in violations)
            drop = bool(violations) and (not args.hard_only or is_hard)
            if violations:
                for v in violations:
                    per_violation[v.split(":")[0]] += 1
                    violating_ids[v].append(rec.get("id"))
            if not drop:
                clean_records.append(rec)

        total = len(records) - unparsed
        n_bad = total - len(clean_records)
        print(f"\n== {path}")
        print(f"   records: {len(records)} (unparsed: {unparsed})")
        print(f"   clean: {len(clean_records)}  violating: {n_bad} ({100*n_bad/max(total,1):.1f}%)")
        for code, cnt in sorted(per_violation.items()):
            print(f"   {code}: {cnt}")

        summary[str(path)] = {
            "records": len(records),
            "unparsed": unparsed,
            "violating": n_bad,
            "by_rule": dict(per_violation),
            "ids_by_rule": {k: v[:200] for k, v in violating_ids.items()},
        }

        if args.clean:
            out = path.with_name(path.stem + ".clean.jsonl")
            write_jsonl(out, clean_records)
            print(f"   -> wrote {out} ({len(clean_records)} records)")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved to {args.report}")


if __name__ == "__main__":
    main()

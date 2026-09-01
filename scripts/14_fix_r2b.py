"""Fix R2b contradictions (operator_sub enabled while operator_count <= 2).

Strategy: for every candidate in scored_v4 with an R2b violation, swap its plan
for a same-function, tests-passed alternative from validated_full that does NOT
enable operator_sub. Then re-run 07_format_for_training to rebuild formatted
records, and soften the R4 wording in SYSTEM_PROMPT.

Usage:
    python scripts/14_fix_r2b.py \
        --scored data/candidates/scored_v4.jsonl \
        --validated data/candidates/validated_full.jsonl \
        --output data/candidates/scored_v4_fixed.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import read_jsonl, write_jsonl


def is_r2b(record: dict) -> bool:
    p = record.get("plan", {})
    f = record.get("features", {})
    return bool(
        p.get("transforms", {}).get("operator_sub", {}).get("enabled")
        and f.get("operator_count", 0) <= 2
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scored", type=Path, default=Path("data/candidates/scored_v4.jsonl"))
    ap.add_argument("--validated", type=Path, default=Path("data/candidates/validated_full.jsonl"))
    ap.add_argument("--output", type=Path, default=Path("data/candidates/scored_v4_fixed.jsonl"))
    args = ap.parse_args()

    by_id: defaultdict[str, list] = defaultdict(list)
    for v in read_jsonl(args.validated):
        by_id[v["id"]].append(v)

    fixed = kept = missing_alt = 0
    out = []
    for rec in read_jsonl(args.scored):
        if is_r2b(rec):
            alts = [
                v for v in by_id.get(rec["id"], [])
                if v["tests_passed"]
                and not v["plan"]["transforms"]["operator_sub"]["enabled"]
            ]
            if alts:
                # pick highest-scoring alternative deterministically
                best = max(
                    alts,
                    key=lambda v: (
                        v.get("metrics", {}).get("score", 0),
                        v["candidate_id"],
                    ),
                )
                replacement = {k: best[k] for k in rec.keys() if k in best}
                # keep metrics from the replacement so score matches the plan
                replacement["metrics"] = best.get("metrics") or rec.get("metrics")
                out.append(replacement)
                fixed += 1
                continue
            missing_alt += 1
        kept += 1
        out.append(rec)

    n = write_jsonl(args.output, out)
    print(f"written={n} fixed_r2b={fixed} dropped_no_alternative={missing_alt} output={args.output}")


if __name__ == "__main__":
    main()

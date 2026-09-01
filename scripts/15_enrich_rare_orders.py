"""Enrich rare-order coverage in the formatted dataset (v5).

The v4_fixed dataset covers only 24 unique transform orders, and 94% of
records contain `rename`. The model never sees alternatives like
`string_encode > dead_code` or plans without rename at all.

This script adds quota-driven extra records from the validated candidate pool:

  --rare-min-count   orders with fewer than this many records in the current
                     train set are considered "rare" and topped up
  --extra-target     total number of extra records to add (sampled from rare
                     orders first, then no-rename diversity)

Extra candidates must:
  - pass tests (tests_passed)
  - not already be present in the current train/val/test (by candidate_id)
  - keep real/synthetic quotas intact (extras are synthetic-only by default,
    so the exact real counts of the splits are untouched)

Output: a merged formatted file that can be split again with 08_split_dataset.py.

Usage:
    python scripts/15_enrich_rare_orders.py \
        --formatted data/final/formatted_v4_fixed.jsonl \
        --validated data/candidates/validated_full.jsonl \
        --scored data/candidates/scored_v4_fixed.jsonl \
        --current-split-dir data/final_v4_fixed \
        --output data/final/formatted_v5.jsonl \
        --extra-target 1500
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import read_jsonl

TRANSFORMS = ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]


def plan_order(plan: dict) -> tuple:
    t = plan.get("transforms", {})
    return tuple(name for name in TRANSFORMS if t.get(name, {}).get("enabled"))


def format_candidate(record: dict) -> dict:
    """Format a validated_full record exactly like 07_format_for_training does."""
    # import lazily so SYSTEM_PROMPT stays single-sourced
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fmt", str(Path(__file__).parent / "07_format_for_training.py"))
    fmt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmt)
    return fmt.format_record(record)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--formatted", type=Path, default=Path("data/final/formatted_v4_fixed.jsonl"))
    ap.add_argument("--validated", type=Path, default=Path("data/candidates/validated_full.jsonl"))
    ap.add_argument("--scored", type=Path, default=Path("data/candidates/all_scored_v4.jsonl"))
    ap.add_argument("--split-dir", type=Path, default=Path("data/final_v4_fixed"))
    ap.add_argument("--output", type=Path, default=Path("data/final/formatted_v5.jsonl"))
    ap.add_argument("--extra-target", type=int, default=1500)
    ap.add_argument("--rare-threshold", type=int, default=100,
                    help="orders with fewer train records than this are rare")
    ap.add_argument("--seed", type=int, default=20260824)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    used_ids: set[str] = set()
    train_orders: Counter = Counter()
    for path in sorted(args.split_dir.glob("*.jsonl")):
        for rec in read_jsonl(path):
            used_ids.add(rec["id"])
            if path.stem.startswith("train"):
                try:
                    train_orders[plan_order(json.loads(rec["output"]))] += 1
                except (json.JSONDecodeError, KeyError):
                    pass

    print(f"used ids across splits: {len(used_ids)}")
    print(f"train order classes: {len(train_orders)}, rare (<{args.rare_threshold}): "
          f"{sum(1 for c in train_orders.values() if c < args.rare_threshold)}")

    # scored ids are already in the dataset pipeline; validated_full holds all passed candidates.
    # Build pool of unused, passed candidates whose id is NOT already in any split
    # (id-level dedup keeps splits disjoint) and whose candidate_id is unused.
    pool_by_order: defaultdict[tuple, list] = defaultdict(list)
    for v in read_jsonl(args.validated):
        if not v.get("tests_passed"):
            continue
        if v["candidate_id"] in {i + suffix for i in used_ids for suffix in ("",)} :
            continue
        if v["source_type"] != "synthetic":
            continue  # protect exact real quotas in splits
        o = plan_order(v["plan"])
        if len(o) == 0:
            continue
        # respect prompt rules: no operator_sub when operator_count <= 2
        if "operator_sub" in o and v["features"].get("operator_count", 0) <= 2:
            continue
        if "string_encode" in o and v["features"].get("string_count", 0) == 0:
            continue
        pool_by_order[o].append(v)

    extras: list[dict] = []
    # Phase 1: top up rare orders
    rare_orders = [o for o in train_orders if train_orders[o] < args.rare_threshold]
    rng.shuffle(rare_orders)
    per_rare_cap = max(args.extra_target // max(len(rare_orders), 1), 10)
    for o in rare_orders:
        cands = pool_by_order.get(o, [])
        rng.shuffle(cands)
        take = min(per_rare_cap, args.rare_threshold - train_orders[o], len(cands))
        for v in cands[:take]:
            extras.append(v)
            used_ids.add(v["candidate_id"])

    # Phase 2: fill remaining quota from under-represented structures (no-rename first)
    remaining = args.extra_target - len(extras)
    if remaining > 0:
        norename = []
        for o, cands in pool_by_order.items():
            if "rename" not in o and train_orders.get(o, 0) + sum(
                    1 for e in extras if plan_order(e["plan"]) == o) < args.extra_target:
                norename.extend(cands)
        rng.shuffle(norename)
        seen_cand = {e["candidate_id"] for e in extras}
        for v in norename:
            if remaining <= 0:
                break
            if v["candidate_id"] in seen_cand or v["id"] in {
                    x["id"] for x in extras}:
                continue
            extras.append(v)
            seen_cand.add(v["candidate_id"])
            remaining -= 1

    # dedupe extras by function id (different candidates of the same function)
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for e in extras:
        if e["id"] in seen_ids:
            continue
        seen_ids.add(e["id"])
        deduped.append(e)
    dropped_dupes = len(extras) - len(deduped)
    if dropped_dupes:
        print(f"dropped {dropped_dupes} extra duplicates (same function, different plan)")
    extras = deduped

    print(f"selected {len(extras)} extra candidates")

    # Format extras into training records using the canonical formatter.
    # validated_full lacks `metrics`; take them from the scored pool (all passed
    # candidates are present there).
    by_candidate = {}
    for v in read_jsonl(args.validated):
        by_candidate[v["candidate_id"]] = v
    metrics_by_candidate = {}
    for s in read_jsonl(args.scored):
        if "metrics" in s:
            metrics_by_candidate[s["candidate_id"]] = s["metrics"]
    formatted_extras = []
    for e in extras:
        rec = dict(by_candidate[e["candidate_id"]])
        m = metrics_by_candidate.get(rec["candidate_id"])
        if m is None:
            continue  # skip unscored extras defensively
        rec["metrics"] = m
        formatted_extras.append(format_candidate(rec))

    base = list(read_jsonl(args.formatted))
    base_ids = {r["id"] for r in base}
    # same function with a different plan would collide on `id`; drop those
    # collisions so split disjointness (id-level) stays verifiable
    dropped_collisions = sum(1 for r in formatted_extras if r["id"] in base_ids)
    formatted_extras = [r for r in formatted_extras if r["id"] not in base_ids]
    out_records = base + formatted_extras
    if dropped_collisions:
        print(f"dropped {dropped_collisions} extras colliding with existing function ids")

    # sanity: no duplicate ids
    ids = Counter(r["id"] for r in out_records)
    dupes = {i: c for i, c in ids.items() if c > 1}
    if dupes:
        raise SystemExit(f"duplicate ids after merge: {list(dupes)[:5]}")

    from common import write_jsonl
    n = write_jsonl(args.output, out_records)
    new_orders = Counter(plan_order(json.loads(r["output"])) for r in out_records)
    print(f"written={n} output={args.output}")
    print(f"total unique orders now: {len(new_orders)}")
    norename_total = sum(c for o, c in new_orders.items() if "rename" not in o)
    print(f"records without rename: {norename_total} ({100*norename_total/n:.1f}%)")


if __name__ == "__main__":
    main()

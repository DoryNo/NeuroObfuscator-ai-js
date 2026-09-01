from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from common import read_jsonl, write_jsonl

SPLITS = ("train", "val", "test")


def _stable_key(record_id: str, seed: int) -> bytes:
    return hashlib.sha256(f"{seed}:{record_id}".encode()).digest()


def _make_seed_variant(record: dict, new_seed: int) -> dict:
    """Clone a formatted record with a different seed."""
    import copy
    variant = copy.deepcopy(record)
    variant["id"] = f"{record['id']}:s{new_seed}"
    # Parse output JSON and update seed
    try:
        plan = json.loads(variant["output"])
        plan["seed"] = new_seed
        variant["output"] = json.dumps(plan, separators=(",", ":"))
    except Exception:
        pass

    # Update seed reference in instruction
    if "instruction" in variant:
        variant["instruction"] = re.sub(
            r"seed=\d+", f"seed={new_seed}", variant["instruction"]
        )

    variant.setdefault("metadata", {})["seed_variant"] = True
    return variant


def _cell_of(record: dict, fields: list[str]) -> tuple[str, ...]:
    metadata = record.get("metadata", {})
    return tuple(str(metadata.get(field, "unknown")) for field in fields)


def _largest_remainder(n: int, weights: list[float]) -> list[int]:
    """Hamilton allocation of n items proportional to weights."""
    total = sum(weights)
    ideals = [n * w / total for w in weights]
    base = [int(x) for x in ideals]
    leftover = n - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-(ideals[i] - base[i]), i))
    for i in order[:leftover]:
        base[i] += 1
    return base


def _allocate_cell(n: int, weights: list[float]) -> list[int]:
    """Proportional Hamilton allocation; cells >= 3 keep >= 1 per split.

    Splitting off fixed minimums first would bias small-ratio splits upward,
    so that guarantee is enforced only where plain Hamilton violates it.
    """
    alloc = _largest_remainder(n, weights)
    if n >= len(SPLITS):
        for i, count in enumerate(alloc):
            if count == 0:
                donor = max(range(len(alloc)), key=lambda j: (alloc[j] - n * weights[j] / sum(weights), -j))
                alloc[donor] -= 1
                alloc[i] = 1
    return alloc


def _reconcile(allocation: dict[tuple, dict[str, int]], targets: dict[str, int],
               cells: dict[tuple, list[dict]]) -> None:
    """Move individual records between splits until exact targets hold."""
    current = {split: sum(cell[split] for cell in allocation.values()) for split in SPLITS}
    overflow = {split: current[split] - targets[split] for split in SPLITS}
    moves = sum(max(0, v) for v in overflow.values())
    for _ in range(moves):
        donor = max(SPLITS, key=lambda s: (overflow[s], SPLITS.index(s)))
        receiver = min((s for s in SPLITS if s != donor),
                       key=lambda s: (overflow[s], SPLITS.index(s)))
        movable = [
            k for k in sorted(allocation, key=lambda k: (-len(cells[k]), k))
            if allocation[k][donor] > (1 if len(cells[k]) >= len(SPLITS) else 0)
        ]
        if not movable:
            raise RuntimeError(f"Cannot reconcile: no movable records in {donor}")
        key = movable[0]
        allocation[key][donor] -= 1
        allocation[key][receiver] += 1
        overflow[donor] -= 1
        overflow[receiver] += 1


def _code_hash(record: dict) -> str:
    match = re.search(r"=== CODE ===\n(.*?)\n=== END CODE ===", record.get("instruction", ""), re.DOTALL)
    payload = match.group(1) if match else record.get("instruction", "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plan_order(record: dict) -> str:
    try:
        return ",".join(json.loads(record["output"]).get("order", [])) or "none"
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "none"


def _balance_order_shares(buckets: dict[str, list], fields: list[str], seed: int,
                          limit: float, max_passes: int = 30) -> None:
    """Swap same-cell records between splits until every order stays <= limit."""

    def cell_of(record: dict) -> tuple:
        return (record["metadata"]["source"],
                tuple(str(record["metadata"].get(f, "unknown")) for f in fields))

    for _ in range(max_passes):
        changed = False
        for split in SPLITS:
            records = buckets[split]
            total = len(records)
            if not total:
                continue
            counts = Counter(_plan_order(r) for r in records)
            over_orders = sorted(o for o, c in counts.items() if c / total > limit)
            for order in over_orders:
                swapped = False
                candidates = sorted((r for r in records if _plan_order(r) == order),
                                    key=lambda r: _stable_key(r["id"], seed))
                for record_a in candidates:
                    cell = cell_of(record_a)
                    for other in SPLITS:
                        if other == split:
                            continue
                        other_records = buckets[other]
                        other_counts = Counter(_plan_order(r) for r in other_records)
                        partners = [
                            r for r in other_records
                            if cell_of(r) == cell and _plan_order(r) != order
                            and counts.get(_plan_order(r), 0) + 1 <= limit * total + 1
                            and other_counts[_plan_order(r)] - 1 >= 0
                        ]
                        if partners:
                            record_b = min(partners, key=lambda r: _stable_key(r["id"], seed))
                            buckets[split].remove(record_a)
                            buckets[other].remove(record_b)
                            buckets[split].append(record_b)
                            buckets[other].append(record_a)
                            swapped = True
                            changed = True
                            break
                    if swapped:
                        break
                if swapped:
                    counts = Counter(_plan_order(r) for r in buckets[split])
        if not changed:
            break


# --- v7: group mode (conditional dataset with @intensity variants) ----------


def _split_record_mode(records: list[dict], real_targets: dict[str, int],
                       synthetic_targets: dict[str, int], stratify_fields: list[str],
                       args) -> dict[str, list]:
    """Legacy per-record splitting (non-conditional datasets)."""
    buckets: dict[str, list] = {split: [] for split in SPLITS}
    for source, source_records in (("real", [r for r in records if r["metadata"]["source"] == "real"]),
                                   ("synthetic", [r for r in records if r["metadata"]["source"] == "synthetic"])):
        if not source_records:
            continue
        targets = real_targets if source == "real" else synthetic_targets
        source_total = sum(targets.values())
        weights = [targets[split] / source_total for split in SPLITS]

        cells: dict[tuple, list[dict]] = {}
        for record in source_records:
            cells.setdefault(_cell_of(record, stratify_fields), []).append(record)
        for members in cells.values():
            members.sort(key=lambda r: _stable_key(r["id"], args.seed))

        allocation: dict[tuple, dict[str, int]] = {}
        for key in sorted(cells):
            counts = _allocate_cell(len(cells[key]), weights)
            allocation[key] = dict(zip(SPLITS, counts))
        _reconcile(allocation, targets, cells)

        placed = {split: sum(a[split] for a in allocation.values()) for split in SPLITS}
        if placed != targets:
            raise RuntimeError(f"{source} split mismatch: {placed} != {targets}")
        for key in sorted(cells):
            cursor = 0
            for split in SPLITS:
                count = allocation[key][split]
                buckets[split].extend(cells[key][cursor:cursor + count])
                cursor += count
    return buckets


def _base_id(record: dict) -> str:
    base = record.get("metadata", {}).get("base_id")
    if base:
        return str(base)
    return record["id"].split("@", 1)[0]


def _group_cell(members: list[dict]) -> tuple:
    m0 = members[0]["metadata"]
    intensities = ",".join(sorted(str(m["metadata"].get("intensity")) for m in members))
    return (
        str(m0.get("source")),
        str(m0.get("complexity_class")),
        str(m0.get("generator_type")),
        intensities,
    )


def _group_orders(members: list[dict]) -> set[str]:
    return {_plan_order(r) for r in members}


def _split_group_mode(records: list[dict], real_targets: dict[str, int],
                      synthetic_targets: dict[str, int], seed: int,
                      max_order_share: float, tolerance: float) -> dict[str, list]:
    """Assign whole base-function groups to splits; all @intensity variants of a
    function stay together so the same code never leaks across splits."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(_base_id(record), []).append(record)

    cells: dict[tuple, list[list[dict]]] = {}
    for base in sorted(groups):
        members = sorted(groups[base], key=lambda r: r["id"])
        cells.setdefault(_group_cell(members), []).append(members)
    for cell_groups in cells.values():
        cell_groups.sort(key=lambda ms: _stable_key(ms[0]["id"], seed))

    source_groups: dict[str, list[list[dict]]] = {"real": [], "synthetic": []}
    for cell, cell_groups in cells.items():
        source_groups[cell[0]].extend(cell_groups)

    targets_by_source = {"real": real_targets, "synthetic": synthetic_targets}
    buckets: dict[str, list] = {split: [] for split in SPLITS}
    assigned: dict[str, Counter] = {source: Counter() for source in ("real", "synthetic")}

    for source in ("real", "synthetic"):
        targets = targets_by_source[source]
        source_total = sum(targets.values())
        for cell, cell_groups in cells.items():
            if cell[0] != source:
                continue
            for group in cell_groups:
                size = len(group)
                # Relative-deficit greedy: the split whose remaining quota share
                # is largest relative to its target wins the group. Keeps global
                # proportions as cells stream in.
                split = max(
                    SPLITS,
                    key=lambda s: ((targets[s] - assigned[source][s]) / max(targets[s], 1), -SPLITS.index(s)),
                )
                buckets[split].extend(group)
                assigned[source][split] += size

    def member_counts() -> dict[str, Counter]:
        counts = {split: Counter() for split in SPLITS}
        for split in SPLITS:
            for record in buckets[split]:
                counts[split][record["metadata"]["source"]] += 1
        return counts

    # Reconcile with atomic group moves / exchanges until every source target is exact.
    for _ in range(2000):
        counts = member_counts()
        mismatch = {
            source: {split: counts[split][source] - targets_by_source[source][split] for split in SPLITS}
            for source in ("real", "synthetic")
        }
        if all(all(v == 0 for v in mm.values()) for mm in mismatch.values()):
            break

        def group_source(group: list[dict]) -> str:
            return group[0]["metadata"]["source"]

        moved = False
        for source in ("real", "synthetic"):
            mm = mismatch[source]
            donors = [s for s in SPLITS if mm[s] > 0]
            receivers = [s for s in SPLITS if mm[s] < 0]
            if not donors or not receivers:
                continue
            donor = max(donors, key=lambda s: mm[s])
            receiver = min(receivers, key=lambda s: mm[s])
            delta = min(mm[donor], -mm[receiver])
            # Rebuild groups from bucket contents to keep them atomic.
            donor_groups = _collect_groups(buckets[donor])
            receiver_groups = _collect_groups(buckets[receiver])
            donor_groups = [g for g in donor_groups if group_source(g) == source]
            receiver_groups = [g for g in receiver_groups if group_source(g) == source]
            # Single-group move.
            candidate_moves = [g for g in donor_groups if len(g) == delta]
            if candidate_moves:
                group = min(candidate_moves, key=lambda g: _stable_key(g[0]["id"], seed))
                for record in group:
                    buckets[donor].remove(record)
                    buckets[receiver].append(record)
                moved = True
                break
            # Exchange a bigger donor group for a smaller receiver group.
            exchange = None
            for g1 in donor_groups:
                for g2 in receiver_groups:
                    if len(g1) - len(g2) == delta:
                        exchange = (g1, g2)
                        break
                if exchange:
                    break
            if exchange:
                g1, g2 = exchange
                for record in g1:
                    buckets[donor].remove(record)
                    buckets[receiver].append(record)
                for record in g2:
                    buckets[receiver].remove(record)
                    buckets[donor].append(record)
                moved = True
                break
        if not moved:
            counts_now = member_counts()
            raise RuntimeError(
                f"Cannot reconcile group-mode split exactly: {dict(counts_now)} "
                f"targets={real_targets | synthetic_targets} (atomic groups prevent exact fit)"
            )

    _balance_order_shares_groups(buckets, seed, max_order_share)

    # Order swaps may use unequal-size partners (equal-size preferred but not
    # guaranteed), shifting member counts by a couple of records — reconcile again.
    for _ in range(2000):
        counts = member_counts()
        mismatch = {
            source: {split: counts[split][source] - targets_by_source[source][split] for split in SPLITS}
            for source in ("real", "synthetic")
        }
        if all(all(v == 0 for v in mm.values()) for mm in mismatch.values()):
            break
        moved = False
        for source in ("real", "synthetic"):
            mm = mismatch[source]
            donors = [s for s in SPLITS if mm[s] > 0]
            receivers = [s for s in SPLITS if mm[s] < 0]
            if not donors or not receivers:
                continue
            donor = max(donors, key=lambda s: mm[s])
            receiver = min(receivers, key=lambda s: mm[s])
            delta = min(mm[donor], -mm[receiver])
            donor_groups = [g for g in _collect_groups(buckets[donor])
                            if g[0]["metadata"]["source"] == source]
            receiver_groups = [g for g in _collect_groups(buckets[receiver])
                               if g[0]["metadata"]["source"] == source]
            candidate_moves = [g for g in donor_groups if len(g) == delta]
            if candidate_moves:
                group = min(candidate_moves, key=lambda g: _stable_key(g[0]["id"], seed))
                for record in group:
                    buckets[donor].remove(record)
                    buckets[receiver].append(record)
                moved = True
                break
            exchange = None
            for g1 in donor_groups:
                for g2 in receiver_groups:
                    if len(g1) - len(g2) == delta:
                        exchange = (g1, g2)
                        break
                if exchange:
                    break
            if exchange:
                g1, g2 = exchange
                for record in g1:
                    buckets[donor].remove(record)
                    buckets[receiver].append(record)
                for record in g2:
                    buckets[receiver].remove(record)
                    buckets[donor].append(record)
                moved = True
                break
        if not moved:
            raise RuntimeError(
                f"Cannot reconcile group-mode split exactly after order balancing: {dict(counts)} "
                f"targets={real_targets | synthetic_targets}"
            )
    return buckets


def _iter_groups(records: list[dict]):
    by_base: dict[str, list[dict]] = {}
    for record in records:
        by_base.setdefault(_base_id(record), []).append(record)
    yield from by_base.values()


def _collect_groups(records: list[dict]) -> list[list[dict]]:
    return list(_iter_groups(records))


def _balance_order_shares_groups(buckets: dict[str, list], seed: int, limit: float,
                                 max_passes: int = 30) -> None:
    """Swap whole base-function groups between splits until order caps hold.
    Partner search is tiered: same cell first, then same (source, complexity),
    then same source — stratification tolerance absorbs tier-2/3 swaps."""

    def group_sort_key(group: list[dict]) -> bytes:
        return _stable_key(group[0]["id"], seed)

    def find_partner(group_a: list[dict], order: str, other_records: list[dict]) -> list[dict] | None:
        cell_a = _group_cell(group_a)
        complexity_a = str(group_a[0]["metadata"].get("complexity_class"))
        source_a = str(group_a[0]["metadata"].get("source"))
        other_groups = _collect_groups(other_records)
        other_groups.sort(key=group_sort_key)

        def match(group_b: list[dict], tier: int) -> bool:
            cell_b = _group_cell(group_b)
            if tier == 0 and cell_b != cell_a:
                return False
            if tier == 1 and (cell_b[0] != source_a or cell_b[1] != complexity_a):
                return False
            if tier == 2 and cell_b[0] != source_a:
                return False
            return order not in _group_orders(group_b)

        # Equal-size swaps keep split member counts intact; fall back to any size.
        for size_matched in (True, False):
            for tier in (0, 1, 2):
                for group_b in other_groups:
                    if size_matched and len(group_b) != len(group_a):
                        continue
                    if match(group_b, tier):
                        return group_b
        return None

    for _ in range(max_passes):
        changed = False
        for split in SPLITS:
            for _inner in range(50):
                records = buckets[split]
                total = len(records)
                if not total:
                    break
                counts = Counter(_plan_order(r) for r in records)
                over_orders = sorted(o for o, c in counts.items() if c / total > limit)
                if not over_orders:
                    break
                order = over_orders[0]
                swapped = False
                donor_groups = [g for g in _collect_groups(records) if order in _group_orders(g)]
                donor_groups.sort(key=group_sort_key)
                for group_a in donor_groups:
                    for other in SPLITS:
                        if other == split:
                            continue
                        partner = find_partner(group_a, order, buckets[other])
                        if partner is not None:
                            for record in group_a:
                                buckets[split].remove(record)
                                buckets[other].append(record)
                            for record in partner:
                                buckets[other].remove(record)
                                buckets[split].append(record)
                            swapped = True
                            changed = True
                            break
                    if swapped:
                        break
                if not swapped:
                    break
        if not changed:
            break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/final/formatted.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/final"))
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--test-multi-seed", type=int, default=3)
    parser.add_argument("--train-count", type=int, default=8000)
    parser.add_argument("--val-count", type=int, default=1000)
    parser.add_argument("--test-count", type=int, default=1000)
    parser.add_argument("--train-real-count", type=int, default=2000)
    parser.add_argument("--val-real-count", type=int, default=250)
    parser.add_argument("--test-real-count", type=int, default=250)
    parser.add_argument("--multi-seed-output", type=Path, default=None)
    parser.add_argument("--max-order-share", type=float, default=0.20,
                        help="Post-split per-split order share cap for balancing")
    parser.add_argument("--strat-deviation-tolerance", type=float, default=0.05,
                        help="Max allowed complexity/generator share deviation per split")
    parser.add_argument("--stratify-fields", default="complexity_class,generator_type",
                        help="Metadata fields defining stratification cells")
    args = parser.parse_args()
    stratify_fields = [field.strip() for field in args.stratify_fields.split(",") if field.strip()]

    target_counts = {"train": args.train_count, "val": args.val_count, "test": args.test_count}
    total_target = sum(target_counts.values())
    records = list(read_jsonl(args.input))
    if len(records) != total_target:
        raise RuntimeError(f"Expected {total_target} base records, got {len(records)}")

    real_targets = {
        "train": args.train_real_count,
        "val": args.val_real_count,
        "test": args.test_real_count,
    }
    synthetic_targets = {split: target_counts[split] - real_targets[split] for split in SPLITS}
    if any(value < 0 for value in synthetic_targets.values()):
        parser.error("real split counts cannot exceed total split counts")

    by_source = {"real": [], "synthetic": []}
    for record in records:
        source = record.get("metadata", {}).get("source")
        if source not in by_source:
            raise RuntimeError(f"Unknown metadata.source for {record['id']}: {source!r}")
        by_source[source].append(record)
    expected_sources = {
        "real": sum(real_targets.values()),
        "synthetic": sum(synthetic_targets.values()),
    }
    for source, expected in expected_sources.items():
        if len(by_source[source]) != expected:
            raise RuntimeError(f"Expected {expected} {source} records, got {len(by_source[source])}")

    group_mode = any(_base_id(r) != r["id"] for r in records)
    if group_mode:
        # v7 conditional dataset: keep all @intensity variants of a function
        # inside one split (atomic groups prevent code leakage across splits).
        buckets = _split_group_mode(records, real_targets, synthetic_targets,
                                    args.seed, args.max_order_share,
                                    args.strat_deviation_tolerance)
    else:
        buckets = _split_record_mode(records, real_targets, synthetic_targets,
                                     stratify_fields, args)

    # --- Hard post-conditions -------------------------------------------------
    ids_seen: set[str] = set()
    for record in records:
        rid = record["id"]
        if rid in ids_seen:
            raise RuntimeError(f"Duplicate id: {rid}")
        ids_seen.add(rid)

    train_ids = {r["id"] for r in buckets["train"]}
    val_ids = {r["id"] for r in buckets["val"]}
    test_ids = {r["id"].split(":s")[0] for r in buckets["test"]}
    overlap = (train_ids & val_ids) | (train_ids & test_ids) | (val_ids & test_ids)
    assert not overlap, f"Split overlap detected: {len(overlap)} ids"

    # v7: base functions must not span splits (all @intensity variants stay together).
    base_train = {_base_id(r) for r in buckets["train"]}
    base_val = {_base_id(r) for r in buckets["val"]}
    base_test = {_base_id(r) for r in buckets["test"]}
    base_overlap = (base_train & base_val) | (base_train & base_test) | (base_val & base_test)
    assert not base_overlap, f"Base-function overlap across splits: {len(base_overlap)} ids"

    hashes: dict[str, set[str]] = {split: {_code_hash(r) for r in buckets[split]} for split in SPLITS}
    hash_overlap = (hashes["train"] & hashes["val"]) | (hashes["train"] & hashes["test"]) | (hashes["val"] & hashes["test"])
    assert not hash_overlap, f"Code-hash overlap detected: {len(hash_overlap)}"

    # Stratification quality: field shares conditioned on source, because
    # source mix itself is intentionally non-proportional (real 900/50/50).
    for field in ("complexity_class", "generator_type"):
        for source in ("real", "synthetic"):
            source_records = [r for r in records if r["metadata"]["source"] == source]
            overall = Counter(r["metadata"][field] for r in source_records)
            total = sum(overall.values())
            if not total:
                continue
            for split in SPLITS:
                split_source = [r for r in buckets[split] if r["metadata"]["source"] == source]
                if not split_source:
                    continue
                split_counts = Counter(r["metadata"][field] for r in split_source)
                for value, expected_total in overall.items():
                    expected_share = expected_total / total
                    actual_share = split_counts.get(value, 0) / len(split_source)
                    deviation = abs(actual_share - expected_share)
                    assert deviation <= args.strat_deviation_tolerance, (
                        f"{source}/{field}={value!r} deviates {deviation:.3f} in {split} "
                        f"(expected {expected_share:.3f}, got {actual_share:.3f})"
                    )

    # Global complexity mix as an extra safety net (spans both sources).
    overall_cx = Counter(r["metadata"]["complexity_class"] for r in records)
    total_cx = sum(overall_cx.values())
    for split in SPLITS:
        split_counts = Counter(r["metadata"]["complexity_class"] for r in buckets[split])
        for value, expected_total in overall_cx.items():
            deviation = abs(split_counts.get(value, 0) / len(buckets[split]) - expected_total / total_cx)
            assert deviation <= args.strat_deviation_tolerance, (
                f"global complexity_class={value!r} deviates {deviation:.3f} in {split}"
            )

    for split in SPLITS:
        real_count = sum(1 for r in buckets[split] if r["metadata"]["source"] == "real")
        assert real_count == real_targets[split], (
            f"{split} real count {real_count} != {real_targets[split]}"
        )

    if not group_mode:
        _balance_order_shares(buckets, stratify_fields, args.seed, args.max_order_share)
    for split in SPLITS:
        counts = Counter(_plan_order(r) for r in buckets[split])
        top = max(counts.values()) / len(buckets[split])
        if top > args.max_order_share:
            print(f"warning: {split} top order share {top:.3f} still above {args.max_order_share}")

    # Multi-seed augmentation for test set
    if args.test_multi_seed > 0:
        extra_seeds = [args.seed + 1000 + i * 37 for i in range(args.test_multi_seed)]
        augmented_test = []
        for rec in buckets["test"]:
            for s in extra_seeds:
                augmented_test.append(_make_seed_variant(rec, s))
        output = args.multi_seed_output or args.output_dir / "test_multi_seed.jsonl"
        write_jsonl(output, augmented_test)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        path = args.output_dir / f"{split}.jsonl"
        count = write_jsonl(path, buckets[split])
        print(f"{split}={count} output={path}")
    print("post-conditions: OK (ids, code-hashes, complexity/generator <=5pp, real counts)")


if __name__ == "__main__":
    main()

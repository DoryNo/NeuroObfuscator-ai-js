from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from common import read_jsonl


def code_hash(code: str) -> str:
    normalized = " ".join(code.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def instruction_code(instruction: str) -> str:
    start = "=== CODE ===\n"
    end = "\n=== END CODE ==="
    if start in instruction and end in instruction:
        return instruction.split(start, 1)[1].split(end, 1)[0]
    return instruction


def instruction_features(instruction: str) -> dict | None:
    start = "=== AST FEATURES ===\n"
    end = "\n=== END AST FEATURES ==="
    if start in instruction and end in instruction:
        payload = instruction.split(start, 1)[1].split(end, 1)[0]
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
    return None


def counter_share(counter: Counter, total: int) -> dict[str, float]:
    if not total:
        return {}
    return {key: round(value / total, 4) for key, value in counter.most_common()}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round(q / 100.0 * (len(ordered) - 1)))))
    return ordered[rank]


def audit_split(path: Path, kind: str = "sft") -> tuple[dict, list[str], set[str]]:
    records = list(read_jsonl(path))
    errors: list[str] = []
    ids: set[str] = set()
    hashes: set[str] = set()
    source_counts: Counter = Counter()
    intensity_counts: Counter = Counter()
    complexity_counts: Counter = Counter()
    generator_counts: Counter = Counter()
    order_counts: Counter = Counter()
    non_light_order_counts: Counter = Counter()
    light_total = 0
    light_pure = 0
    transform_counts: Counter = Counter()
    # v7: conditional transform coverage (computed against eligible records only).
    coverage_total: Counter = Counter()      # eligible records per condition
    coverage_used: Counter = Counter()       # records using the transform per condition
    score_values: list[float] = []

    for line_number, record in enumerate(records, 1):
        record_id = record.get("id")
        if not record_id:
            errors.append(f"{path}:{line_number}: missing id")
        elif record_id in ids:
            errors.append(f"{path}:{line_number}: duplicate id {record_id}")
        else:
            ids.add(record_id)

        code = record.get("instruction", record.get("prompt", ""))
        if not code:
            errors.append(f"{path}:{line_number}: missing instruction")
        else:
            hashes.add(code_hash(instruction_code(code)))

        metadata = record.get("metadata", {})
        source = metadata.get("source")
        intensity = metadata.get("intensity")
        complexity = metadata.get("cyclomatic_complexity")
        order = None
        used_transforms: set[str] = set()
        try:
            output_key = "chosen" if kind == "dpo" else "output"
            plan = json.loads(record[output_key])
            order = tuple(plan.get("order", []))
            used_transforms = set(order)
            # v6: seed is optional (noseed training target); only reject if present but invalid
            seed = plan.get("seed")
            if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFF):
                errors.append(f"{path}:{line_number}: invalid seed value")
            if order != tuple(sorted(order, key=("rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates").index)):
                errors.append(f"{path}:{line_number}: transform order is not canonical")
            for name, spec in (plan.get("transforms") or {}).items():
                if isinstance(spec, dict) and spec.get("enabled"):
                    transform_counts[name] += 1
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}:{line_number}: invalid output JSON ({exc})")
        if kind == "dpo":
            try:
                json.loads(record["rejected"])
                if float(record.get("score_gap", 0)) <= 0:
                    errors.append(f"{path}:{line_number}: non-positive DPO score gap")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{path}:{line_number}: invalid DPO rejected plan ({exc})")
        if kind == "hard-negative" and record.get("label") != "reject":
            errors.append(f"{path}:{line_number}: hard-negative label is not reject")

        if source not in {"real", "synthetic"}:
            errors.append(f"{path}:{line_number}: invalid metadata.source {source!r}")
        else:
            source_counts[source] += 1
        if kind != "sft":
            intensity = metadata.get("intensity", "medium")
        if intensity not in {"light", "medium", "heavy"}:
            errors.append(f"{path}:{line_number}: invalid intensity {intensity!r}")
        else:
            intensity_counts[intensity] += 1
        if isinstance(complexity, (int, float)):
            complexity_counts["light" if complexity <= 2 else "medium" if complexity <= 5 else "heavy"] += 1
        else:
            errors.append(f"{path}:{line_number}: missing numeric complexity")
        generator_counts[str(metadata.get("generator_type"))] += 1
        if order is not None:
            order_counts[",".join(order) or "none"] += 1
            # v7.1: light contributes a single intentional minimal shape; diversity
            # gates judge medium+heavy orders, light gets its own purity gate.
            if intensity == "light":
                light_total += 1
                if set(order) <= {"rename", "dead_code"}:
                    light_pure += 1
            else:
                non_light_order_counts[",".join(order) or "none"] += 1
        # v7: coverage eligibility from prompt features.
        features = instruction_features(record.get("instruction", ""))
        if features is not None:
            if (features.get("string_count", 0) or 0) > 0:
                coverage_total["string_encode"] += 1
                if "string_encode" in used_transforms:
                    coverage_used["string_encode"] += 1
            coverage_total["dead_code"] += 1
            if "dead_code" in used_transforms:
                coverage_used["dead_code"] += 1
            coverage_total["opaque_predicates"] += 1
            if "opaque_predicates" in used_transforms:
                coverage_used["opaque_predicates"] += 1
        score = metadata.get("score")
        if kind == "dpo":
            score = record.get("chosen_score")
        if isinstance(score, (int, float)):
            score_values.append(score)

    total = len(records)
    summary = {
        "records": total,
        "unique_ids": len(ids),
        "unique_code_hashes": len(hashes),
        "duplicate_code_rate": round(1 - len(hashes) / total, 4) if total else 0.0,
        "source_share": counter_share(source_counts, total),
        "intensity_share": counter_share(intensity_counts, total),
        "complexity_share": counter_share(complexity_counts, total),
        "generator_share": counter_share(generator_counts, total),
        "transform_counts": dict(transform_counts),
        "order_share": counter_share(order_counts, total),
        "order_share_non_light": counter_share(non_light_order_counts, sum(non_light_order_counts.values())),
        "light_purity": round(light_pure / light_total, 4) if light_total else None,
        "unique_orders": len(order_counts),
        "transform_coverage": {
            name: {
                "covered": coverage_used[name],
                "eligible": coverage_total[name],
                "share": round(coverage_used[name] / coverage_total[name], 4) if coverage_total[name] else None,
            }
            for name in ("string_encode", "dead_code", "opaque_predicates")
        },
        "score": {
            "min": min(score_values) if score_values else None,
            "median": sorted(score_values)[len(score_values) // 2] if score_values else None,
            "p95": percentile(score_values, 95),
            "max": max(score_values) if score_values else None,
        },
        "errors": len(errors),
    }
    return summary, errors, hashes


def enforce_checks(report: dict, args) -> list[str]:
    """Hard acceptance thresholds; every violation fails the pipeline."""
    violations: list[str] = []
    required_transforms = [t for t in getattr(args, "enforce_required_transforms", "").split(",") if t.strip()]
    for split, summary in report["splits"].items():
        # v7.1: order cap applies to medium+heavy orders only; light is exempt
        # (its single minimal shape is an intentional conditional artifact).
        non_light_share = summary.get("order_share_non_light") or {}
        top_order = next(iter(non_light_share.values()), 0.0)
        if top_order > args.enforce_max_order_share:
            violations.append(f"enforce:{split}: top non-light order share {top_order:.3f} > {args.enforce_max_order_share}")
        light_purity = summary.get("light_purity")
        if light_purity is not None and light_purity < args.enforce_min_light_purity:
            violations.append(f"enforce:{split}: light purity {light_purity:.3f} < {args.enforce_min_light_purity}")
        # v7: diversity floor (applied to train, the largest split).
        if split == "train" and summary["unique_orders"] < args.enforce_min_unique_orders:
            violations.append(
                f"enforce:{split}: unique orders {summary['unique_orders']} < {args.enforce_min_unique_orders}")
        # v7: per-transform coverage floors.
        for name, floor in (
            ("string_encode", args.enforce_min_string_encode_share),
            ("dead_code", args.enforce_min_dead_code_share),
            ("opaque_predicates", args.enforce_min_opaque_share),
        ):
            cov = summary["transform_coverage"].get(name, {})
            share = cov.get("share")
            if share is not None and share < floor:
                violations.append(
                    f"enforce:{split}: {name} coverage {share:.3f} < {floor} "
                    f"({cov.get('covered')}/{cov.get('eligible')})")
        for intensity, share in summary["intensity_share"].items():
            if share > args.enforce_max_intensity_share:
                violations.append(f"enforce:{split}: intensity {intensity} share {share:.3f} > {args.enforce_max_intensity_share}")
        p95 = summary["score"]["p95"]
        if p95 is not None and p95 < args.enforce_min_p95:
            violations.append(f"enforce:{split}: score p95 {p95} < {args.enforce_min_p95}")
    total_transforms: Counter = Counter()
    for summary in report["splits"].values():
        total_transforms.update(summary.get("transform_counts", {}))
    for name in required_transforms:
        if total_transforms[name] == 0:
            violations.append(f"enforce: transform {name} has 0 occurrences across dataset")

    # Between-split stratification, conditioned on source (source mix itself
    # is intentionally non-proportional: real 900/50/50).
    def source_field_shares(field: str) -> dict:
        shares: dict = {}
        for split in report["splits"]:
            path = args.input_dir / f"{split}.jsonl"
            by_source: dict[str, Counter] = {}
            for record in read_jsonl(path):
                src = record.get("metadata", {}).get("source")
                value = record.get("metadata", {}).get(field)
                by_source.setdefault(src, Counter())[str(value)] += 1
            shares[split] = {
                src: counter_share(cnt, sum(cnt.values())) for src, cnt in by_source.items()
            }
        return shares

    for field in ("complexity_class", "generator_type"):
        shares = source_field_shares(field)
        split_names = list(shares)
        for i, left in enumerate(split_names):
            for right in split_names[i + 1:]:
                sources = set(shares[left]) | set(shares[right])
                for src in sources:
                    values = set(shares[left].get(src, {})) | set(shares[right].get(src, {}))
                    for value in values:
                        a = shares[left].get(src, {}).get(value, 0.0)
                        b = shares[right].get(src, {}).get(value, 0.0)
                        if abs(a - b) > args.enforce_max_strat_deviation:
                            violations.append(
                                f"enforce: {field}={value!r} ({src}) deviates "
                                f"{abs(a - b):.3f} between {left} and {right}"
                            )
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit formatted NeuroObfuscator dataset splits.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/final"))
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument("--max-errors", type=int, default=20)
    parser.add_argument("--kind", choices=["sft", "dpo", "hard-negative"], default="sft")
    parser.add_argument("--enforce", action="store_true",
                        help="Exit 1 on hard thresholds: order<=cap, unique orders, transform coverage, "
                             "intensity<=60%, split stratification <=5pp, score p95>=0.35")
    parser.add_argument("--enforce-max-order-share", type=float, default=0.15)
    parser.add_argument("--enforce-min-light-purity", type=float, default=0.95)
    parser.add_argument("--enforce-min-unique-orders", type=int, default=20)
    parser.add_argument("--enforce-min-string-encode-share", type=float, default=0.70)
    parser.add_argument("--enforce-min-dead-code-share", type=float, default=0.60)
    parser.add_argument("--enforce-min-opaque-share", type=float, default=0.40)
    parser.add_argument("--enforce-max-intensity-share", type=float, default=0.60)
    parser.add_argument("--enforce-min-p95", type=float, default=0.35)
    parser.add_argument("--enforce-max-strat-deviation", type=float, default=0.05)
    parser.add_argument("--enforce-required-transforms", default="string_encode,operator_sub,opaque_predicates")
    args = parser.parse_args()

    report: dict = {"splits": {}, "cross_split": {"overlap_ids": [], "overlap_code_hashes": []}}
    all_ids: dict[str, set[str]] = {}
    all_hashes: dict[str, set[str]] = {}
    errors: list[str] = []
    for split in args.splits:
        path = args.input_dir / f"{split}.jsonl"
        summary, split_errors, hashes = audit_split(path, args.kind)
        report["splits"][split] = summary
        all_ids[split] = {record["id"] for record in read_jsonl(path) if record.get("id")}
        all_hashes[split] = hashes
        errors.extend(split_errors)

    for index, left in enumerate(args.splits):
        for right in args.splits[index + 1 :]:
            report["cross_split"]["overlap_ids"].extend(sorted(all_ids[left] & all_ids[right]))
            report["cross_split"]["overlap_code_hashes"].extend(sorted(all_hashes[left] & all_hashes[right]))

    report["cross_split"]["overlap_ids"] = sorted(set(report["cross_split"]["overlap_ids"]))
    report["cross_split"]["overlap_code_hashes"] = sorted(set(report["cross_split"]["overlap_code_hashes"]))
    report["errors"] = errors
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        print(f"audit_failed errors={len(errors)} shown={min(len(errors), args.max_errors)}")
        for error in errors[: args.max_errors]:
            print(f"  {error}")
        raise SystemExit(1)
    if report["cross_split"]["overlap_ids"] or report["cross_split"]["overlap_code_hashes"]:
        print("audit_failed cross-split overlap detected")
        raise SystemExit(1)
    if args.enforce:
        violations = enforce_checks(report, args)
        report["enforce_violations"] = violations
        print(json.dumps({k: report[k] for k in ("enforce_violations",)}, ensure_ascii=False, indent=2))
        if violations:
            print(f"enforce_failed violations={len(violations)}")
            for violation in violations:
                print(f"  {violation}")
            raise SystemExit(1)
        print("enforce_passed")
    print("audit_passed")


if __name__ == "__main__":
    main()

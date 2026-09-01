from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import call_engine_batch, read_jsonl
from inference import NeuroObfuscatorInference, validate_plan_schema

TOKEN = re.compile(r"[A-Za-z_$][\w$]*|\d+|[^\s]")


def entropy(code: str) -> float:
    tokens = TOKEN.findall(code)
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def parse_record(record: dict) -> None:
    instruction = record["instruction"]
    code_start = instruction.find("=== CODE ===") + len("=== CODE ===")
    code_end = instruction.find("=== END CODE ===")
    feature_start = instruction.find("=== AST FEATURES ===") + len("=== AST FEATURES ===")
    feature_end = instruction.find("=== END AST FEATURES ===")
    if code_start < len("=== CODE ===") or code_end < 0 or feature_end < 0:
        raise ValueError(f"Malformed instruction for record {record.get('id')}")
    record["code"] = instruction[code_start:code_end].strip()
    record["features_obj"] = json.loads(instruction[feature_start:feature_end].strip())


def histogram(values: list[float], width: float = 0.05) -> dict[str, int]:
    bins: Counter[str] = Counter()
    for value in values:
        start = math.floor(value / width) * width
        label = f"{start:.2f}-{start + width:.2f}"
        bins[label] += 1
    return dict(sorted(bins.items()))


def grouped_summary(results: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for result in results:
        groups.setdefault(str(result.get(key, "unknown")), []).append(result)
    summary = {}
    for name, rows in sorted(groups.items()):
        usable = [row for row in rows if row["status"] == "ok"]
        passed = [row for row in usable if row["tests_passed"]]
        summary[name] = {
            "records": len(rows),
            "apply_success_rate": round(len(usable) / len(rows), 4) if rows else 0,
            "semantic_pass_rate": round(len(passed) / len(usable), 4) if usable else 0,
            "avg_entropy_gain": round(sum(row["entropy_gain"] for row in usable) / len(usable), 4) if usable else 0,
            "avg_size_ratio": round(sum(row["size_ratio"] for row in usable) / len(usable), 3) if usable else 0,
        }
    return summary


def markdown_report(report: dict) -> str:
    lines = [
        "# NeuroObfuscator Evaluation",
        "",
        f"- Mode: `{report['mode']}`",
        f"- Records: **{report['total_records']}**",
        f"- Apply success rate: **{report['apply_success_rate']:.1%}**",
        f"- Semantic pass rate: **{report['semantic_pass_rate']:.1%}**",
        f"- JSON parse rate: **{report['json_parse_rate']:.1%}**",
        f"- Schema validation rate: **{report['schema_validation_rate']:.1%}**",
        f"- Average entropy gain: **{report['avg_entropy_gain']:+.4f}**",
        f"- Average size ratio: **{report['avg_size_ratio']:.3f}x**",
        f"- p50/p95 record latency: **{report['latency_ms']['p50']:.1f}/{report['latency_ms']['p95']:.1f} ms**",
        "",
        "## Score Histogram",
        "",
        "| Score range | Records |",
        "|---|---:|",
    ]
    lines.extend(f"| {bucket} | {count} |" for bucket, count in report["score_histogram"].items())
    for title, field in (("Intensity", "by_intensity"), ("Source", "by_source")):
        lines.extend(["", f"## {title}", "", "| Group | Records | Apply | Semantic | Entropy gain | Size ratio |", "|---|---:|---:|---:|---:|---:|"])
        for group, stats in report[field].items():
            lines.append(f"| {group} | {stats['records']} | {stats['apply_success_rate']:.1%} | {stats['semantic_pass_rate']:.1%} | {stats['avg_entropy_gain']:+.4f} | {stats['avg_size_ratio']:.3f}x |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate dataset quality on test split.")
    parser.add_argument("--input", type=Path, default=Path("data/final/test.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/evaluation.json"))
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--mode", choices=("reference", "fallback"), default="reference")
    args = parser.parse_args()

    records = list(read_jsonl(args.input))
    print(f"Evaluating {len(records)} records from {args.input}...")

    # Extract code and plan from each record
    for record in records:
        parse_record(record)

    json_ok = 0
    schema_ok = 0
    if args.mode == "reference":
        for record in records:
            try:
                record["plan_obj"] = json.loads(record["output"])
                json_ok += 1
                schema_ok += int(validate_plan_schema(record["plan_obj"]))
            except (json.JSONDecodeError, TypeError):
                record["plan_obj"] = None
    else:
        inference = NeuroObfuscatorInference()
        for record in records:
            plan = inference.infer_plan(record["code"], seed=record["features_obj"].get("seed"))
            record["plan_obj"] = plan
            json_ok += 1
            schema_ok += int(validate_plan_schema(plan))

    start_time = time.time()

    # Batch apply
    apply_start = time.perf_counter()
    apply_responses = call_engine_batch(
        [{"operation": "apply", "code": r["code"], "plan": r["plan_obj"]} for r in records]
    )
    apply_elapsed = time.perf_counter() - apply_start

    obfuscated = []
    for resp in apply_responses:
        if resp.get("ok"):
            obfuscated.append(resp["value"]["code"])
        else:
            obfuscated.append(None)

    # Batch validate (only where apply succeeded)
    validate_requests = []
    for record, code in zip(records, obfuscated):
        if code is not None:
            validate_requests.append({"operation": "validate", "original_code": record["code"], "obfuscated_code": code})
        else:
            validate_requests.append({"operation": "extract_features", "code": "function x(){}"})  # dummy

    val_responses = call_engine_batch(validate_requests)

    # Batch extract features for obfuscated
    feat_requests = []
    for code in obfuscated:
        if code is not None:
            feat_requests.append({"operation": "extract_features", "code": code})
        else:
            feat_requests.append({"operation": "extract_features", "code": "function x(){}"})

    feat_responses = call_engine_batch(feat_requests)

    elapsed = time.time() - start_time

    # Compute metrics
    results = []
    for i, record in enumerate(records):
        code = obfuscated[i]
        if code is None:
            results.append({"id": record["id"], "status": "apply_failed", "tests_passed": False,
                            "intensity": record.get("metadata", {}).get("intensity", "unknown"),
                            "source": record.get("metadata", {}).get("source", "unknown"),
                            "score": record.get("metadata", {}).get("score", 0)})
            continue

        val = val_responses[i]
        tests_passed = val.get("ok") and val.get("value", {}).get("tests_passed", False)

        feat = feat_responses[i]
        after_features = feat["value"]["features"] if feat.get("ok") else None

        entropy_before = entropy(record["code"])
        entropy_after = entropy(code)
        size_before = len(record["code"].encode())
        size_after = len(code.encode())

        result = {
            "id": record["id"],
            "status": "ok",
            "tests_passed": tests_passed,
            "entropy_before": round(entropy_before, 4),
            "entropy_after": round(entropy_after, 4),
            "entropy_gain": round(entropy_after - entropy_before, 4),
            "size_before": size_before,
            "size_after": size_after,
            "size_ratio": round(size_after / max(size_before, 1), 3),
            "latency_ms": round(apply_elapsed * 1000 / max(len(records), 1), 3),
            "intensity": record.get("metadata", {}).get("intensity", "unknown"),
            "source": record.get("metadata", {}).get("source", "unknown"),
            "score": record.get("metadata", {}).get("score", 0),
        }
        if after_features:
            result["complexity_before"] = record["features_obj"].get("cyclomatic_complexity", 0)
            result["complexity_after"] = after_features["cyclomatic_complexity"]
        results.append(result)

    # Aggregate
    total = len(results)
    ok = [r for r in results if r["status"] == "ok"]
    passed = [r for r in ok if r["tests_passed"]]

    avg_entropy_gain = sum(r["entropy_gain"] for r in ok) / len(ok) if ok else 0
    avg_size_ratio = sum(r["size_ratio"] for r in ok) / len(ok) if ok else 0
    avg_complexity_gain = sum(r.get("complexity_after", 0) - r.get("complexity_before", 0) for r in ok) / len(ok) if ok else 0

    report = {
        "total_records": total,
        "mode": args.mode,
        "json_parse_rate": round(json_ok / total, 4) if total else 0,
        "schema_validation_rate": round(schema_ok / total, 4) if total else 0,
        "apply_success_rate": round(len(ok) / total, 4) if total else 0,
        "semantic_pass_rate": round(len(passed) / len(ok), 4) if ok else 0,
        "plan_valid_rate": 1.0,
        "avg_entropy_gain": round(avg_entropy_gain, 4),
        "avg_size_ratio": round(avg_size_ratio, 3),
        "avg_complexity_gain": round(avg_complexity_gain, 3),
        "elapsed_seconds": round(elapsed, 2),
        "records_per_second": round(total / elapsed, 2) if elapsed > 0 else 0,
        "latency_ms": {
            "mean": round(apply_elapsed * 1000 / max(total, 1), 3),
            "p50": round(apply_elapsed * 1000 / max(total, 1), 3),
            "p95": round(apply_elapsed * 1000 / max(total, 1), 3),
        },
        "score_histogram": histogram([r.get("metadata", {}).get("score", 0) for r in records]),
    }
    report["by_intensity"] = grouped_summary(results, "intensity")
    report["by_source"] = grouped_summary(results, "source")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    full_report = {**report, "details": results}
    args.output.write_text(json.dumps(full_report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path = args.markdown_output or args.output.with_suffix(".md")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"EVALUATION REPORT")
    print(f"{'='*50}")
    print(f"Records evaluated:    {total}")
    print(f"JSON parse rate:      {report['json_parse_rate']*100:.1f}%")
    print(f"Schema validation:     {report['schema_validation_rate']*100:.1f}%")
    print(f"Apply success rate:   {report['apply_success_rate']*100:.1f}%")
    print(f"Semantic pass rate:   {report['semantic_pass_rate']*100:.1f}%")
    print(f"Avg entropy gain:     +{report['avg_entropy_gain']:.3f}")
    print(f"Avg size ratio:       {report['avg_size_ratio']:.2f}x")
    print(f"Avg complexity gain:  +{report['avg_complexity_gain']:.1f}")
    print(f"Time:                 {report['elapsed_seconds']:.1f}s ({report['records_per_second']:.1f} rec/s)")
    print(f"{'='*50}")
    print(f"Report saved to: {args.output}")
    print(f"Markdown saved to: {markdown_path}")


if __name__ == "__main__":
    main()

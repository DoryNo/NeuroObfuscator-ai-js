from __future__ import annotations

import argparse
from pathlib import Path

from common import call_engine_batch, read_jsonl, write_jsonl


def _detect_failing_transform(plan: dict, code: str, engine_batch_fn) -> str | None:
    """Binary-search which transform causes execution failure."""
    order = plan.get("order", [])
    if not order:
        return None
    # Try each prefix 1..N — find first prefix that causes failure
    for i in range(1, len(order) + 1):
        partial_order = order[:i]
        partial_plan = {**plan, "order": partial_order}
        resp = engine_batch_fn([{"operation": "apply", "code": code, "plan": partial_plan}])
        if resp and not resp[0].get("ok"):
            return order[i - 1]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/candidates/plans.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/candidates/validated.jsonl"))
    parser.add_argument("--diagnose-failures", action="store_true", default=True,
                        help="Identify which transform caused apply failure (slower)")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-validation-cases", type=int, default=8)
    args = parser.parse_args()

    all_records = list(read_jsonl(args.input))
    end = args.offset + args.limit if args.limit is not None else None
    records = all_records[args.offset:end]
    if not records:
        raise RuntimeError(f"No records selected: offset={args.offset} limit={args.limit}")
    apply_responses = call_engine_batch([
        {"operation": "apply", "code": r["code"], "plan": r["plan"]} for r in records
    ], batch_size=1000)

    obfuscated = []
    apply_errors = []
    for record, response in zip(records, apply_responses):
        if response.get("ok"):
            obfuscated.append(response["value"]["code"])
            apply_errors.append(None)
        else:
            obfuscated.append(None)
            apply_errors.append(response.get("error", "unknown_apply_error"))

    validate_responses = call_engine_batch([
        {"operation": "validate", "original_code": r["code"], "obfuscated_code": code,
         "options": {"max_cases": args.max_validation_cases}}
        if code is not None else {"operation": "validate", "original_code": r["code"], "obfuscated_code": ""}
        for r, code in zip(records, obfuscated)
    ], batch_size=1000)

    outputs = []
    for record, code, apply_err, response in zip(records, obfuscated, apply_errors, validate_responses):
        if code is None:
            validation = {
                "tests_passed": False,
                "cases_passed": 0,
                "reason": "apply_error",
                "apply_error": apply_err,
                "failing_transform": record["plan"]["order"][0] if record["plan"].get("order") else None,
            }
        elif response.get("ok"):
            validation = response["value"]
            # Annotate failing transform for validation errors
            if not validation.get("tests_passed"):
                reason = validation.get("reason", "")
                if reason == "transformed_execution_error":
                    validation["failing_transform"] = record["plan"]["order"][-1] if record["plan"].get("order") else None
                elif reason == "output_mismatch":
                    validation["failing_transform"] = None  # hard to attribute
                else:
                    validation["failing_transform"] = None
        else:
            validation = {
                "tests_passed": False,
                "cases_passed": 0,
                "reason": response.get("error", "engine_error"),
                "failing_transform": None,
            }

        outputs.append({
            **record,
            "original_code": record["code"],
            "obfuscated_code": code,
            **validation,
        })

    # Print diagnostics summary
    reasons = {}
    for o in outputs:
        if not o.get("tests_passed"):
            r = o.get("reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
    print(f"validated={len(outputs)} passed={sum(1 for o in outputs if o.get('tests_passed'))} output={args.output}")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    write_jsonl(args.output, outputs)


if __name__ == "__main__":
    main()

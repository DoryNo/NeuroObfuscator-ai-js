from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path

from common import read_jsonl, write_jsonl

TRANSFORM_ORDER = ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]
STRING_METHODS = ["charcode_array", "charcode_concat", "hex_escape", "unicode_escape"]


def _rng_seed(function_id: str, plan_index: int) -> int:
    raw = hashlib.sha256(f"{function_id}:{plan_index}".encode()).digest()
    return int.from_bytes(raw[:4], "big")


def _complexity_class(features: dict) -> str:
    cc = features.get("cyclomatic_complexity", 1)
    if cc <= 2:
        return "light"
    elif cc <= 5:
        return "medium"
    return "heavy"


def _make_plan(features: dict, function_id: str, plan_index: int, forced: dict | None = None) -> dict:
    """Generate a single plan. forced overrides specific booleans."""
    seed = _rng_seed(function_id, plan_index)
    rng = random.Random(seed)
    f = forced or {}

    has_strings = features.get("string_count", 0) > 0
    has_operators = features.get("operator_count", 0) > 0
    cc = features.get("cyclomatic_complexity", 1)
    base_class = _complexity_class(features)

    # Intensity
    intensity_weights = {
        "light":  {"light": 0.60, "medium": 0.35, "heavy": 0.05},
        "medium": {"light": 0.10, "medium": 0.65, "heavy": 0.25},
        "heavy":  {"light": 0.05, "medium": 0.30, "heavy": 0.65},
    }[base_class]
    intensity = f.get("intensity") or rng.choices(
        list(intensity_weights.keys()), weights=list(intensity_weights.values())
    )[0]

    rename_on = f.get("rename_on", plan_index == 0 or rng.random() < 0.88)

    if has_strings:
        string_on = f.get("string_on", rng.random() < 0.72)
    else:
        string_on = f.get("string_on", False)
    string_method = rng.choice(STRING_METHODS) if string_on else "charcode_array"
    string_min = rng.choice([1, 2, 3]) if string_on else 2

    # v6: force operator_sub when features strongly suggest it (was 45% adoption)
    if "op_sub_on" not in f:
        if (cc >= 8 or features.get("operator_count", 0) > 5) and has_operators:
            op_sub_on = True
        else:
            op_sub_on = (rng.random() < (0.55 if intensity == "light" else 0.75)) if has_operators else False
    else:
        op_sub_on = f["op_sub_on"]
    # v6: force string_encode when string_count > 2
    if "string_on" not in f and has_strings and features.get("string_count", 0) > 2:
        string_on = True
    op_rate = round(rng.uniform(0.4, 1.0), 2) if op_sub_on else 0.7

    dead_on = f.get("dead_on", rng.random() < 0.85)
    if dead_on:
        if intensity == "light":
            dead_count = rng.randint(1, 2)
        elif intensity == "heavy":
            dead_count = rng.randint(2, min(5, max(2, cc // 2)))
        else:
            dead_count = rng.randint(1, min(4, max(1, cc // 2)))
    else:
        dead_count = 1

    opaque_on = f.get("opaque_on", rng.random() < (0.30 if intensity == "light" else 0.55))
    opaque_count = rng.randint(1, 3) if opaque_on else 1

    transforms = {
        "rename": {"enabled": rename_on},
        "string_encode": (
            {"enabled": True, "method": string_method, "min_length": string_min}
            if string_on else {"enabled": False}
        ),
        "operator_sub": (
            {"enabled": True, "rate": op_rate} if op_sub_on else {"enabled": False}
        ),
        "dead_code": (
            {"enabled": True, "count": dead_count} if dead_on else {"enabled": False}
        ),
        "opaque_predicates": (
            {"enabled": True, "count": opaque_count} if opaque_on else {"enabled": False}
        ),
    }
    order = [name for name in TRANSFORM_ORDER if transforms[name]["enabled"]]
    return {"seed": seed, "intensity": intensity, "transforms": transforms, "order": order}


def generate_diverse_plans(features: dict, function_id: str, n: int) -> list[dict]:
    """Generate n diverse plans with guaranteed coverage of edge cases."""
    if n < 1:
        return []
    has_strings = features.get("string_count", 0) > 0
    plans = []

    # Forced plan 0: always light intensity + rename only (minimal baseline)
    plans.append(_make_plan(features, function_id, 0, forced={
        "intensity": "light", "rename_on": True, "string_on": False,
        "op_sub_on": False, "dead_on": True, "opaque_on": False,
    }))
    if n == 1:
        return plans

    # Forced plan 1: no operator_sub
    plans.append(_make_plan(features, function_id, 1, forced={"op_sub_on": False}))
    if n == 2:
        return plans

    # Forced plan 2: string_encode if possible (or no string_encode if no strings)
    plans.append(_make_plan(features, function_id, 2, forced={
        "string_on": has_strings,
    }))
    if n == 3:
        return plans

    # Forced plan 3: minimal (1-2 transforms max) — rename + dead only
    plans.append(_make_plan(features, function_id, 3, forced={
        "rename_on": True, "string_on": False, "op_sub_on": False,
        "dead_on": True, "opaque_on": False,
    }))

    # Remaining: random diverse
    for i in range(4, n):
        plans.append(_make_plan(features, function_id, i))

    return plans

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/filtered/features.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/candidates/plans.jsonl"))
    parser.add_argument("--plans-per-function", type=int, default=6)
    parser.add_argument("--adaptive", action="store_true",
                        help="Generate at least six plans for complex functions.")
    parser.add_argument("--intensity-seeded", action="store_true",
                        help="v6: append contrastive intensity-sweep plans (one per intensity class).")
    args = parser.parse_args()

    def records():
        for record in read_jsonl(args.input):
            features = record.get("features", {})
            fid = record["id"]
            cc = features.get("cyclomatic_complexity", 1)
            n = args.plans_per_function
            if args.adaptive and cc >= 5:
                n = max(n, 6)
            base_plans = generate_diverse_plans(features, fid, n)
            for i, plan in enumerate(base_plans):
                yield {**record, "candidate_id": f"{fid}:{i}", "plan": plan}
            # v6: append 3 contrastive plans (one per intensity) for DPO / robustness
            if args.intensity_seeded:
                for offset, forced_intensity in enumerate(("light", "medium", "heavy"), start=1):
                    forced = {"intensity": forced_intensity, "rename_on": True, "dead_on": True}
                    plan = _make_plan(features, fid, n + offset, forced=forced)
                    yield {**record, "candidate_id": f"{fid}:c{offset}", "plan": plan}

    total = write_jsonl(args.output, records())
    print(f"plans={total} output={args.output}")

if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import ast
import json
import math
import re
from collections import Counter
from pathlib import Path

from common import call_engine_batch, read_jsonl, write_jsonl

TOKEN = re.compile(r"[A-Za-z_$][\w$]*|\d+|[^\s]")
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
MAX_ORDER_SHARE = 0.25

# v7: transform coverage floors enforced as hard post-conditions.
DEFAULT_MIN_STRING_ENCODE = 0.70   # share of records with string_count > 0
DEFAULT_MIN_DEAD_CODE = 0.60
DEFAULT_MIN_OPAQUE = 0.40


def parse_quota(value: str | None, option: str) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as error:
            try:
                parsed = {
                    key.strip().strip("'\""): int(raw.strip())
                    for item in value.strip("{} ").split(",")
                    for key, raw in [item.split(":", 1) if ":" in item else item.split("=", 1)]
                }
            except (ValueError, TypeError) as fallback_error:
                raise ValueError(f"--{option} must be a JSON/Python-literal object or key=value list") from fallback_error
    if not isinstance(parsed, dict) or any(not isinstance(item, int) or item < 0 for item in parsed.values()):
        raise ValueError(f"--{option} must contain non-negative integer values")
    return parsed


def entropy(code: str) -> float:
    tokens = TOKEN.findall(code)
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def identifier_set(code: str) -> set[str]:
    return set(IDENTIFIER.findall(code))


def score_record(record: dict, after_features: dict) -> dict:
    before = record["original_code"]
    after  = record["obfuscated_code"]
    before_features = record["features"]

    entropy_gain = max(0.0, min((entropy(after) - entropy(before)) / 4.0, 1.0))
    complexity_gain = max(0.0, min(
        (after_features["cyclomatic_complexity"] - before_features["cyclomatic_complexity"]) / 10.0, 1.0
    ))
    size_ratio = len(after.encode()) / max(len(before.encode()), 1)
    # v7: sweet spot widened (3.0 center, range 4, max 8) so string_encode-inflated
    # candidates are not penalized below non-encoding ones.
    size_quality = max(0.0, 1.0 - abs(size_ratio - 3.0) / 4.0) if size_ratio <= 8 else 0.0

    before_ids = identifier_set(before)
    after_ids  = identifier_set(after)
    before_unique = max(len(before_ids), 1)
    overlap = len(before_ids & after_ids) / before_unique
    scramble_raw = 1.0 - overlap
    identifier_scramble = scramble_raw if before_features.get("identifier_count", 0) > 3 else 0.0

    # v7 relevance bonus rebalanced: string_encode was undervalued relative to
    # operator_sub, which made the dominant order string_encode-free.
    op_count = before_features.get("operator_count", 0)
    order = record.get("plan", {}).get("order", [])
    operator_sub_used = "operator_sub" in order
    relevance_bonus = 0.0
    if op_count > 2 and operator_sub_used:
        relevance_bonus = 0.05
    elif op_count <= 2 and not operator_sub_used:
        relevance_bonus = 0.03
    string_count = before_features.get("string_count", 0)
    string_encode_used = "string_encode" in order
    if string_count > 0 and string_encode_used:
        relevance_bonus += 0.10
    elif string_count == 0 and not string_encode_used:
        relevance_bonus += 0.03

    score = (
        0.35 * entropy_gain
        + 0.25 * complexity_gain
        + 0.20 * size_quality
        + 0.20 * identifier_scramble
        + relevance_bonus
    )

    return {
        **record,
        "metrics": {
            "entropy_before": entropy(before),
            "entropy_after":  entropy(after),
            "entropy_gain_normalized": entropy_gain,
            "complexity_before": before_features["cyclomatic_complexity"],
            "complexity_after":  after_features["cyclomatic_complexity"],
            "complexity_gain_normalized": complexity_gain,
            "size_ratio":    size_ratio,
            "size_quality":  size_quality,
            "identifier_scramble": identifier_scramble,
            "relevance_bonus": relevance_bonus,
            "score": score,
        },
    }


def _complexity_class(record: dict) -> str:
    cc = record.get("features", {}).get("cyclomatic_complexity", 1)
    return "light" if cc <= 2 else "medium" if cc <= 5 else "heavy"


def _intensity_fractions(intensity_targets: dict[str, int], total_target: int) -> dict[str, float]:
    """Quota values <= 100 are percent shares, larger values are absolute counts."""
    if all(v <= 100 for v in intensity_targets.values()):
        fractions = {name: v / 100.0 for name, v in intensity_targets.items()}
    else:
        fractions = {name: v / total_target for name, v in intensity_targets.items()}
    if sum(fractions.values()) > 1.0 + 1e-9:
        raise ValueError("intensity target shares must not exceed the total target")
    return fractions


def _order_key(record: dict) -> str:
    return ",".join(record["plan"].get("order", []))


def has_contradiction(record: dict) -> bool:
    """v7: R2b (operator_sub on operator-poor functions) and R4 (opaque_predicates
    on light-complexity functions) are dropped before selection, so quotas and
    coverage floors are computed over contradiction-free candidates only."""
    order = record["plan"].get("order", [])
    features = record.get("features", {})
    if "operator_sub" in order and (features.get("operator_count", 0) or 0) <= 2:
        return True
    if "opaque_predicates" in order and (features.get("cyclomatic_complexity", 1) or 1) <= 2:
        return True
    return False


LIGHT_SHAPES = (frozenset({"rename"}), frozenset({"rename", "dead_code"}))


def matches_intensity_shape(record: dict) -> bool:
    """v7.1: 'Target intensity' must be a REAL control signal, i.e. the plan shape
    is determined by the intensity label. Without this the prompt promises
    'light -> minimal' while the data contains full 4-transform light plans
    (light purity was 2.3%) and the model cannot learn the conditioning.

    light  = minimal:      {rename} or {rename, dead_code}
    medium = moderate:     2-4 transforms, NO opaque_predicates, at least one
                           of string_encode/operator_sub (else it is a light shape)
    heavy  = aggressive:   opaque_predicates present (severity marker), >= 3 transforms
    """
    intensity = record["plan"].get("intensity")
    order = frozenset(record["plan"].get("order", []))
    if intensity == "light":
        return order in LIGHT_SHAPES
    if intensity == "medium":
        return (
            "opaque_predicates" not in order
            and 2 <= len(order) <= 4
            and bool(order - {"rename", "dead_code"})
        )
    if intensity == "heavy":
        if "opaque_predicates" not in order or len(order) < 3:
            return False
        string_count = record.get("features", {}).get("string_count", 0) or 0
        if string_count > 0 and "string_encode" not in order:
            return False
        return True
    return True


def _cell_key(record: dict, multi_variant: bool = False) -> tuple[str, str]:
    """One record per (function, intensity) cell when multi-variant selection is
    enabled (v7 conditional datasets); otherwise one per function (legacy)."""
    if multi_variant:
        return (record["id"], record["plan"].get("intensity") or "unknown")
    return (record["id"], "")


def _bucket_of(record: dict) -> str:
    return record["plan"].get("intensity") or "unknown"


class _QuotaState:
    """Shared counters for selection and swap-balancing."""

    def __init__(self, targets: dict[str, int], max_share: float,
                 complexity_targets: dict | None, generator_targets: dict | None,
                 multi_variant: bool = False, light_exempt_order_cap: bool = False):
        self.targets = targets
        self.total_target = sum(targets.values())
        self.order_cap = max(1, int(self.total_target * max_share))
        self.complexity_targets = complexity_targets or {}
        self.generator_targets = generator_targets or {}
        self.multi_variant = multi_variant
        # v7.1: light cells all share the single minimal shape, so the global
        # order cap must not apply to them (light share == that order's share).
        self.light_exempt_order_cap = light_exempt_order_cap
        self.selected: list[dict] = []
        self.source_counts: Counter = Counter()
        self.complexity_counts: Counter = Counter()
        self.generator_counts: Counter = Counter()
        self.intensity_counts: Counter = Counter()
        self.order_counts: Counter = Counter()
        self.used_cells: set[tuple[str, str]] = set()

    def eligible(self, record: dict) -> bool:
        kind = record["source_type"]
        if self.source_counts[kind] >= self.targets[kind]:
            return False
        if _cell_key(record, self.multi_variant) in self.used_cells:
            return False
        if not (self.light_exempt_order_cap and _bucket_of(record) == "light"):
            if self.order_counts[_order_key(record)] >= self.order_cap:
                return False
        complexity = _complexity_class(record)
        if self.complexity_counts[complexity] >= self.complexity_targets.get(complexity, self.total_target):
            return False
        generator = record.get("generator_type") or "unknown"
        if self.generator_counts[generator] >= self.generator_targets.get(generator, self.total_target):
            return False
        return True

    def add(self, record: dict) -> None:
        self.selected.append(record)
        self.source_counts[record["source_type"]] += 1
        self.complexity_counts[_complexity_class(record)] += 1
        self.generator_counts[record.get("generator_type") or "unknown"] += 1
        self.intensity_counts[_bucket_of(record)] += 1
        self.order_counts[_order_key(record)] += 1
        self.used_cells.add(_cell_key(record, self.multi_variant))

    def remove(self, record: dict) -> None:
        self.selected.remove(record)
        self.source_counts[record["source_type"]] -= 1
        self.complexity_counts[_complexity_class(record)] -= 1
        self.generator_counts[record.get("generator_type") or "unknown"] -= 1
        self.intensity_counts[_bucket_of(record)] -= 1
        self.order_counts[_order_key(record)] -= 1
        self.used_cells.discard(_cell_key(record, self.multi_variant))


def _swap_balance(state: _QuotaState, pool_by_key: dict[tuple, list[dict]],
                  max_passes: int = 12) -> int:
    """Replace over-cap-order records with same-(source,complexity,generator,intensity)
    candidates of a different order. Quotas stay intact; only order counts move."""
    swaps = 0
    for _ in range(max_passes):
        if not state.selected:
            break
        total = len(state.selected)
        over = _over_orders(state)
        if not over:
            break
        changed = False
        victims = sorted(
            (r for r in state.selected
             if _order_key(r) in over
             and not (state.light_exempt_order_cap and _bucket_of(r) == "light")),
            key=lambda r: r["metrics"]["score"],
        )
        for victim in victims:
            if _order_key(victim) not in over:
                continue
            key = (
                victim["source_type"],
                _complexity_class(victim),
                victim.get("generator_type") or "unknown",
                _bucket_of(victim),
            )
            for cand in pool_by_key.get(key, ()):  # score-desc within key
                cand_order = _order_key(cand)
                if cand_order == _order_key(victim) or cand_order in over:
                    continue
                if _cell_key(cand, state.multi_variant) in state.used_cells and \
                        _cell_key(cand, state.multi_variant) != _cell_key(victim, state.multi_variant):
                    continue
                state.remove(victim)
                if not state.eligible(cand):
                    state.add(victim)
                    continue
                state.add(cand)
                swaps += 1
                changed = True
                break
            if not _set_over(state):
                break
        if not changed:
            break
    return swaps


def _over_orders(state: _QuotaState) -> set[str]:
    """Orders above cap. With v7.1 light-exemption the light-only minimal shapes
    ({rename}, {rename,dead_code}) are exempt — they occur only on light records
    and their share equals the light quota, not a diversity failure."""
    over = {o for o, c in state.order_counts.items() if c > state.order_cap}
    if state.light_exempt_order_cap:
        over = {o for o in over if not (set(o.split(",")) <= {"rename", "dead_code"})}
    return over


def _set_over(state: _QuotaState) -> bool:
    return bool(_over_orders(state))


def _swap_balance_intensity(state: _QuotaState, pool_by_key3: dict[tuple, list[dict]],
                            fractions: dict[str, float], tolerance: float = 0.05,
                            max_passes: int = 12) -> int:
    """Swap over-target intensity records for under-target intensity candidates
    matching (source, complexity, generator). Source/complexity/generator quotas
    stay intact; order caps are re-repaired by the caller afterwards."""
    swaps = 0
    for _ in range(max_passes):
        total = len(state.selected)
        if not total:
            break
        over = [name for name in fractions
                if state.intensity_counts[name] / total - fractions[name] > tolerance]
        under = [name for name in fractions
                 if fractions[name] - state.intensity_counts[name] / total > tolerance]
        if not over or not under:
            break
        changed = False
        victims = sorted(
            (r for r in state.selected if _bucket_of(r) in over),
            key=lambda r: r["metrics"]["score"],
        )
        for victim in victims:
            if all(state.intensity_counts[n] / len(state.selected) - fractions[n] <= tolerance
                   for n in over):
                break
            key = (
                victim["source_type"],
                _complexity_class(victim),
                victim.get("generator_type") or "unknown",
            )
            for cand in pool_by_key3.get(key, ()):
                if _bucket_of(cand) not in under:
                    continue
                if _order_key(cand) == _order_key(victim):
                    continue
                if not (state.light_exempt_order_cap and _bucket_of(cand) == "light"):
                    if state.order_counts[_order_key(cand)] >= state.order_cap:
                        continue
                state.remove(victim)
                if not state.eligible(cand):
                    state.add(victim)
                    continue
                state.add(cand)
                swaps += 1
                changed = True
                break
        if not changed:
            break
    return swaps


def _coverage_of(state: _QuotaState, transform: str, predicate) -> tuple[int, int]:
    eligible_records = [r for r in state.selected if predicate(r)]
    if not eligible_records:
        return 0, 0
    covered = sum(1 for r in eligible_records if transform in r["plan"].get("order", []))
    return covered, len(eligible_records)


def _swap_boost_coverage(state: _QuotaState, pool_by_key: dict[tuple, list[dict]],
                         transform: str, predicate, min_share: float, max_passes: int = 8) -> int:
    """Swap non-covered records for covered same-key candidates until floor holds."""
    swaps = 0
    for _ in range(max_passes):
        covered, total = _coverage_of(state, transform, predicate)
        if not total or covered / total >= min_share:
            break
        changed = False
        victims = sorted(
            (r for r in state.selected
             if predicate(r) and transform not in r["plan"].get("order", [])),
            key=lambda r: r["metrics"]["score"],
        )
        for victim in victims:
            if covered / total >= min_share:
                break
            key = (
                victim["source_type"],
                _complexity_class(victim),
                victim.get("generator_type") or "unknown",
                _bucket_of(victim),
            )
            for cand in pool_by_key.get(key, ()):
                if transform not in cand["plan"].get("order", []):
                    continue
                if _order_key(cand) == _order_key(victim):
                    continue
                if not (state.light_exempt_order_cap and _bucket_of(cand) == "light"):
                    if state.order_counts[_order_key(cand)] >= state.order_cap:
                        continue
                if _cell_key(cand, state.multi_variant) in state.used_cells and \
                        _cell_key(cand, state.multi_variant) != _cell_key(victim, state.multi_variant):
                    continue
                state.remove(victim)
                if not state.eligible(cand):
                    state.add(victim)
                    continue
                state.add(cand)
                swaps += 1
                changed = True
                covered, total = _coverage_of(state, transform, predicate)
                break
        if not changed:
            break
    return swaps


def select_with_quotas(
    candidates: list[dict],
    targets: dict[str, int],
    max_share: float,
    complexity_targets: dict[str, int] | None = None,
    generator_targets: dict[str, int] | None = None,
    intensity_targets: dict[str, int] | None = None,
    min_string_encode: float = DEFAULT_MIN_STRING_ENCODE,
    min_dead_code: float = DEFAULT_MIN_DEAD_CODE,
    min_opaque: float = DEFAULT_MIN_OPAQUE,
    multi_variant: bool = False,
    drop_contradictions: bool = False,
    conditional_shapes: bool = False,
) -> list[dict]:
    total_target = sum(targets.values())

    if drop_contradictions:
        candidates = [r for r in candidates if not has_contradiction(r)]
    if conditional_shapes:
        before = len(candidates)
        candidates = [r for r in candidates if matches_intensity_shape(r)]
        print(f"conditional_shapes: pool {before} -> {len(candidates)} (light=minimal, medium=no-opaque, heavy=opaque)")

    # Pool indexed by (source, complexity, generator, intensity) for swap passes.
    pool_by_key: dict[tuple, list[dict]] = {}
    pool_by_key3: dict[tuple, list[dict]] = {}
    for record in candidates:
        key = (
            record["source_type"],
            _complexity_class(record),
            record.get("generator_type") or "unknown",
            _bucket_of(record),
        )
        pool_by_key.setdefault(key, []).append(record)
        pool_by_key3.setdefault(key[:3], []).append(record)
    for bucket in pool_by_key.values():
        bucket.sort(key=lambda r: r["metrics"]["score"], reverse=True)
    for bucket in pool_by_key3.values():
        bucket.sort(key=lambda r: r["metrics"]["score"], reverse=True)

    state = _QuotaState(targets, max_share, complexity_targets, generator_targets, multi_variant,
                        light_exempt_order_cap=conditional_shapes)
    if conditional_shapes:
        # v7.1: the order cap governs the non-light population, so it must be
        # scaled to the expected non-light record count (not the grand total),
        # otherwise per-split share gates (share of non-light) see ~cap/light_share.
        light_fraction = 0.0
        if intensity_targets:
            light_fraction = _intensity_fractions(intensity_targets, total_target).get("light", 0.0)
        expected_non_light = total_target * (1.0 - light_fraction)
        state.order_cap = max(1, int(expected_non_light * max_share))
    ordered = sorted(candidates, key=lambda r: r["metrics"]["score"], reverse=True)

    # Phase 1: scarce sources pick first under shared counters.
    scarce_sources = [kind for kind, amount in targets.items() if amount <= total_target // 2]
    phase1 = [r for r in ordered if r["source_type"] in scarce_sources]
    for record in phase1:
        if state.source_counts[record["source_type"]] >= targets[record["source_type"]]:
            break
        if state.eligible(record):
            state.add(record)

    # Phase 2: intensity staging over the remaining (non-scarce) candidates.
    # Scarcest intensity claims shared order/complexity capacity first (same
    # principle as the scarce-source phase): staging by descending share starved
    # heavy and broke the intensity quota.
    if intensity_targets:
        fractions = _intensity_fractions(intensity_targets, total_target)
        stages = sorted(fractions, key=lambda name: fractions[name])
        rest = [r for r in ordered if r["source_type"] not in scarce_sources]
        for name in stages:
            stage_goal = int(total_target * fractions[name]) - state.intensity_counts[name]
            claimed = 0
            for record in rest:
                if claimed >= stage_goal:
                    break
                if _bucket_of(record) != name:
                    continue
                if state.eligible(record):
                    state.add(record)
                    claimed += 1

    # Phase 3: greedy fill.
    for record in ordered:
        if len(state.selected) >= total_target:
            break
        if state.eligible(record):
            state.add(record)

    if len(state.selected) != total_target:
        raise RuntimeError(
            f"Cannot satisfy source quotas and order cap: selected={len(state.selected)}/{total_target}, "
            f"source_counts={dict(state.source_counts)}, max_order_count={state.order_cap}, "
            f"distinct_orders={len(state.order_counts)}"
        )

    # Phase 4: swap-balancing for coverage floors, intensity quotas and order caps.
    swaps_se = _swap_boost_coverage(
        state, pool_by_key, "string_encode",
        lambda r: (r.get("features", {}).get("string_count", 0) or 0) > 0, min_string_encode)
    swaps_dc = _swap_boost_coverage(
        state, pool_by_key, "dead_code", lambda r: True, min_dead_code)
    swaps_op = _swap_boost_coverage(
        state, pool_by_key, "opaque_predicates", lambda r: True, min_opaque)
    swaps_int = 0
    if intensity_targets:
        swaps_int = _swap_balance_intensity(
            state, pool_by_key3, _intensity_fractions(intensity_targets, total_target))
    swaps_order = _swap_balance(state, pool_by_key)

    # Hard post-conditions (v7): the pipeline fails instead of shipping a collapsed dataset.
    total = len(state.selected)
    if conditional_shapes:
        # v7.1: diversity is judged over medium+heavy orders; light contributes a
        # single intentional shape (its share == light quota, not collapse).
        # The cap is absolute (order_cap = share x total), light orders exempt.
        non_light_counts = Counter(
            {o: c for o, c in state.order_counts.items()
             if not (set(o.split(",")) <= {"rename", "dead_code"})}
        )
        non_light_total = sum(non_light_counts.values())
        top_order, top_count = (non_light_counts.most_common(1)[0]
                                if non_light_counts else ("none", 0))
        if top_count > state.order_cap:
            raise RuntimeError(
                f"post-condition failed: top non-light order '{top_order}' count "
                f"{top_count} > cap {state.order_cap} "
                f"({top_count / max(non_light_total, 1):.3f} of non-light)")
        light_records = [r for r in state.selected if _bucket_of(r) == "light"]
        pure = sum(1 for r in light_records
                   if frozenset(r["plan"].get("order", [])) in LIGHT_SHAPES)
        if light_records and pure / len(light_records) < 0.95:
            raise RuntimeError(
                f"post-condition failed: light purity {pure}/{len(light_records)} < 0.95")
        print(f"light_purity={pure}/{len(light_records)}")
    else:
        top_order, top_count = state.order_counts.most_common(1)[0]
        if top_count / total > max_share + 1e-9:
            raise RuntimeError(f"post-condition failed: top order '{top_order}' share {top_count / total:.3f} > {max_share}")
    if intensity_targets:
        fractions = _intensity_fractions(intensity_targets, total_target)
        for name, wanted in fractions.items():
            actual = state.intensity_counts[name] / total
            if abs(actual - wanted) > 0.05:
                raise RuntimeError(
                    f"post-condition failed: intensity {name} share {actual:.3f} deviates from target {wanted:.3f}")
    se_covered, se_total = _coverage_of(state, "string_encode",
                                        lambda r: (r.get("features", {}).get("string_count", 0) or 0) > 0)
    if se_total and se_covered / se_total < min_string_encode:
        raise RuntimeError(f"post-condition failed: string_encode coverage {se_covered}/{se_total} < {min_string_encode}")
    dc_covered, dc_total = _coverage_of(state, "dead_code", lambda r: True)
    if dc_total and dc_covered / dc_total < min_dead_code:
        raise RuntimeError(f"post-condition failed: dead_code coverage {dc_covered}/{dc_total} < {min_dead_code}")
    op_covered, op_total = _coverage_of(state, "opaque_predicates", lambda r: True)
    if op_total and op_covered / op_total < min_opaque:
        raise RuntimeError(f"post-condition failed: opaque_predicates coverage {op_covered}/{op_total} < {min_opaque}")

    print(f"swaps: order={swaps_order} string_encode={swaps_se} dead_code={swaps_dc} opaque={swaps_op} intensity={swaps_int}")
    print(f"intensity_mix={ {k: round(v / total, 3) for k, v in sorted(state.intensity_counts.items())} }")
    print(f"complexity_mix={ {k: round(v / total, 3) for k, v in sorted(state.complexity_counts.items())} }")
    print(f"distinct_orders={len(state.order_counts)} max_order_share={top_count / total:.3f}")
    print(f"coverage: string_encode={se_covered}/{se_total} dead_code={dc_covered}/{dc_total} opaque={op_covered}/{op_total}")
    print(f"unique_functions={len({r['id'] for r in state.selected})} (multi-intensity variants allowed)")
    return state.selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  type=Path, default=Path("data/candidates/validated.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/candidates/scored.jsonl"))
    parser.add_argument("--max-order-share", type=float, default=MAX_ORDER_SHARE)
    parser.add_argument("--total-target", type=int, default=10000)
    parser.add_argument("--real-target", type=int, default=2500)
    parser.add_argument("--synthetic-target", type=int, default=7500)
    parser.add_argument("--complexity-targets", type=str, default=None,
                        help='JSON counts, e.g. {"light":2500,"medium":4500,"heavy":3000}')
    parser.add_argument("--intensity-targets", type=str, default=None,
                        help='Staged shares as JSON/key=value; values <=100 are percents,'
                             ' e.g. "light=28,medium=47,heavy=19"')
    parser.add_argument("--generator-targets", type=str, default=None,
                        help='JSON counts by generator_type; omitted types are unrestricted')
    parser.add_argument("--min-string-encode-share", type=float, default=DEFAULT_MIN_STRING_ENCODE)
    parser.add_argument("--min-dead-code-share", type=float, default=DEFAULT_MIN_DEAD_CODE)
    parser.add_argument("--min-opaque-share", type=float, default=DEFAULT_MIN_OPAQUE)
    parser.add_argument("--allow-multi-intensity", action="store_true",
                        help="v7: allow up to one record per (function, intensity) cell;"
                             " requires conditional formatting and group-mode splitting")
    parser.add_argument("--drop-contradictions", action="store_true",
                        help="v7: exclude R2b (op_sub on operator-poor) and R4 (opaque on light) candidates")
    parser.add_argument("--conditional-shapes", action="store_true",
                        help="v7.1: intensity determines the plan shape (light=minimal, "
                             "medium=no opaque, heavy=opaque); light is exempt from the order cap")
    parser.add_argument("--all-scored-output", type=Path, default=None,
                        help="Optional path for all scored valid candidates, used by DPO generation")
    args = parser.parse_args()

    valid = [r for r in read_jsonl(args.input) if r.get("tests_passed") and r.get("obfuscated_code")]
    if not valid:
        print("selected=0 (no valid candidates)")
        return

    responses = call_engine_batch([
        {"operation": "extract_features", "code": r["obfuscated_code"]} for r in valid
    ])
    scored = [score_record(rec, resp["value"]["features"]) for rec, resp in zip(valid, responses)]
    if args.all_scored_output:
        write_jsonl(args.all_scored_output, scored)

    groups = {
        "real": [r for r in scored if r.get("source_type") == "real"],
        "synthetic": [r for r in scored if r.get("source_type") != "real"],
    }
    targets = {"real": args.real_target, "synthetic": args.synthetic_target}
    if args.total_target != args.real_target + args.synthetic_target:
        parser.error("--total-target must equal --real-target + --synthetic-target")
    missing = {kind: targets[kind] - len(groups[kind]) for kind in targets if len(groups[kind]) < targets[kind]}
    if missing:
        raise RuntimeError(
            "Insufficient source-aware candidates: "
            + ", ".join(f"{kind} need {amount} more (available={len(groups[kind])})" for kind, amount in missing.items())
        )

    try:
        complexity_targets = parse_quota(args.complexity_targets, "complexity-targets")
        generator_targets = parse_quota(args.generator_targets, "generator-targets")
        intensity_targets = parse_quota(args.intensity_targets, "intensity-targets")
    except ValueError as error:
        parser.error(str(error))
    if complexity_targets and sum(complexity_targets.values()) != args.total_target:
        parser.error("complexity target counts must sum to --total-target")
    try:
        if intensity_targets:
            _intensity_fractions(intensity_targets, args.total_target)
    except ValueError as error:
        parser.error(str(error))
    if generator_targets and sum(generator_targets.values()) > args.total_target:
        parser.error("generator target counts cannot exceed --total-target")

    all_candidates = groups["real"] + groups["synthetic"]
    selected = select_with_quotas(
        all_candidates,
        targets,
        args.max_order_share,
        complexity_targets,
        generator_targets,
        intensity_targets,
        args.min_string_encode_share,
        args.min_dead_code_share,
        args.min_opaque_share,
        args.allow_multi_intensity,
        args.drop_contradictions,
        args.conditional_shapes,
    )

    selected.sort(key=lambda r: (r["id"], r["plan"].get("intensity", "")))
    print(f"selected={write_jsonl(args.output, selected)} real={args.real_target} synthetic={args.synthetic_target} output={args.output}")


if __name__ == "__main__":
    main()

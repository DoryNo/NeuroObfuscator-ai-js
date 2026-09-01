#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# v7: reuses data/candidates/validated_v6.jsonl (engine v6.1 unchanged).
# Focus: fix mode collapse (top order <=14% at selection, 15% enforced),
# conditional intensity prompts, atomic-group splits, hard audit gates.

echo "=== v7 step 06: score + select (rebalanced score, per-cell dedup, coverage floors) ==="
python scripts/06_score_and_select.py \
    --input data/candidates/validated_v6.jsonl \
    --output data/candidates/scored_v7.jsonl \
    --all-scored-output data/candidates/all_scored_v7.jsonl \
    --total-target 7500 \
    --real-target 900 \
    --synthetic-target 6600 \
    --max-order-share 0.14 \
    --allow-multi-intensity \
    --drop-contradictions \
    --conditional-shapes \
    --intensity-targets "light=20,medium=45,heavy=35" \
    --min-string-encode-share 0.70 \
    --min-dead-code-share 0.60 \
    --min-opaque-share 0.25

echo "=== v7 step 07: conditional format (Target intensity in prompt, @intensity ids) ==="
mkdir -p data/final_v7
python scripts/07_format_for_training.py \
    --input data/candidates/scored_v7.jsonl \
    --output data/final_v7/formatted_v7.jsonl \
    --conditional

echo "=== v7 step 08: atomic-group split (exact sizes, no base-function leakage) ==="
python scripts/08_split_dataset.py \
    --input data/final_v7/formatted_v7.jsonl \
    --output-dir data/final_v7 \
    --seed 2026 \
    --train-count 6000 \
    --val-count 750 \
    --test-count 750 \
    --train-real-count 720 \
    --val-real-count 90 \
    --test-real-count 90 \
    --max-order-share 0.30

echo "=== v7 step 09: audit + enforce gates ==="
python scripts/09_audit_dataset.py \
    --input-dir data/final_v7 \
    --splits train val test \
    --enforce \
    --enforce-max-order-share 0.15 \
    --enforce-min-unique-orders 20 \
    --enforce-min-string-encode-share 0.70 \
    --enforce-min-dead-code-share 0.60 \
    --enforce-min-opaque-share 0.40

echo "=== v7 step 10: contradictions audit (report) ==="
python scripts/10_audit_contradictions.py \
    --inputs data/final_v7/train.jsonl data/final_v7/val.jsonl data/final_v7/test.jsonl \
    --report reports/contradictions_report_v7.json

echo "=== v7 step 12: DPO pairs (seed-aligned, gap >= 0.05, conditional prompts) ==="
python scripts/12_build_dpo.py \
    --input data/candidates/all_scored_v7.jsonl \
    --output data/final_v7/dpo_pairs_v7.jsonl \
    --min-gap 0.05 \
    --conditional \
    --drop-contradictions

echo "=== v7 step 09b: audit DPO ==="
python scripts/09_audit_dataset.py \
    --input-dir data/final_v7 \
    --splits dpo_pairs_v7 \
    --kind dpo

echo "=== v7 done ==="
ls -la data/final_v7/

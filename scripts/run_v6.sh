#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== v6 step 04: generate plans (intensity-seeded) ==="
python scripts/04_generate_plans.py \
    --input data/filtered/features.jsonl \
    --output data/candidates/plans_v6.jsonl \
    --plans-per-function 6 \
    --adaptive \
    --intensity-seeded

echo "=== v6 step 04b: extras ==="
python scripts/04_generate_plans.py \
    --input data/filtered/features.jsonl \
    --output data/candidates/plans_v6_extra.jsonl \
    --plans-per-function 1

python -c "
import json
def read(p): return [json.loads(l) for l in open(p, encoding='utf-8')]
a = read('data/candidates/plans_v6.jsonl')
b = read('data/candidates/plans_v6_extra.jsonl')
with open('data/candidates/plans_v6_all.jsonl', 'w', encoding='utf-8') as f:
    for r in a + b: f.write(json.dumps(r, ensure_ascii=False) + chr(10))
print('merged:', len(a) + len(b))
"

echo "=== v6 step 05: apply + validate ==="
python scripts/05_apply_and_validate.py \
    --input data/candidates/plans_v6_all.jsonl \
    --output data/candidates/validated_v6.jsonl

echo "=== v6 step 06: score + select (v6 relevance bonus) ==="
python scripts/06_score_and_select.py \
    --input data/candidates/validated_v6.jsonl \
    --output data/candidates/scored_v6.jsonl \
    --all-scored-output data/candidates/all_scored_v6.jsonl \
    --total-target 9000 \
    --real-target 1500 \
    --synthetic-target 7500 \
    --max-order-share 0.22 \
    --complexity-targets '{"light":2300,"medium":4400,"heavy":2300}' \
    --intensity-targets "light=28,medium=48,heavy=24" \
    --generator-targets '{"real":1500,"callback":420,"closure":420,"destructuring":420,"default_params":420,"i18n_messages":200,"log_formatter":200,"url_parser":200}'

echo "=== v6 step 07: format noseed ==="
mkdir -p data/final_v6
python scripts/07_format_for_training.py \
    --input data/candidates/scored_v6.jsonl \
    --output data/final_v6/formatted_v6.jsonl \
  

echo "=== v6 step 08: split ==="
python scripts/08_split_dataset.py \
    --input data/final_v6/formatted_v6.jsonl \
    --output-dir data/final_v6 \
    --seed 2026 \
    --train-size 7200 \
    --val-size 900 \
    --test-size 900 \
    --real-source-quota 1200 \
    --synthetic-source-quota 6000

echo "=== v6 done ==="
ls -la data/final_v6/

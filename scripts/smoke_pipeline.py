from __future__ import annotations

import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(script: str, *args: str) -> None:
    subprocess.run([PYTHON, str(ROOT / "scripts" / script), *args], cwd=ROOT, check=True)


def main() -> None:
    data = ROOT / "tmp" / "smoke-data"
    if data.exists():
        shutil.rmtree(data)
    run("01_collect.py", "--source", str(ROOT / "tests" / "fixtures"), "--output", str(data / "raw"))
    run("02_filter.py", "--input", str(data / "raw"), "--output", str(data / "filtered" / "functions.jsonl"))
    run("03_extract_features.py", "--input", str(data / "filtered" / "functions.jsonl"), "--output", str(data / "filtered" / "features.jsonl"))
    run("04_generate_plans.py", "--input", str(data / "filtered" / "features.jsonl"), "--output", str(data / "candidates" / "plans.jsonl"), "--plans-per-function", "3")
    run("05_apply_and_validate.py", "--input", str(data / "candidates" / "plans.jsonl"), "--output", str(data / "candidates" / "validated.jsonl"))
    # Smoke fixtures are intentionally synthetic-only and use relaxed production quotas.
    run("06_score_and_select.py", "--input", str(data / "candidates" / "validated.jsonl"), "--output", str(data / "candidates" / "scored.jsonl"), "--all-scored-output", str(data / "candidates" / "all_scored.jsonl"), "--total-target", "50", "--real-target", "50", "--synthetic-target", "0", "--max-order-share", "1", "--min-string-encode-share", "0", "--min-dead-code-share", "0", "--min-opaque-share", "0")
    run("07_format_for_training.py", "--input", str(data / "candidates" / "scored.jsonl"), "--output", str(data / "final" / "formatted.jsonl"))
    run("08_split_dataset.py", "--input", str(data / "final" / "formatted.jsonl"), "--output-dir", str(data / "final"), "--train-count", "40", "--val-count", "5", "--test-count", "5", "--train-real-count", "40", "--val-real-count", "5", "--test-real-count", "5", "--strat-deviation-tolerance", "0.5")
    run("11_build_hard_negatives.py", "--input", str(data / "candidates" / "validated.jsonl"), "--output", str(data / "final" / "hard_negatives.jsonl"), "--limit", "20")
    run("12_build_dpo.py", "--input", str(data / "candidates" / "all_scored.jsonl"), "--output", str(data / "final" / "dpo_pairs.jsonl"), "--min-gap", "0.01")
    run("09_audit_dataset.py", "--input-dir", str(data / "final"), "--splits", "train", "val", "test")
    run("09_audit_dataset.py", "--input-dir", str(data / "final"), "--splits", "hard_negatives", "--kind", "hard-negative")
    run("09_audit_dataset.py", "--input-dir", str(data / "final"), "--splits", "dpo_pairs", "--kind", "dpo")
    run("09_audit_dataset.py", "--input-dir", str(data / "final"), "--splits", "train", "val", "test", "--enforce",
        "--enforce-max-order-share", "1", "--enforce-max-intensity-share", "1", "--enforce-min-p95", "0",
        "--enforce-max-strat-deviation", "1", "--enforce-required-transforms", "",
        "--enforce-min-unique-orders", "0", "--enforce-min-string-encode-share", "0",
        "--enforce-min-dead-code-share", "0", "--enforce-min-opaque-share", "0",
        "--enforce-min-light-purity", "0")
    print(f"smoke_pipeline=passed output={data}")


if __name__ == "__main__":
    main()

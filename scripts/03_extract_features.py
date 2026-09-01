from __future__ import annotations

import argparse
from pathlib import Path

from common import call_engine_batch, read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/filtered/functions.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/filtered/features.jsonl"))
    args = parser.parse_args()

    records = list(read_jsonl(args.input))
    responses = call_engine_batch([{"operation": "extract_features", "code": r["code"]} for r in records])
    for record, response in zip(records, responses):
        record["features"] = response["value"]["features"]
    print(f"featured={write_jsonl(args.output, records)} output={args.output}")


if __name__ == "__main__":
    main()

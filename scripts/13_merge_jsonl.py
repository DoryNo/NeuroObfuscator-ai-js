from __future__ import annotations

import argparse
from pathlib import Path

from common import read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge ordered JSONL chunks without duplicate ids.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    seen: set[str] = set()

    def records():
        for path in args.inputs:
            for record in read_jsonl(path):
                record_id = record.get("candidate_id", record.get("id"))
                if record_id in seen:
                    raise RuntimeError(f"Duplicate record id while merging: {record_id}")
                seen.add(record_id)
                yield record

    count = write_jsonl(args.output, records())
    print(f"merged={count} output={args.output}")


if __name__ == "__main__":
    main()

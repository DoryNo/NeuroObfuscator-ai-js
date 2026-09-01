from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from common import call_engine_batch, write_jsonl


UNSUPPORTED_RUNTIME = re.compile(
    r"\b(?:async|await|Promise|setTimeout|setInterval|queueMicrotask|fetch|WebSocket"
    r"|require|process|Buffer|globalThis|window|document)\b"
)


def _load_sources(input_dir: Path) -> dict[str, dict]:
    sources: dict[str, dict] = {}
    manifest = input_dir / "manifest.jsonl"
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                sources[record["file"]] = record
    return sources


def records(input_dir: Path, min_lines: int, max_lines: int, max_avg_line: float, real_max_lines: int | None):
    sources = _load_sources(input_dir)
    paths = sorted(input_dir.rglob("*.js"))

    # Batch 1: extract functions from every file.
    file_requests = []
    file_paths = []
    for path in paths:
        try:
            code = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        file_requests.append({"operation": "extract_functions", "code": code, "source": str(path)})
        file_paths.append(path)

    func_responses = call_engine_batch(file_requests)

    # Collect candidate functions passing structural size filters.
    seen: set[str] = set()
    candidates = []  # (digest, path, function, normalized)
    for path, response in zip(file_paths, func_responses):
        if not response.get("ok"):
            continue
        for function in response["value"]["functions"]:
            normalized = function["code"].strip()
            if UNSUPPORTED_RUNTIME.search(normalized):
                continue
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            provenance = sources.get(path.name, {})
            source_list = provenance.get("sources", [str(path)])
            source_type = provenance.get("source_type")
            if source_type not in {"synthetic", "real"}:
                source_type = "synthetic" if all("synthetic" in str(s).lower() for s in source_list) else "real"
            lines = normalized.splitlines()
            if not lines:
                continue
            average = sum(len(line) for line in lines) / len(lines)
            max_allowed_lines = real_max_lines if source_type == "real" and real_max_lines is not None else max_lines
            if not min_lines <= len(lines) <= max_allowed_lines or average >= max_avg_line:
                continue
            seen.add(digest)
            candidates.append((digest, path, function, normalized))

    # Batch 2: extract features for surviving candidates.
    feat_responses = call_engine_batch([{"operation": "extract_features", "code": c[3]} for c in candidates])

    for (digest, path, function, normalized), response in zip(candidates, feat_responses):
        if not response.get("ok"):
            continue
        provenance = sources.get(path.name, {})
        source_list = provenance.get("sources", [str(path)])
        source_type = provenance.get("source_type")
        if source_type not in {"synthetic", "real"}:
            source_type = "synthetic" if all("synthetic" in str(s).lower() for s in source_list) else "real"
        features = response["value"]["features"]
        # Modern syntax families are valuable even when they have no branch/loop.
        modern_generator = provenance.get("generator_type") in {
            "destructuring", "closure", "callback", "default_params",
        }
        # Require control-flow complexity for legacy synthetic samples.
        if (
            source_type == "synthetic"
            and not modern_generator
            and features["branch_count"] + features["loop_count"] < 1
        ):
            continue
        yield {
            "id": digest,
            **function,
            "source": source_list,
            "source_type": source_type,
            "repository": provenance.get("repository"),
            "license": provenance.get("license"),
            "generator_type": provenance.get("generator_type"),
            "code": normalized,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/filtered/functions.jsonl"))
    parser.add_argument("--min-lines", type=int, default=3)
    parser.add_argument("--max-lines", type=int, default=80)
    parser.add_argument("--real-max-lines", type=int, default=120)
    parser.add_argument("--max-avg-line", type=float, default=120)
    args = parser.parse_args()
    count = write_jsonl(args.output, records(
        args.input,
        args.min_lines,
        args.max_lines,
        args.max_avg_line,
        args.real_max_lines,
    ))
    print(f"filtered={count} output={args.output}")


if __name__ == "__main__":
    main()

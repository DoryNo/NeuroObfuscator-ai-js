from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine" / "index.js"


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid JSONL at {path}:{line_number}: {error}") from error


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def call_engine(request: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    responses = call_engine_batch([request], timeout=timeout)
    if not responses:
        raise RuntimeError("Node engine returned no response")
    resp = responses[0]
    if isinstance(resp, dict) and "ok" in resp:
        if resp["ok"]:
            return resp["value"]
        else:
            raise RuntimeError(resp.get("error", "engine error"))
    return resp


def call_engine_batch(requests: list[dict[str, Any]], timeout: float = 300.0, batch_size: int = 100) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for start in range(0, len(requests), batch_size):
        chunk = requests[start:start + batch_size]
        payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in chunk)
        try:
            result = subprocess.run(
                ["node", str(ENGINE), "--json"],
                input=payload,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=timeout,
                cwd=ROOT,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Node engine timed out after {timeout}s") from error
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Node engine failed")
        for line in result.stdout.splitlines():
            if line.strip():
                responses.append(json.loads(line))
    return responses

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def sources_from_path(source: Path):
    if source.is_file() and source.suffix.lower() == ".js":
        yield source
    elif source.is_dir():
        for path in source.rglob("*.js"):
                if "node_modules" not in path.parts and ".git" not in path.parts:
                    yield path


def load_source_metadata(root: Path) -> dict[str, dict]:
    """Load provenance for generated files when the source has a manifest."""
    manifest_path = root / "manifest.jsonl"
    if not manifest_path.exists():
        return {}
    metadata = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            metadata[record.get("file", "")] = record
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect JavaScript from local paths or explicit Git URLs.")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--git-url", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    if not args.source and not args.git_url:
        parser.error("at least one --source or --git-url is required")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.jsonl"
    manifest = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                manifest[record["id"]] = record
    roots = [Path(value).resolve() for value in args.source]
    temporary = tempfile.TemporaryDirectory(prefix="neuroobfuscator-") if args.git_url else None
    try:
        for index, url in enumerate(args.git_url):
            if shutil.which("git") is None:
                raise RuntimeError("git is not available in PATH; use --source or install Git")
            destination = Path(temporary.name) / str(index)
            try:
                subprocess.run(["git", "clone", "--depth", "1", url, str(destination)], check=True, capture_output=True)
                roots.append(destination)
            except subprocess.CalledProcessError as error:
                print(f"skipped {url}: {error}")

        count = 0
        for root in roots:
            if not root.exists():
                raise FileNotFoundError(root)
            source_metadata = load_source_metadata(root)
            for path in sources_from_path(root):
                try:
                    content = path.read_bytes()
                except OSError as error:
                    print(f"skipped file {path}: {error}")
                    continue
                digest = hashlib.sha256(content).hexdigest()
                destination = args.output / f"{digest}.js"
                origin = str(path.resolve())
                source_record = source_metadata.get(path.name, {})
                is_synthetic = (
                    source_record.get("source_type") == "synthetic"
                    or "synthetic" in origin.lower()
                )
                record = manifest.setdefault(digest, {
                    "id": digest,
                    "file": destination.name,
                    "sources": [],
                    "source_type": "synthetic" if is_synthetic else "real",
                    "generator_type": source_record.get("generator_type"),
                })
                if record.get("generator_type") is None:
                    record["generator_type"] = source_record.get("generator_type")
                record["source_type"] = "synthetic" if all("synthetic" in str(s).lower() for s in record["sources"] + [origin]) else "real"
                if origin not in record["sources"]:
                    record["sources"].append(origin)
                if not destination.exists():
                    destination.write_bytes(content)
                    count += 1
        manifest_path.write_text(
            "".join(json.dumps(manifest[key], ensure_ascii=False, separators=(",", ":")) + "\n" for key in sorted(manifest)),
            encoding="utf-8",
            newline="\n",
        )
        print(f"collected={count} output={args.output}")
    finally:
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    main()

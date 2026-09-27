"""Create deterministic corpus archives and benchmarks/manifest.json."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path


SOURCES = [
    {
        "ecosystem": "postgresql",
        "canonical_repository_url": "https://github.com/postgres/postgres.git",
        "requested_version": "REL_16_3",
        "actual_resolved_tag": "REL_16_3",
        "resolved_commit_sha": "05ffe9398b758bbb8d30cc76e9bbc638dab2d477",
        "license": "PostgreSQL License",
        "doc_relative_path": "doc/src/sgml",
        "source_dir": Path("data/sources/postgres/doc/src/sgml"),
        "file_extensions": [".sgml", ".xml", ".html"],
    },
    {
        "ecosystem": "pytorch",
        "canonical_repository_url": "https://github.com/pytorch/pytorch.git",
        "requested_version": "v2.3.1",
        "actual_resolved_tag": "v2.3.1",
        "resolved_commit_sha": "63d5e9221bedd1546b7d364b5ce4171547db12a9",
        "license": "BSD-3-Clause",
        "doc_relative_path": "docs/source",
        "source_dir": Path("data/sources/pytorch/docs/source"),
        "file_extensions": [".rst", ".md"],
    },
    {
        "ecosystem": "kubernetes",
        "canonical_repository_url": "https://github.com/kubernetes/website.git",
        "requested_version": "v1.30",
        "actual_resolved_tag": "snapshot-initial-v1.30",
        "resolved_commit_sha": "0471ca12572f26cd6f553dafddbe1de22c4abf7f",
        "license": "Apache-2.0 / CC-BY-4.0",
        "doc_relative_path": "content/en/docs",
        "source_dir": Path("data/sources/kubernetes/content/en/docs"),
        "file_extensions": [".md", ".html"],
    },
    {
        "ecosystem": "fastapi",
        "canonical_repository_url": "https://github.com/fastapi/fastapi.git",
        "requested_version": "0.111.0",
        "actual_resolved_tag": "0.111.0",
        "resolved_commit_sha": "1c3e6918750ccb3f20ea260e9a4238ce2c0e5f63",
        "license": "MIT License",
        "doc_relative_path": "docs/en/docs",
        "source_dir": Path("data/sources/fastapi/docs/en/docs"),
        "file_extensions": [".md"],
    },
]


def create_deterministic_archive(source_dir: Path, archive_path: Path, extensions: list[str]) -> Tuple[int, str]:
    """Archive files deterministically and return (file_count, sha256_hash)."""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    all_files = []
    for root, _, files in os.walk(source_dir):
        for f in files:
            if any(f.endswith(ext) for ext in extensions):
                full_path = Path(root) / f
                rel_path = full_path.relative_to(source_dir).as_posix()
                all_files.append((rel_path, full_path))

    # Sort files deterministically
    all_files.sort(key=lambda x: x[0])

    # Create tar archive with normalized mtime, uid/gid, and gzip header mtime=0 for bitwise determinism
    with open(archive_path, "wb") as raw_f:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_f, mtime=0.0) as gz_f:
            with tarfile.open(fileobj=gz_f, mode="w") as tar:
                for rel_path, full_path in all_files:
                    ti = tar.gettarinfo(full_path, arcname=rel_path)
                    ti.mtime = 1714560000  # Fixed timestamp (2024-05-01T10:40:00Z)
                    ti.uid = 0
                    ti.gid = 0
                    ti.uname = "ragtune"
                    ti.gname = "ragtune"
                    with open(full_path, "rb") as f:
                        tar.addfile(ti, f)

    # Compute SHA-256 of the archive
    sha = hashlib.sha256()
    with open(archive_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)

    return len(all_files), sha.hexdigest()


def main() -> None:
    now_utc = datetime.now(timezone.utc).isoformat()
    manifest_sources = []

    archives_dir = Path("benchmarks/archives")
    archives_dir.mkdir(parents=True, exist_ok=True)

    for src in SOURCES:
        archive_file = archives_dir / f"{src['ecosystem']}_snapshot.tar.gz"
        file_count, archive_sha256 = create_deterministic_archive(
            source_dir=src["source_dir"],
            archive_path=archive_file,
            extensions=src["file_extensions"],
        )

        record = {
            "ecosystem": src["ecosystem"],
            "canonical_repository_url": src["canonical_repository_url"],
            "requested_version": src["requested_version"],
            "actual_resolved_tag": src["actual_resolved_tag"],
            "resolved_commit_sha": src["resolved_commit_sha"],
            "retrieval_timestamp_utc": now_utc,
            "license": src["license"],
            "documentation_path_included": src["doc_relative_path"],
            "source_file_count": file_count,
            "snapshot_archive_sha256": archive_sha256,
            "snapshot_archive_path": archive_file.as_posix(),
        }
        manifest_sources.append(record)
        print(f"[{src['ecosystem']}] Files: {file_count}, Archive SHA: {archive_sha256[:16]}...")

    manifest = {
        "version": "1.0",
        "created_at_utc": now_utc,
        "sources": manifest_sources,
    }

    manifest_path = Path("benchmarks/manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Corpus manifest written to {manifest_path}")


if __name__ == "__main__":
    from typing import Tuple
    main()

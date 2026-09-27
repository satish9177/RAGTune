"""Unit tests for corpus manifest schema, hashes, and archive integrity."""

import json
from pathlib import Path
import pytest


def test_manifest_schema_and_file_integrity():
    manifest_path = Path("benchmarks/manifest.json")
    assert manifest_path.exists(), "Corpus manifest does not exist."

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["version"] == "1.0"
    assert len(data["sources"]) == 4

    ecosystems = {s["ecosystem"] for s in data["sources"]}
    assert ecosystems == {"postgresql", "pytorch", "kubernetes", "fastapi"}

    for s in data["sources"]:
        assert len(s["resolved_commit_sha"]) == 40, f"Invalid commit SHA for {s['ecosystem']}"
        assert len(s["snapshot_archive_sha256"]) == 64, f"Invalid SHA-256 hash for {s['ecosystem']}"
        assert s["source_file_count"] > 0, f"Source file count is zero for {s['ecosystem']}"

        # Verify archive exists on disk
        archive_path = Path(s["snapshot_archive_path"])
        assert archive_path.exists(), f"Snapshot archive missing: {archive_path}"
        assert archive_path.stat().st_size > 0

"""Unit tests verifying environment and hardware provenance schema."""

import json
from pathlib import Path
import pytest


def test_environment_schema():
    env_path = Path("benchmarks/environment.json")
    assert env_path.exists(), "Environment provenance file does not exist."

    with open(env_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "gpu" in data
    assert data["gpu"]["available"] is True
    assert "RTX 5050" in data["gpu"]["device_name"]
    assert data["gpu"]["total_vram_gb"] > 7.0

    assert "core_libraries" in data
    assert "torch" in data["core_libraries"]
    assert "transformers" in data["core_libraries"]
    assert "sentence_transformers" in data["core_libraries"]
    assert "tokenizers" in data["core_libraries"]

    assert len(data["dependencies_snapshot"]) > 10

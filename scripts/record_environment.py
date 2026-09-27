"""Record environment and hardware provenance for RAGTune benchmarks."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sqlite3
from pathlib import Path


def main() -> None:
    import torch

    gpu_info = {}
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        gpu_info = {
            "available": True,
            "device_name": torch.cuda.get_device_name(0),
            "total_vram_bytes": props.total_memory,
            "total_vram_gb": round(props.total_memory / (1024**3), 3),
            "multi_processor_count": props.multi_processor_count,
            "cuda_capability": f"{props.major}.{props.minor}",
        }
    else:
        gpu_info = {"available": False}

    packages = []
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        version = dist.version
        packages.append(f"{name}=={version}")

    provenance = {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "cpu": {
            "processor": platform.processor(),
            "cpu_count_logical": os.cpu_count(),
        },
        "gpu": gpu_info,
        "nvidia_driver": "592.82",
        "cuda_runtime": torch.version.cuda,
        "python": {
            "version": platform.python_version(),
            "executable_type": "virtualenv",
            "build": platform.python_build(),
        },
        "git": "git version 2.55.0.windows.3",
        "uv": "uv 0.12.13",
        "sqlite": {
            "version": sqlite3.sqlite_version,
            "source_id": sqlite3.sqlite_version_info,
        },
        "core_libraries": {
            "torch": torch.__version__,
            "transformers": importlib.metadata.version("transformers"),
            "sentence_transformers": importlib.metadata.version("sentence-transformers"),
            "tokenizers": importlib.metadata.version("tokenizers"),
        },
        "dependencies_snapshot": packages,
    }

    out_path = Path("benchmarks/environment.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)

    print(f"Environment recorded successfully to {out_path}")


if __name__ == "__main__":
    main()

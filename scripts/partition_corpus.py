"""Deterministic, document-level source partitioning into Train (60%), Val (15%), Frozen Test (25%)."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set
from ragtune.models import PassageChunk


def partition_corpus(
    chunks_path: Path,
    partition_manifest_path: Path,
    output_partitioned_chunks_path: Path,
    seed: int = 42,
) -> Dict:
    # 1. Load chunks and group by ecosystem and relative_file_path
    chunks: List[PassageChunk] = []
    ecosystem_files: Dict[str, Set[str]] = defaultdict(set)

    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = PassageChunk.model_validate_json(line)
                chunks.append(c)
                ecosystem_files[c.ecosystem].add(c.relative_file_path)

    # 2. Partition unique files per ecosystem deterministically
    rng = random.Random(seed)
    file_partition_map: Dict[str, str] = {}  # "ecosystem::relative_file_path" -> partition
    partition_manifest: Dict = {
        "seed": seed,
        "split_ratios": {"train": 0.60, "validation": 0.15, "frozen_test": 0.25},
        "summary": {},
        "files": {"train": [], "validation": [], "frozen_test": []},
    }

    counts_by_partition: Dict[str, Dict[str, int]] = {
        "train": defaultdict(int),
        "validation": defaultdict(int),
        "frozen_test": defaultdict(int),
    }

    for ecosystem, file_set in sorted(ecosystem_files.items()):
        rng = random.Random(seed)
        file_list = sorted(file_set)
        rng.shuffle(file_list)

        n = len(file_list)
        n_train = int(n * 0.60)
        n_val = int(n * 0.15)
        # Remainder goes to frozen test to ensure exactly 100% allocation
        train_files = file_list[:n_train]
        val_files = file_list[n_train : n_train + n_val]
        test_files = file_list[n_train + n_val :]

        for f in train_files:
            file_partition_map[f"{ecosystem}::{f}"] = "train"
            partition_manifest["files"]["train"].append({"ecosystem": ecosystem, "file_path": f})

        for f in val_files:
            file_partition_map[f"{ecosystem}::{f}"] = "validation"
            partition_manifest["files"]["validation"].append({"ecosystem": ecosystem, "file_path": f})

        for f in test_files:
            file_partition_map[f"{ecosystem}::{f}"] = "frozen_test"
            partition_manifest["files"]["frozen_test"].append({"ecosystem": ecosystem, "file_path": f})

    # 3. Assign partition to chunks and write partitioned chunks file
    output_partitioned_chunks_path.parent.mkdir(parents=True, exist_ok=True)
    partitioned_chunks: List[PassageChunk] = []

    with open(output_partitioned_chunks_path, "w", encoding="utf-8") as out_f:
        for chunk in chunks:
            key = f"{chunk.ecosystem}::{chunk.relative_file_path}"
            part = file_partition_map[key]
            updated_chunk = chunk.model_copy(update={"partition": part})
            partitioned_chunks.append(updated_chunk)
            counts_by_partition[part][chunk.ecosystem] += 1
            out_f.write(updated_chunk.model_dump_json() + "\n")

    # 4. Finalize summary statistics
    for part in ["train", "validation", "frozen_test"]:
        part_files = len(partition_manifest["files"][part])
        part_chunks = sum(counts_by_partition[part].values())
        partition_manifest["summary"][part] = {
            "file_count": part_files,
            "chunk_count": part_chunks,
            "by_ecosystem": dict(counts_by_partition[part]),
        }

    partition_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(partition_manifest_path, "w", encoding="utf-8") as f:
        json.dump(partition_manifest, f, indent=2)

    return partition_manifest


def main() -> None:
    chunks_path = Path("data/processed/corpus_chunks.jsonl")
    manifest_path = Path("benchmarks/partition_manifest.json")
    output_path = Path("data/processed/partitioned_chunks.jsonl")

    manifest = partition_corpus(chunks_path, manifest_path, output_path, seed=42)

    print("Partitioning complete:")
    for part, data in manifest["summary"].items():
        print(f"  {part.upper()}: {data['file_count']} files, {data['chunk_count']} chunks")
    print(f"Partition manifest written to {manifest_path}")


if __name__ == "__main__":
    main()

"""Process raw documentation into unified structured chunks obeying all invariants."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Set
import numpy as np

from ragtune.chunking.structural_chunker import (
    StructuralChunker,
    get_tokenizer_provenance,
)
from ragtune.ingestion.doc_parser import normalize_to_markdown
from ragtune.models import PassageChunk

KUBERNETES_EXCLUDED_PATH_PREFIXES = (
    "reference/kubectl/",
    "reference/kubernetes-api/",
    "reference/setup-tools/",
    "reference/command-line-tools-reference/",
    "reference/config-api/",
    "reference/instrumentation/metrics.md",
    "contribute/",
    "doc-contributor-tools/",
)

SOURCES_CONFIG = [
    {
        "ecosystem": "postgresql",
        "source_ref": "REL_16_3",
        "source_dir": Path("data/sources/postgres/doc/src/sgml"),
        "extensions": [".sgml"],
    },
    {
        "ecosystem": "pytorch",
        "source_ref": "v2.3.1",
        "source_dir": Path("data/sources/pytorch/docs/source"),
        "extensions": [".rst", ".md"],
    },
    {
        "ecosystem": "kubernetes",
        "source_ref": "snapshot-initial-v1.30",
        "source_dir": Path("data/sources/kubernetes/content/en/docs"),
        "extensions": [".md"],
    },
    {
        "ecosystem": "fastapi",
        "source_ref": "0.111.0",
        "source_dir": Path("data/sources/fastapi/docs/en/docs"),
        "extensions": [".md"],
    },
]


def is_file_excluded(ecosystem: str, rel_path: str) -> bool:
    """Evaluate whether a document file should be excluded under corpus policy."""
    if ecosystem == "kubernetes":
        norm_rel = rel_path.replace("\\", "/")
        for prefix in KUBERNETES_EXCLUDED_PATH_PREFIXES:
            if norm_rel.startswith(prefix) or norm_rel == prefix.rstrip("/"):
                return True
    return False


def ingest_all(output_file: Path, max_tokens: int = 512) -> List[PassageChunk]:
    """Ingest all configured corpora deterministically into PassageChunk objects."""
    chunker = StructuralChunker(max_tokens=max_tokens, overlap_tokens=64)
    all_chunks: List[PassageChunk] = []

    for cfg in SOURCES_CONFIG:
        ecosystem = cfg["ecosystem"]
        source_ref = cfg["source_ref"]
        source_dir: Path = cfg["source_dir"]
        extensions: List[str] = cfg["extensions"]

        # Collect and sort all matching files deterministically
        candidate_files: List[Path] = []
        for root, _, files in os.walk(source_dir):
            for file_name in files:
                if any(file_name.endswith(ext) for ext in extensions):
                    candidate_files.append(Path(root) / file_name)

        sorted_files = sorted(candidate_files, key=lambda p: p.relative_to(source_dir).as_posix())

        eco_chunks = 0
        file_count = 0
        excluded_count = 0

        for full_path in sorted_files:
            rel_path = full_path.relative_to(source_dir).as_posix()

            if is_file_excluded(ecosystem, rel_path):
                excluded_count += 1
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw_content = f.read()

                if len(raw_content.strip()) < 40:
                    continue

                norm_markdown = normalize_to_markdown(raw_content, rel_path)
                if not norm_markdown.strip():
                    continue

                chunks = chunker.chunk_document(
                    content=norm_markdown,
                    ecosystem=ecosystem,  # type: ignore[arg-type]
                    source_ref=source_ref,
                    relative_file_path=rel_path,
                )
                all_chunks.extend(chunks)
                eco_chunks += len(chunks)
                file_count += 1
            except Exception as e:
                print(f"Error processing {full_path}: {e}")

        print(
            f"[{ecosystem}] Processed {file_count} files (excluded {excluded_count}) -> {eco_chunks} chunks."
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(chunk.model_dump_json() + "\n")

    return all_chunks


def compute_and_save_stats(chunks: List[PassageChunk], stats_path: Path) -> Dict:
    """Compute and save granular corpus statistics including percentiles and token provenance."""
    stats: Dict = {
        "total_chunks": len(chunks),
        "tokenizer_provenance": get_tokenizer_provenance(),
        "ecosystems": {},
    }

    tokens_by_eco: Dict[str, List[int]] = {}
    files_by_eco: Dict[str, Set[str]] = {}

    for chunk in chunks:
        eco = chunk.ecosystem
        if eco not in tokens_by_eco:
            tokens_by_eco[eco] = []
            files_by_eco[eco] = set()

        tokens_by_eco[eco].append(chunk.token_count)
        files_by_eco[eco].add(chunk.relative_file_path)

    for eco, tok_list in sorted(tokens_by_eco.items()):
        arr = np.array(tok_list, dtype=np.int32)
        count = len(arr)
        stats["ecosystems"][eco] = {
            "chunk_count": count,
            "unique_files_count": len(files_by_eco[eco]),
            "total_tokens": int(np.sum(arr)),
            "min_tokens": int(np.min(arr)) if count > 0 else 0,
            "max_tokens": int(np.max(arr)) if count > 0 else 0,
            "avg_tokens": round(float(np.mean(arr)), 1) if count > 0 else 0.0,
            "p50_tokens": round(float(np.percentile(arr, 50)), 1) if count > 0 else 0.0,
            "p90_tokens": round(float(np.percentile(arr, 90)), 1) if count > 0 else 0.0,
            "p95_tokens": round(float(np.percentile(arr, 95)), 1) if count > 0 else 0.0,
            "p99_tokens": round(float(np.percentile(arr, 99)), 1) if count > 0 else 0.0,
        }

    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return stats


def main() -> None:
    output_path = Path("data/processed/corpus_chunks.jsonl")
    chunks = ingest_all(output_path, max_tokens=512)
    stats_path = Path("benchmarks/corpus_stats.json")
    stats = compute_and_save_stats(chunks, stats_path)
    print(f"\nCorpus Ingestion Summary: {len(chunks)} chunks across 4 ecosystems.")
    for eco, s in stats["ecosystems"].items():
        print(
            f"  {eco}: {s['chunk_count']} chunks from {s['unique_files_count']} files | "
            f"min={s['min_tokens']}, avg={s['avg_tokens']}, max={s['max_tokens']}, "
            f"p50={s['p50_tokens']}, p90={s['p90_tokens']}, p99={s['p99_tokens']}"
        )
    print(f"Stats written to {stats_path}")


if __name__ == "__main__":
    main()

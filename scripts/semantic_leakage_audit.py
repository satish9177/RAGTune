"""Semantic cross-partition leakage audit using frozen BAAI/bge-small-en-v1.5 embeddings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

MODEL_ID = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
COSINE_THRESHOLD = 0.85


def run_semantic_leakage_audit(
    chunks_path: Path,
    output_audit_path: Path,
    cosine_threshold: float = COSINE_THRESHOLD,
    batch_size: int = 64,
) -> Dict:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading frozen embedding model {MODEL_ID} (rev: {MODEL_REVISION[:10]}) on {device}...")
    model = SentenceTransformer(MODEL_ID, revision=MODEL_REVISION, device=device)

    # 1. Load partitioned chunks
    chunks: List[Dict] = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))

    print(f"Loaded {len(chunks)} partitioned chunks.")

    test_indices = [i for i, c in enumerate(chunks) if c["partition"] == "frozen_test"]
    train_val_indices = [i for i, c in enumerate(chunks) if c["partition"] in ("train", "validation")]

    print(f"Partition distribution: {len(test_indices)} frozen_test chunks, {len(train_val_indices)} train/val chunks.")

    # 2. Encode texts
    texts = [c["content"] for c in chunks]
    print(f"Generating normalized embeddings on {device} (batch_size={batch_size})...")
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_tensor=True,
        device=device,
    )

    test_emb = embeddings[test_indices]
    train_val_emb = embeddings[train_val_indices]

    # 3. Discover high semantic similarity cross-partition candidate pairs
    print(f"Computing cross-partition cosine similarities ({test_emb.shape[0]} test vs {train_val_emb.shape[0]} train/val)...")

    flagged_records: List[Dict] = []
    top_scores: List[float] = []

    block_size = 500
    for start_idx in range(0, len(test_indices), block_size):
        end_idx = min(start_idx + block_size, len(test_indices))
        block_test_emb = test_emb[start_idx:end_idx]

        # Cosine similarity matrix: (block_size, len(train_val_indices))
        sims = torch.matmul(block_test_emb, train_val_emb.T)

        # Record max score for each test chunk for distribution
        max_vals, _ = torch.max(sims, dim=1)
        top_scores.extend(max_vals.cpu().tolist())

        # Retrieve top matches exceeding threshold
        k = min(5, train_val_emb.shape[0])
        top_k_vals, top_k_indices = torch.topk(sims, k=k, dim=1)

        for i in range(end_idx - start_idx):
            global_test_idx = test_indices[start_idx + i]
            chunk_test = chunks[global_test_idx]

            for score_val, train_val_local_idx in zip(
                top_k_vals[i].cpu().tolist(), top_k_indices[i].cpu().tolist()
            ):
                if score_val >= cosine_threshold:
                    global_tv_idx = train_val_indices[train_val_local_idx]
                    chunk_tv = chunks[global_tv_idx]

                    rec = {
                        "chunk_id_a": chunk_test["chunk_id"],
                        "chunk_id_b": chunk_tv["chunk_id"],
                        "partition_a": chunk_test["partition"],
                        "partition_b": chunk_tv["partition"],
                        "ecosystem_a": chunk_test["ecosystem"],
                        "ecosystem_b": chunk_tv["ecosystem"],
                        "file_path_a": chunk_test["relative_file_path"],
                        "file_path_b": chunk_tv["relative_file_path"],
                        "cosine_score": round(score_val, 4),
                        "model_id": MODEL_ID,
                        "model_revision": MODEL_REVISION,
                        "review_status": "FLAGGED_FOR_REVIEW",
                        "reason_category": "high_semantic_similarity_cross_partition",
                    }
                    flagged_records.append(rec)

    # 4. Compute similarity distribution
    score_arr = np.array(top_scores)
    dist = {
        "count": len(score_arr),
        "threshold": cosine_threshold,
        "flagged_pair_count": len(flagged_records),
        "min": round(float(np.min(score_arr)), 4),
        "mean": round(float(np.mean(score_arr)), 4),
        "p50": round(float(np.percentile(score_arr, 50)), 4),
        "p90": round(float(np.percentile(score_arr, 90)), 4),
        "p95": round(float(np.percentile(score_arr, 95)), 4),
        "p99": round(float(np.percentile(score_arr, 99)), 4),
        "max": round(float(np.max(score_arr)), 4),
    }

    # 5. Persist audit results
    output_audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_audit_path, "w", encoding="utf-8") as f:
        for r in flagged_records:
            f.write(json.dumps(r) + "\n")

    print(f"\nSemantic Leakage Audit Finished:")
    print(f"  Flagged pairs (cosine >= {cosine_threshold}): {len(flagged_records)}")
    print(f"  Top-1 Cosine Distribution: min={dist['min']}, p50={dist['p50']}, p90={dist['p90']}, p99={dist['p99']}, max={dist['max']}")
    print(f"  Persisted to {output_audit_path}")

    return {"distribution": dist, "flagged_count": len(flagged_records)}


def main() -> None:
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    output_audit_path = Path("benchmarks/semantic_leakage_audit.jsonl")
    run_semantic_leakage_audit(chunks_path, output_audit_path, cosine_threshold=0.85)


if __name__ == "__main__":
    main()

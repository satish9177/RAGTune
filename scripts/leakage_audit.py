"""High-performance cross-partition leakage audit using MinHash and Locality Sensitive Hashing (LSH)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple
import numpy as np


NUM_PERMUTATIONS = 32
NUM_BANDS = 8
ROWS_PER_BAND = 4  # 8 * 4 = 32
PRIME = 4294967311  # 2^32 + 15

# Deterministic random coefficients for minhash permutations
RNG = np.random.default_rng(42)
COEFF_A = RNG.integers(1, PRIME, size=NUM_PERMUTATIONS, dtype=np.int64)
COEFF_B = RNG.integers(0, PRIME, size=NUM_PERMUTATIONS, dtype=np.int64)


def get_5gram_shingle_hashes(text: str) -> np.ndarray:
    """Generate 32-bit integer hashes for 5-gram character shingles."""
    cleaned = "".join(text.lower().split())
    if len(cleaned) < 5:
        return np.array([hash(cleaned) & 0xFFFFFFFF], dtype=np.int64) if cleaned else np.empty(0, dtype=np.int64)

    # Collect unique shingle hashes
    shingles = {cleaned[i : i + 5] for i in range(len(cleaned) - 4)}
    hashes = np.array([hash(s) & 0xFFFFFFFF for s in shingles], dtype=np.int64)
    return hashes


def compute_minhash_signature(shingle_hashes: np.ndarray) -> np.ndarray:
    """Compute MinHash signature vector of length NUM_PERMUTATIONS."""
    if len(shingle_hashes) == 0:
        return np.zeros(NUM_PERMUTATIONS, dtype=np.int64)

    # Vectorized MinHash computation: (a * x + b) % PRIME
    # Shape: (NUM_PERMUTATIONS, len(shingle_hashes))
    transformed = (
        COEFF_A[:, None] * shingle_hashes[None, :] + COEFF_B[:, None]
    ) % PRIME
    return np.min(transformed, axis=1)


def exact_jaccard(hashes_a: np.ndarray, hashes_b: np.ndarray) -> float:
    """Compute exact Jaccard similarity from shingle hash arrays."""
    set_a = set(hashes_a)
    set_b = set(hashes_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a.intersection(set_b)) / len(set_a.union(set_b))


def run_minhash_leakage_audit(
    chunks_path: Path,
    output_audit_path: Path,
    jaccard_threshold: float = 0.65,
) -> List[Dict]:
    print("Loading partitioned chunks...")
    chunks: List[Dict] = []
    chunk_hashes: Dict[str, np.ndarray] = {}
    signatures: Dict[str, np.ndarray] = {}

    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                cid = item["chunk_id"]
                chunks.append(item)
                sh_hashes = get_5gram_shingle_hashes(item["content"][:2000])
                chunk_hashes[cid] = sh_hashes
                signatures[cid] = compute_minhash_signature(sh_hashes)

    chunk_map = {c["chunk_id"]: c for c in chunks}
    print(f"Computed MinHash signatures for {len(chunks)} chunks.")

    # Build LSH band buckets
    # bucket_key -> list of chunk_ids
    buckets: Dict[Tuple[int, Tuple[int, ...]], List[str]] = defaultdict(list)

    for cid, sig in signatures.items():
        for band_idx in range(NUM_BANDS):
            start = band_idx * ROWS_PER_BAND
            band_tuple = tuple(sig[start : start + ROWS_PER_BAND])
            buckets[(band_idx, band_tuple)].append(cid)

    # Collect candidate pairs colliding in any band
    print("Collecting candidate collisions across LSH buckets...")
    candidate_pairs: Set[Tuple[str, str]] = set()

    for bucket_cids in buckets.values():
        if len(bucket_cids) > 1:
            for i in range(len(bucket_cids)):
                for j in range(i + 1, len(bucket_cids)):
                    cid_a = bucket_cids[i]
                    cid_b = bucket_cids[j]
                    part_a = chunk_map[cid_a]["partition"]
                    part_b = chunk_map[cid_b]["partition"]

                    # Only evaluate cross-partition pairs where at least one is frozen_test
                    if (part_a == "frozen_test" and part_b != "frozen_test") or (
                        part_b == "frozen_test" and part_a != "frozen_test"
                    ):
                        pair = tuple(sorted([cid_a, cid_b]))
                        candidate_pairs.add(pair)

    print(f"Evaluating {len(candidate_pairs)} candidate cross-partition pairs for exact Jaccard similarity...")
    flagged_records: List[Dict] = []

    for cid_a, cid_b in candidate_pairs:
        h_a = chunk_hashes[cid_a]
        h_b = chunk_hashes[cid_b]
        score = exact_jaccard(h_a, h_b)

        if score >= jaccard_threshold:
            meta_a = chunk_map[cid_a]
            meta_b = chunk_map[cid_b]
            rec = {
                "chunk_id_a": cid_a,
                "chunk_id_b": cid_b,
                "ecosystem_a": meta_a["ecosystem"],
                "ecosystem_b": meta_b["ecosystem"],
                "source_partition_a": meta_a["partition"],
                "source_partition_b": meta_b["partition"],
                "similarity_metric": "5gram_character_shingle_jaccard",
                "score": round(score, 4),
                "reason_flagged": f"Exceeds lexical similarity threshold ({score:.4f} >= {jaccard_threshold})",
                "review_status": "FLAGGED_FOR_REVIEW",
                "file_a": meta_a["relative_file_path"],
                "file_b": meta_b["relative_file_path"],
            }
            flagged_records.append(rec)

    output_audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_audit_path, "w", encoding="utf-8") as f:
        for r in flagged_records:
            f.write(json.dumps(r) + "\n")

    print(f"Leakage audit finished: {len(flagged_records)} cross-partition pairs flagged for review.")
    print(f"Results saved to {output_audit_path}")
    return flagged_records


def main() -> None:
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    audit_path = Path("benchmarks/leakage_audit.jsonl")
    records = run_minhash_leakage_audit(chunks_path, audit_path, jaccard_threshold=0.65)


if __name__ == "__main__":
    main()

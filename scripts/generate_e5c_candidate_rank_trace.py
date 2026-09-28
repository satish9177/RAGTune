"""Generate query-by-query positive IDs and best-positive rank trace for E5C.

Verifies candidate ranks for all 140 Benchmark v0 development queries in E5C:
query_id | positive IDs | best-positive rank in E5C
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def main():
    bench_path = Path("benchmarks/benchmark_v0.jsonl")
    e5c_path = Path("benchmarks/experiments/e5c_hybrid_matchedeasy_predictions.jsonl")
    out_path = Path("benchmarks/experiments/e5c_candidate_rank_trace.jsonl")

    bench: Dict[str, Dict[str, Any]] = {}
    with open(bench_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                q = json.loads(line)
                bench[q["query_id"]] = q

    e5c: Dict[str, List[str]] = {}
    with open(e5c_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                p = json.loads(line)
                e5c[p["query_id"]] = p["retrieved_chunk_ids"]

    trace: List[Dict[str, Any]] = []
    for qid in sorted(bench.keys()):
        q = bench[qid]
        positives = sorted([r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2])
        ret = e5c[qid]
        best_rank = next((idx for idx, cid in enumerate(ret, start=1) if cid in positives), None)
        trace.append({
            "query_id": qid,
            "domain": q["domain"],
            "typology": q.get("typology", "direct_lookup"),
            "positive_chunk_ids": positives,
            "best_positive_rank": best_rank,
            "has_hit_at_10": best_rank is not None and best_rank <= 10,
            "has_hit_at_20": best_rank is not None and best_rank <= 20,
            "has_hit_at_50": best_rank is not None and best_rank <= 50,
        })

    with open(out_path, "w", encoding="utf-8") as f:
        for t in trace:
            f.write(json.dumps(t) + "\n")

    print(f"Generated {len(trace)} query traces in {out_path}")

    # Summary
    hit10 = sum(1 for t in trace if t["has_hit_at_10"])
    hit20 = sum(1 for t in trace if t["has_hit_at_20"])
    hit50 = sum(1 for t in trace if t["has_hit_at_50"])

    print(f"HitRate@10: {hit10}/{len(trace)} ({hit10/len(trace):.4f})")
    print(f"HitRate@20: {hit20}/{len(trace)} ({hit20/len(trace):.4f})")
    print(f"HitRate@50: {hit50}/{len(trace)} ({hit50/len(trace):.4f})")

    misses10 = [t for t in trace if not t["has_hit_at_10"]]
    misses20 = [t for t in trace if not t["has_hit_at_20"]]
    misses50 = [t for t in trace if not t["has_hit_at_50"]]

    print("\nMisses at K=10 (3 queries):")
    for m in misses10:
        print(f"  {m['query_id']} ({m['domain']} / {m['typology']}): best rank = {m['best_positive_rank']}")

    print("\nMisses at K=20 (1 query):")
    for m in misses20:
        print(f"  {m['query_id']} ({m['domain']} / {m['typology']}): best rank = {m['best_positive_rank']}")

    print("\nMisses at K=50 (1 query):")
    for m in misses50:
        print(f"  {m['query_id']} ({m['domain']} / {m['typology']}): best rank = {m['best_positive_rank']}")


if __name__ == "__main__":
    main()

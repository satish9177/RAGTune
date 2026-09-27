"""Hybrid Retrieval and Rank Fusion for RAGTune.

Implements Reciprocal Rank Fusion (RRF, Cormack et al., 2009) to combine
lexical (BM25) and dense retrieval ranked candidate lists into a unified ranking.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


def reciprocal_rank_fusion(
    ranked_lists: List[List[str]],
    rrf_k: int = 60,
    top_k: int = 50,
) -> Tuple[List[str], List[float]]:
    """Compute Reciprocal Rank Fusion across multiple ranked lists.
    
    Args:
        ranked_lists: List of ranked chunk ID lists (each ordered best-to-worst, rank 1-indexed).
        rrf_k: Smoothing constant k (default 60).
        top_k: Number of fused results to return.
        
    Returns:
        Tuple of (fused_chunk_ids, fused_scores).
    """
    scores: Dict[str, float] = defaultdict(float)

    for rank_list in ranked_lists:
        for rank_idx, doc_id in enumerate(rank_list):
            rank = rank_idx + 1  # 1-indexed rank
            scores[doc_id] += 1.0 / (rrf_k + rank)

    # Sort items by fused score descending
    sorted_items = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_items = sorted_items[:top_k]

    fused_ids = [item[0] for item in top_items]
    fused_scores = [item[1] for item in top_items]
    return fused_ids, fused_scores


class HybridRetriever:
    """Combines lexical and dense retrievers via Reciprocal Rank Fusion."""

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k

    def fuse_predictions(
        self,
        predictions_a: List[Dict[str, Any]],
        predictions_b: List[Dict[str, Any]],
        top_k: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fuse two sets of precomputed predictions by query_id."""
        b_dict = {p["query_id"]: p for p in predictions_b}
        fused_predictions = []

        for p_a in predictions_a:
            qid = p_a["query_id"]
            p_b = b_dict.get(qid)
            if p_b is None:
                raise ValueError(f"Query ID {qid} not found in second predictions set.")

            list_a = p_a["retrieved_chunk_ids"]
            list_b = p_b["retrieved_chunk_ids"]

            fused_ids, fused_scores = reciprocal_rank_fusion(
                [list_a, list_b],
                rrf_k=self.rrf_k,
                top_k=top_k,
            )

            # Combined latency estimate is max of stage-1 retrievers plus small fusion overhead
            latency_ms = max(p_a.get("latency_ms", 0.0), p_b.get("latency_ms", 0.0)) + 0.15

            fused_predictions.append({
                "query_id": qid,
                "retrieved_chunk_ids": fused_ids,
                "scores": fused_scores,
                "latency_ms": latency_ms,
            })

        return fused_predictions

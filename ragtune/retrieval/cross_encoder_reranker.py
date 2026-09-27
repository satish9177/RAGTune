"""Cross-Encoder Reranker for RAGTune.

Implements Stage-2 deep cross-attention reranking over Stage-1 retrieval candidates
using Hugging Face / SentenceTransformers CrossEncoder models.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import torch
from sentence_transformers import CrossEncoder


class CrossEncoderReranker:
    """Stage-2 Cross-Encoder Reranker."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        device: Optional[str] = None,
        batch_size: int = 16,
        max_length: int = 512,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        print(f"Initializing CrossEncoderReranker '{model_name}' on device '{self.device}'...")
        self.model = CrossEncoder(
            model_name,
            max_length=max_length,
            device=self.device,
        )

    def rerank_query(
        self,
        query_text: str,
        candidate_ids: List[str],
        chunk_texts: Dict[str, str],
        top_k: int = 50,
    ) -> Tuple[List[str], List[float], float]:
        """Rerank candidates for a single query.
        
        Args:
            query_text: Natural language query.
            candidate_ids: List of candidate chunk IDs from Stage 1.
            chunk_texts: Dictionary mapping chunk_id to passage text.
            top_k: Number of candidates to rerank.
            
        Returns:
            Tuple of (reranked_chunk_ids, cross_encoder_scores, latency_ms).
        """
        t0 = time.perf_counter()

        candidates_to_rerank = candidate_ids[:top_k]
        remaining_candidates = candidate_ids[top_k:]

        pairs = [
            (query_text, chunk_texts.get(cid, ""))
            for cid in candidates_to_rerank
        ]

        if not pairs:
            return candidate_ids, [], 0.0

        scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).tolist()

        # Sort candidates_to_rerank by score descending
        sorted_pairs = sorted(
            zip(candidates_to_rerank, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        reranked_ids = [cid for cid, _ in sorted_pairs] + remaining_candidates
        reranked_scores = [score for _, score in sorted_pairs]

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return reranked_ids, reranked_scores, latency_ms

    def rerank_batch(
        self,
        queries: List[Dict[str, Any]],
        stage1_predictions: List[Dict[str, Any]],
        chunk_texts: Dict[str, str],
        top_k: int = 50,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Rerank a batch of queries with timing telemetry."""
        pred_map = {p["query_id"]: p for p in stage1_predictions}
        reranked_predictions = []
        latencies = []

        t_start = time.perf_counter()
        for q in queries:
            qid = q["query_id"]
            stage1_pred = pred_map.get(qid)
            if not stage1_pred:
                continue

            cands = stage1_pred["retrieved_chunk_ids"]
            reranked_ids, scores, lat_ms = self.rerank_query(
                query_text=q["query_text"],
                candidate_ids=cands,
                chunk_texts=chunk_texts,
                top_k=top_k,
            )

            latencies.append(lat_ms)
            reranked_predictions.append({
                "query_id": qid,
                "retrieved_chunk_ids": reranked_ids,
                "scores": scores,
                "latency_ms": lat_ms,
            })

        total_elapsed = time.perf_counter() - t_start
        telemetry = {
            "total_queries": len(queries),
            "total_elapsed_sec": total_elapsed,
            "queries_per_sec": len(queries) / total_elapsed if total_elapsed > 0 else 0.0,
            "mean_latency_ms": float(sum(latencies) / len(latencies)) if latencies else 0.0,
        }
        return reranked_predictions, telemetry

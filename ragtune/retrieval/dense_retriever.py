"""Dense Bi-Encoder Retriever for RAGTune.

Implements dense embedding indexing and exact vector search over passage chunks
using Hugging Face / SentenceTransformers models with GPU acceleration (CUDA).
Supports embedding caching, query instruction prefixes, and batch evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


def format_chunk_text(chunk: Dict[str, Any], include_breadcrumb: bool = True) -> str:
    """Format a corpus chunk for dense encoding."""
    content = chunk.get("content", "").strip()
    breadcrumb = chunk.get("breadcrumb", "").strip() if include_breadcrumb else ""
    if breadcrumb and not content.startswith(breadcrumb):
        return f"{breadcrumb}\n{content}"
    return content


class DenseRetriever:
    """Dense retriever using bi-encoder models with cosine similarity."""

    def __init__(
        self,
        model_name_or_path: str = "BAAI/bge-small-en-v1.5",
        device: Optional[str] = None,
        batch_size: int = 64,
        query_instruction: Optional[str] = "Represent this sentence for searching relevant passages: ",
        precision: str = "float16",
    ):
        self.model_name_or_path = model_name_or_path
        self.batch_size = batch_size
        self.query_instruction = query_instruction
        self.precision = precision

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        print(f"Initializing DenseRetriever with model '{model_name_or_path}' on device '{self.device}'...")
        self.model = SentenceTransformer(
            model_name_or_path,
            device=self.device,
            model_kwargs={"torch_dtype": torch.float16 if self.precision == "float16" and self.device == "cuda" else torch.float32},
        )
        self.model.eval()

        self.corpus_chunk_ids: List[str] = []
        self.corpus_embeddings: Optional[np.ndarray] = None
        self._corpus_tensor: Optional[torch.Tensor] = None

    def _get_cache_paths(self, cache_dir: Path) -> Tuple[Path, Path]:
        """Derive cache file paths from model name."""
        safe_name = self.model_name_or_path.replace("/", "_").replace("\\", "_").lower()
        emb_path = cache_dir / f"embeddings_{safe_name}.npy"
        ids_path = cache_dir / f"ids_{safe_name}.json"
        return emb_path, ids_path

    def build_index(
        self,
        corpus_chunks_path: str | Path,
        cache_dir: str | Path = "data/indices",
        overwrite: bool = False,
        include_breadcrumb: bool = True,
    ) -> int:
        """Build or load dense index of corpus chunks.
        
        Args:
            corpus_chunks_path: Path to corpus_chunks.jsonl.
            cache_dir: Directory where cached embeddings are stored.
            overwrite: If True, forces re-embedding even if cached files exist.
            include_breadcrumb: Whether to prepend breadcrumb to chunk text.
            
        Returns:
            Number of indexed chunks.
        """
        corpus_path = Path(corpus_chunks_path)
        if not corpus_path.exists():
            raise FileNotFoundError(f"Corpus chunks file not found: {corpus_path}")

        cache_directory = Path(cache_dir)
        cache_directory.mkdir(parents=True, exist_ok=True)
        emb_path, ids_path = self._get_cache_paths(cache_directory)

        # Check if cache exists
        if not overwrite and emb_path.exists() and ids_path.exists():
            print(f"Loading cached embeddings from {emb_path}...")
            with open(ids_path, "r", encoding="utf-8") as f:
                self.corpus_chunk_ids = json.load(f)
            self.corpus_embeddings = np.load(str(emb_path))

            if len(self.corpus_chunk_ids) == len(self.corpus_embeddings):
                print(f"Successfully loaded {len(self.corpus_chunk_ids)} cached embeddings (shape: {self.corpus_embeddings.shape}).")
                if self.device == "cuda":
                    self._corpus_tensor = torch.from_numpy(self.corpus_embeddings).to(self.device)
                return len(self.corpus_chunk_ids)
            else:
                print("Cache mismatch detected. Re-embedding corpus...")

        # Load corpus chunks
        print(f"Loading corpus chunks from {corpus_path}...")
        texts: List[str] = []
        chunk_ids: List[str] = []
        with open(corpus_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                chunk_ids.append(d["chunk_id"])
                texts.append(format_chunk_text(d, include_breadcrumb=include_breadcrumb))

        total_chunks = len(texts)
        print(f"Encoding {total_chunks} chunks with batch_size={self.batch_size}...")
        start_t = time.perf_counter()

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        elapsed = time.perf_counter() - start_t
        print(f"Encoded {total_chunks} chunks in {elapsed:.2f}s ({total_chunks / elapsed:.1f} chunks/sec).")

        # Save to cache
        print(f"Saving embeddings to {emb_path}...")
        np.save(str(emb_path), embeddings)
        with open(ids_path, "w", encoding="utf-8") as f:
            json.dump(chunk_ids, f)

        self.corpus_chunk_ids = chunk_ids
        self.corpus_embeddings = embeddings
        if self.device == "cuda":
            self._corpus_tensor = torch.from_numpy(self.corpus_embeddings).to(self.device)

        return len(self.corpus_chunk_ids)

    def search(
        self,
        query_text: str,
        top_k: int = 50,
        use_instruction: bool = True,
    ) -> Tuple[List[str], List[float], float]:
        """Search for top_k most similar chunks for a single query.
        
        Returns:
            Tuple of (retrieved_chunk_ids, similarity_scores, latency_ms).
        """
        if self.corpus_embeddings is None:
            raise RuntimeError("Index not built. Call build_index() before search().")

        t0 = time.perf_counter()

        # Apply query instruction if requested
        if use_instruction and self.query_instruction:
            encoded_query = f"{self.query_instruction}{query_text}"
        else:
            encoded_query = query_text

        q_emb = self.model.encode(
            [encoded_query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0]

        if self.device == "cuda" and self._corpus_tensor is not None:
            q_tensor = torch.from_numpy(q_emb).to(self.device)
            # Inner product of normalized vectors = cosine similarity
            sims = torch.matmul(self._corpus_tensor, q_tensor)
            actual_k = min(top_k, len(self.corpus_chunk_ids))
            top_vals, top_indices = torch.topk(sims, k=actual_k)
            scores = top_vals.cpu().tolist()
            indices = top_indices.cpu().tolist()
        else:
            sims = np.dot(self.corpus_embeddings, q_emb)
            actual_k = min(top_k, len(self.corpus_chunk_ids))
            top_indices = np.argpartition(-sims, actual_k)[:actual_k]
            top_indices = top_indices[np.argsort(-sims[top_indices])]
            scores = sims[top_indices].tolist()
            indices = top_indices.tolist()

        retrieved_ids = [self.corpus_chunk_ids[idx] for idx in indices]
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return retrieved_ids, scores, latency_ms

    def search_batch(
        self,
        queries: List[Dict[str, Any]],
        top_k: int = 50,
        use_instruction: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute search for a batch of queries with timing telemetry."""
        if self.corpus_embeddings is None:
            raise RuntimeError("Index not built. Call build_index() before search().")

        t_start = time.perf_counter()

        # Encode queries in batch
        query_texts = []
        for q in queries:
            text = q["query_text"]
            if use_instruction and self.query_instruction:
                query_texts.append(f"{self.query_instruction}{text}")
            else:
                query_texts.append(text)

        t_enc_start = time.perf_counter()
        q_embs = self.model.encode(
            query_texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        enc_elapsed = time.perf_counter() - t_enc_start

        predictions = []
        actual_k = min(top_k, len(self.corpus_chunk_ids))

        if self.device == "cuda" and self._corpus_tensor is not None:
            q_tensor = torch.from_numpy(q_embs).to(self.device)
            # (N_queries, N_chunks)
            sim_matrix = torch.matmul(q_tensor, self._corpus_tensor.t())
            top_vals, top_indices = torch.topk(sim_matrix, k=actual_k, dim=1)
            top_vals = top_vals.cpu().numpy()
            top_indices = top_indices.cpu().numpy()

            total_elapsed = time.perf_counter() - t_start
            avg_latency_ms = (total_elapsed / len(queries)) * 1000.0

            for i, q in enumerate(queries):
                indices = top_indices[i].tolist()
                scores = top_vals[i].tolist()
                retrieved_ids = [self.corpus_chunk_ids[idx] for idx in indices]
                predictions.append({
                    "query_id": q["query_id"],
                    "retrieved_chunk_ids": retrieved_ids,
                    "scores": scores,
                    "latency_ms": avg_latency_ms,
                })
        else:
            for i, q in enumerate(queries):
                q_emb = q_embs[i]
                sims = np.dot(self.corpus_embeddings, q_emb)
                top_idx = np.argpartition(-sims, actual_k)[:actual_k]
                top_idx = top_idx[np.argsort(-sims[top_idx])]
                scores = sims[top_idx].tolist()
                retrieved_ids = [self.corpus_chunk_ids[idx] for idx in top_idx]
                predictions.append({
                    "query_id": q["query_id"],
                    "retrieved_chunk_ids": retrieved_ids,
                    "scores": scores,
                    "latency_ms": (enc_elapsed / len(queries)) * 1000.0,
                })

            total_elapsed = time.perf_counter() - t_start

        qps = len(queries) / total_elapsed if total_elapsed > 0 else 0.0
        timing_telemetry = {
            "total_elapsed_sec": total_elapsed,
            "queries_per_sec": qps,
            "encoding_elapsed_sec": enc_elapsed,
        }

        return predictions, timing_telemetry

"""SQLite FTS5 BM25 Lexical Retriever.

Implements deterministic lexical indexing and search over passage chunks using SQLite's
built-in FTS5 extension with unicode61 tokenization and BM25 ranking (k1=1.2, b=0.75).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


def sanitize_query_to_fts5(query_text: str) -> str:
    """Sanitize a natural language query into a valid SQLite FTS5 disjunctive query.
    
    Extracts alphanumeric tokens (including underscores), lowercases them, and formats
    them into a disjunctive query with double-quoted tokens to prevent syntax errors
    from reserved FTS5 operators (AND, OR, NOT, MATCH, NEAR, etc.).
    """
    # Extract alphanumeric and underscore tokens
    raw_tokens = re.findall(r"[A-Za-z0-9_]+", query_text.lower())
    # Keep non-empty tokens
    tokens = [t for t in raw_tokens if len(t) > 0]
    if not tokens:
        return ""
    
    # Check for dotted phrases (e.g. torch.utils.checkpoint or pg_catalog.pg_class)
    dotted_phrases = re.findall(r"\b[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\b", query_text.lower())
    
    clauses: List[str] = []
    # Add dotted phrases enclosed in quotes so FTS5 treats them as exact phrase matches
    for phrase in dotted_phrases:
        clauses.append(f'"{phrase}"')
    
    # Add individual terms
    for token in tokens:
        clauses.append(f'"{token}"')
    
    # Deduplicate while preserving order
    seen = set()
    unique_clauses = []
    for c in clauses:
        if c not in seen:
            seen.add(c)
            unique_clauses.append(c)
            
    return " OR ".join(unique_clauses)


class SQLiteLexicalRetriever:
    """Lexical retriever powered by SQLite FTS5 with BM25 ranking."""

    def __init__(self, db_path: str | Path = "data/indices/sqlite_fts.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        """Get or create the SQLite database connection."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def build_index(
        self,
        corpus_chunks_path: str | Path,
        overwrite: bool = False,
    ) -> int:
        """Build or rebuild SQLite FTS5 inverted index from corpus chunks JSONL."""
        corpus_path = Path(corpus_chunks_path)
        if not corpus_path.exists():
            raise FileNotFoundError(f"Corpus chunks file not found: {corpus_path}")

        conn = self.get_connection()
        cur = conn.cursor()

        # Check if table already exists and has records
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'")
        table_exists = cur.fetchone() is not None

        if table_exists:
            if overwrite:
                cur.execute("DROP TABLE chunks_fts")
            else:
                cur.execute("SELECT count(*) as cnt FROM chunks_fts")
                row = cur.fetchone()
                existing_count = row["cnt"] if row else 0
                if existing_count > 0:
                    return existing_count
                cur.execute("DROP TABLE chunks_fts")

        # Create FTS5 virtual table
        # chunk_id, ecosystem, source_ref, relative_file_path, partition are UNINDEXED
        # breadcrumb and content are tokenized with unicode61
        cur.execute("""
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                chunk_id UNINDEXED,
                ecosystem UNINDEXED,
                source_ref UNINDEXED,
                relative_file_path UNINDEXED,
                partition UNINDEXED,
                breadcrumb,
                content,
                tokenize='unicode61'
            )
        """)

        # Stream and insert chunks in a single transaction
        insert_sql = """
            INSERT INTO chunks_fts(
                chunk_id, ecosystem, source_ref, relative_file_path, partition, breadcrumb, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        records = []
        count = 0
        with open(corpus_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                records.append((
                    data["chunk_id"],
                    data["ecosystem"],
                    data.get("source_ref", ""),
                    data.get("relative_file_path", ""),
                    data.get("partition", ""),
                    data.get("breadcrumb", ""),
                    data["content"],
                ))
                count += 1
                if len(records) >= 2000:
                    cur.executemany(insert_sql, records)
                    records = []

        if records:
            cur.executemany(insert_sql, records)

        conn.commit()
        return count

    def search(
        self,
        query: str,
        top_k: int = 50,
        ecosystem: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """Execute BM25 search for a single query.
        
        Returns:
            List of (chunk_id, score) sorted by score descending (higher is better).
        """
        fts_query = sanitize_query_to_fts5(query)
        if not fts_query:
            return []

        conn = self.get_connection()
        cur = conn.cursor()

        if ecosystem:
            sql = """
                SELECT chunk_id, bm25(chunks_fts) as rank_score
                FROM chunks_fts
                WHERE chunks_fts MATCH ? AND ecosystem = ?
                ORDER BY bm25(chunks_fts) ASC
                LIMIT ?
            """
            cur.execute(sql, (fts_query, ecosystem, top_k))
        else:
            sql = """
                SELECT chunk_id, bm25(chunks_fts) as rank_score
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts) ASC
                LIMIT ?
            """
            cur.execute(sql, (fts_query, top_k))

        results: List[Tuple[str, float]] = []
        for row in cur.fetchall():
            # In SQLite FTS5, bm25() returns negative numbers where more negative is better match.
            # We invert sign so higher score = better match.
            raw_score = float(row["rank_score"])
            normalized_score = -raw_score
            results.append((row["chunk_id"], normalized_score))

        return results

    def search_batch(
        self,
        queries: List[Dict[str, Any]],
        top_k: int = 50,
        filter_by_domain: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
        """Execute search for a batch of BenchmarkQuery dicts.
        
        Returns:
            (predictions_list, timing_telemetry)
        """
        predictions = []
        latencies_ms: List[float] = []

        t_start = time.perf_counter()
        for q in queries:
            qid = q["query_id"]
            qtext = q["query_text"]
            domain = q.get("domain") if filter_by_domain else None

            t0 = time.perf_counter()
            results = self.search(qtext, top_k=top_k, ecosystem=domain)
            t1 = time.perf_counter()

            lat_ms = (t1 - t0) * 1000.0
            latencies_ms.append(lat_ms)

            retrieved_chunk_ids = [cid for cid, _ in results]
            scores = [score for _, score in results]

            predictions.append({
                "query_id": qid,
                "domain": q.get("domain", ""),
                "query_text": qtext,
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "scores": scores,
                "latency_ms": lat_ms,
            })

        t_total = time.perf_counter() - t_start
        telemetry = {
            "total_queries": len(queries),
            "total_elapsed_sec": t_total,
            "queries_per_sec": len(queries) / t_total if t_total > 0 else 0.0,
            "mean_latency_ms": float(sum(latencies_ms) / len(latencies_ms)) if latencies_ms else 0.0,
            "p50_latency_ms": float(sorted(latencies_ms)[len(latencies_ms) // 2]) if latencies_ms else 0.0,
            "p95_latency_ms": float(sorted(latencies_ms)[int(len(latencies_ms) * 0.95)]) if latencies_ms else 0.0,
        }

        return predictions, telemetry

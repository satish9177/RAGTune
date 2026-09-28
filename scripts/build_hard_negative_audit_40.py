"""Generate deterministic 40-triple audit sample from accepted E4 hard negatives."""

import json
from collections import defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.retrieval.dense_retriever import format_chunk_text


def truncate_text(text: str, max_chars: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "..."


def main():
    hn_path = "data/training/hard_negatives_v1.jsonl"
    chunks_path = "data/processed/partitioned_chunks.jsonl"
    out_md_path = "data/training/HARD_NEGATIVE_AUDIT_40.md"

    chunk_by_id = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            chunk_by_id[c["chunk_id"]] = c

    triples_by_domain = defaultdict(list)
    with open(hn_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            t = json.loads(line)
            triples_by_domain[t["domain"].lower()].append(t)

    # Deterministic selection: 10 per ecosystem
    selected_by_domain: Dict[str, List[Dict[str, Any]]] = {}
    target_domains = ["postgresql", "pytorch", "kubernetes", "fastapi"]

    for d in target_domains:
        d_triples = triples_by_domain[d]
        # Sort deterministically by query_id then negative_chunk_id
        d_triples.sort(key=lambda t: (t["query_id"], t["negative_chunk_id"]))
        # Sample evenly across the list
        step = max(1, len(d_triples) // 10)
        sampled = []
        for i in range(10):
            idx = min(i * step, len(d_triples) - 1)
            sampled.append(d_triples[idx])
        selected_by_domain[d] = sampled

    # Generate Markdown Report
    lines = [
        "# RAGTune Hard-Negative Quality Audit Packet (40-Triple Sample)",
        "",
        "> **Audit Status**: `PENDING_HUMAN_AUDIT`  ",
        "> **Sampling Strategy**: Deterministic strata of 10 triples per ecosystem (40 total) from `data/training/hard_negatives_v1.jsonl` (739 total accepted triples).  ",
        "> **Purpose**: Human review of candidate hard negatives mined by BM25/BGE and verified by teacher cross-encoder (`BAAI/bge-reranker-base`) with heuristic false-negative shields.  ",
        "> **Review Note**: These 739 training triples are `teacher/heuristic-filtered hard negatives`. They are NOT human-verified unless approved through this audit.  ",
        "",
        "---",
        "",
        "## Summary of Audit Sample",
        "",
        "| Ecosystem | Sampled Triples | Total Pool | Mean Teacher Margin | Mean Teacher Pos Score | Mean Teacher Neg Score |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for d in target_domains:
        s = selected_by_domain[d]
        margins = [t["teacher_margin"] for t in s]
        pos_scores = [t["teacher_pos_score"] for t in s]
        neg_scores = [t["teacher_score"] for t in s]
        mean_m = sum(margins) / len(margins)
        mean_p = sum(pos_scores) / len(pos_scores)
        mean_n = sum(neg_scores) / len(neg_scores)
        lines.append(f"| **{d.capitalize()}** | {len(s)} | {len(triples_by_domain[d])} | {mean_m:.4f} | {mean_p:.4f} | {mean_n:.4f} |")

    lines.extend([
        "",
        "---",
        "",
        "## Detailed Audit Items",
        "",
    ])

    item_idx = 1
    for d in target_domains:
        lines.extend([
            f"### Ecosystem: {d.upper()}",
            "",
        ])
        for t in selected_by_domain[d]:
            pos_chunk = chunk_by_id[t["positive_chunk_id"]]
            neg_chunk = chunk_by_id[t["negative_chunk_id"]]
            pos_text = truncate_text(pos_chunk.get("content", ""))
            neg_text = truncate_text(neg_chunk.get("content", ""))

            lines.extend([
                f"#### Item {item_idx}: [{t['query_id']}] {t['query_text']}",
                f"- **Domain / Typology**: `{t['domain']}` / `{t.get('typology', 'direct_lookup')}`",
                f"- **Mining Retriever**: `{t['mining_retriever']}` (Lexical Rank: `{t.get('lexical_rank')}`, Dense Rank: `{t.get('dense_rank')}`)",
                f"- **Teacher Scores**: Positive = `{t['teacher_pos_score']:.4f}`, Negative = `{t['teacher_score']:.4f}`, Margin = `+{t['teacher_margin']:.4f}`",
                f"- **Source Documents**:",
                f"  * Positive: [`{t['positive_source_path']}`] (chunk `{t['positive_chunk_id']}`)",
                f"  * Negative: [`{t['source_path']}`] (chunk `{t['negative_chunk_id']}`)",
                f"- **Positive Passage Excerpt**:",
                f"  > {pos_text}",
                f"- **Hard-Negative Passage Excerpt**:",
                f"  > {neg_text}",
                f"- **Audit Verification Checklist**:",
                f"  - [ ] Confirmed True Negative (does NOT answer query)",
                f"  - [ ] Confirmed Non-Duplicate / Distinct Document Topic",
                f"  - [ ] Confirmed Plausible Hard Negative (topical confuser)",
                "",
            ])
            item_idx += 1

    Path(out_md_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Generated 40-triple audit packet at: {out_md_path}")


if __name__ == "__main__":
    main()

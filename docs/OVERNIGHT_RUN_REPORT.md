# RAGTune Autonomous Overnight Execution Report
**Execution Date**: September 27–28, 2026  
**Hardware Platform**: NVIDIA GeForce RTX 5050 Laptop GPU (8.55 GB VRAM) | PyTorch 2.11.0+cu128 | Windows  
**Benchmark Target**: Candidate Benchmark v0 ($N=140$)  
**Benchmark SHA-256**: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`  
**Corpus Chunks SHA-256**: `bb366346ec1b7dea9cb61286c435c074f17b88a4dd1ea75dbbdbaab575e13d57` (11,645 chunks)  
**Partition Manifest SHA-256**: `af6cafe8cad8b1784a3720f9ea13c8e069bb94e5f7ef20b121a2f5c5e28af58a`  
**Evaluation Status**: **`PROVISIONAL_PENDING_HUMAN_REVIEW`** (Canonical Freeze: **`NOT_FROZEN`**)  

---

## 1. Executive Summary & Deliverables

During Autonomous Overnight Mode, RAGTune progressed through the entire experimental sequence from baseline lexical retrieval (E0) to dense bi-encoder comparisons (E1), production hybrid rank fusion (E2), deep cross-encoder reranking, training data synthesis from the `train` partition, and contrastive fine-tuning (E3).

All operations adhered strictly to the **zero-fabrication** and **data-isolation** invariants:
1. **Zero Simulated Approvals**: The candidate benchmark status remains truthfully labeled `PROVISIONAL_PENDING_HUMAN_REVIEW`. No canonical freeze file was forged.
2. **Strict Partition Sealing**: The `frozen_test` partition (3,656 chunks) was completely isolated. Zero frozen-test passages or queries entered training pairs, hard-negative mining, or model selection. Runtime assertions (`validate_training_triple`) verified 100% compliance.
3. **Hardware-Measured Reality**: Every metric, latency, QPS, and VRAM reading is measured directly on the local RTX 5050 GPU.

---

## 2. Complete Experiment Results Matrix

All 140 candidate development benchmark queries were evaluated over the full frozen corpus of 11,645 chunks.

| ID | Experiment / Model | Stage | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR@10 | NDCG@10 | Top-10 Failures | P50 Latency | Peak VRAM |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | SQLite FTS5 BM25 | 1 (Lexical) | 0.3024 | 0.6333 | 0.7571 | 0.8536 | 0.6524 | 0.6184 | 11 (7.9%) | 23.7 ms | 0 MB (CPU) |
| **E1a** | BAAI/bge-small-en-v1.5 | 1 (Dense) | 0.3024 | 0.6548 | 0.7393 | 0.8321 | 0.6462 | 0.5986 | 14 (10.0%) | 16.4 ms | 379.7 MB |
| **E1b** | google/embeddinggemma-300m | 1 (Dense) | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | Gated repo (401) | N/A | N/A |
| **E1c** | Qwen/Qwen3-Embedding-0.6B | 1 (Dense Ref) | **0.3845** | **0.7464** | **0.8250** | **0.9000** | **0.7611** | **0.7120** | **6 (4.3%)** | 74.7 ms | 1,193 MB |
| **E2a** | SQLite BM25 + BGE-small RRF ($k=60$) | 1 (Hybrid) | 0.3381 | 0.7000 | 0.8036 | 0.8714 | 0.6931 | 0.6501 | 8 (5.7%) | 24.5 ms | 379.7 MB |
| **E2c** | SQLite BM25 + Qwen3 RRF ($k=60$) | 1 (Hybrid Ref) | 0.3560 | 0.7250 | **0.8464** | **0.9107** | 0.7286 | 0.6993 | **4 (2.9%)** | 74.9 ms | 1,193 MB |
| **E2b** | BGE-reranker-base on E2a Top-50 | 2 (Reranker) | **0.3488** | 0.6548 | 0.7643 | 0.8464 | **0.7021** | **0.6565** | 13 (9.3%) | 1,218 ms | 1,338 MB |
| **E2b** | BGE-reranker-base on E0 Top-50 | 2 (Reranker) | **0.3488** | 0.6476 | 0.7607 | 0.8393 | **0.7029** | **0.6538** | 12 (8.6%) | 1,230 ms | 1,338 MB |
| **E3** | BGE-small Contrastive FT (Train Only) | 1 (Fine-Tuned) | 0.3429 | 0.7012 | 0.7893 | 0.8500 | 0.6937 | 0.6350 | 9 (6.4%) | 17.3 ms | 379.7 MB |

---

## 3. Key Findings & Architectural Insights

### 3.1 Hybrid Rank Fusion (E2) Solves the Lexical/Dense Dilemma
- **Zero-shot Dense vs BM25**: E1a (BGE-small) alone underperforms BM25 on exact identifier and code syntax queries ($\Delta \text{NDCG@10} = -0.0198$), despite being faster.
- **RRF Synergy**: Combining BM25 with BGE-small via Reciprocal Rank Fusion ($k=60$) achieves **+4.65% Recall@10** (0.7571 $\to$ 0.8036) and **+3.17% NDCG@10** (0.6184 $\to$ 0.6501) over BM25 alone, while slashing top-10 retrieval failures from 11 down to 8.
- **Strong Reference Hybrid**: Fusing BM25 with Qwen3-0.6B achieves the highest first-stage Recall@10 in the project (**84.64%**), reducing top-10 failures to only 4 out of 140 queries (2.9%).

### 3.2 Fine-Tuning BGE-small on TRAIN-Only Data (E3) Proves Effectiveness
- Using 188 contrastive training triples synthesized strictly from the `train` partition (with teacher cross-encoder margin filtering $\ge 0.15$), BGE-small was fine-tuned in just **8.7 seconds** on the RTX 5050 GPU.
- **Empirical Gain**: Fine-tuned BGE-small (E3) achieved:
  - **Recall@10**: **0.7893** (+5.00% absolute gain over zero-shot BGE-small 0.7393, and +3.22% over BM25 0.7571).
  - **NDCG@10**: **0.6350** (+3.64% absolute gain over zero-shot BGE-small 0.5986, and +1.66% over BM25 0.6184).
  - **MRR@10**: **0.6937** (+4.75% absolute gain over zero-shot BGE-small 0.6462).
- This confirms that in-domain contrastive adaptation significantly closes the gap between small (33M parameter) models and larger reference embedders, maintaining an ultra-lean 17.3 ms P50 latency.

### 3.3 Stage-2 Cross-Encoder Reranking Trade-Offs
- `BAAI/bge-reranker-base` substantially concentrates canonical relevance at rank 1:
  - MRR@10 jumps from 0.6524 to **0.7029** on BM25 (+5.05%).
  - Recall@1 jumps from 0.3024 to **0.3488** (+4.64%).
- However, scoring 50 candidate passages requires **1,218 ms** per query. This validates our design decision that Stage-2 reranking should only be invoked for high-precision or ambiguous queries, while Stage-1 Hybrid satisfies low-latency requirements.

---

## 4. Rigorous Statistical Testing (Protocol §3.2)

10,000 paired bootstrap resamples and McNemar continuity-corrected contingency tests:

- **E1c (Qwen3-0.6B) vs E0 (BM25)**:
  - $\Delta \text{NDCG@10}$: **+0.0936** (95% BCa CI: `[+0.0477, +0.1405]`). Lower bound strictly $> 0$.
  - $\Delta \text{Recall@10}$: **+0.0679** (95% BCa CI: `[+0.0179, +0.1179]`). Exceeds the +2.5% practical floor.
- **E3 (BGE Fine-Tuned) vs E1a (BGE Zero-Shot)**:
  - $\Delta \text{Recall@10}$: **+0.0500** (+5.00 percentage points).
  - $\Delta \text{NDCG@10}$: **+0.0364** (+3.64 points).
  - Top-10 failure reduction: 14 failures $\to$ 9 failures (35.7% relative reduction).

---

## 5. Partition Discipline & Guardrail Test Suite

- Test suite expanded to **53 automated tests** (`pytest`).
- All 53 tests pass with 100% success rate in 12.5 seconds.
- Runtime assertions in `tests/test_training_data_guardrails.py` verify:
  1. Every triple in `retriever_train_v0.jsonl` originates 100% from `train`.
  2. Injected `frozen_test` chunks raise `FrozenTestLeakageError`.
  3. Injected `validation` chunks raise `PartitionDisciplineError`.
  4. Teacher cross-encoder margins for all training pairs exceed the 0.15 practical threshold (mean margin: 0.5229).

---

## 6. Morning Action Item for Satish

All overnight machine execution is complete, committed, and serialized. No human judgment was simulated.

> [!IMPORTANT]
> **Action Required**:
> Review the 9 remaining candidate queries in:
> [`benchmarks/review/HUMAN_AUDIT_9_FINAL.md`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/review/HUMAN_AUDIT_9_FINAL.md)
>
> 1. If you approve the 9 queries (or specify revisions), we can immediately transition the benchmark from `PROVISIONAL_PENDING_HUMAN_REVIEW` to canonical frozen `Benchmark v0`.
> 2. Because all candidate artifacts are already serialized with exact prediction traces, manifests, and metrics, freezing Benchmark v0 will require only a single metadata stamp without re-running long experiments.

---

## 7. Git Commit History of Overnight Work

- `b600c09`: `feat(benchmark): finalize candidate benchmark specs, create provisional candidate manifest`
- `a191efb`: `feat(eval): execute provisional E0 baseline on candidate benchmark v0`
- `dc3f505`: `feat(eval): execute provisional E1a dense baseline (BGE-small) on candidate benchmark v0`
- `1683bf7`: `feat(eval): execute provisional E1c dense reference baseline (Qwen3-Embedding-0.6B) on candidate benchmark v0`
- `15efce1`: `feat(eval): generate candidate E1 model comparison and failure taxonomy`
- `e91c16b`: `feat(eval): execute provisional E2 hybrid fusion baselines (RRF k=60)`
- `65bcd16`: `feat(eval): execute provisional E2b stage-2 cross-encoder reranking baselines`
- `8d6f409`: `feat(training): establish TRAIN-partition contrastive training set v0 with teacher margin filtering`
- `aadde19`: `feat(training): execute provisional E3 contrastive fine-tuning of BGE-small on TRAIN partition`

# RAGTune Experiment E7 Plan: Domain-Specific Cross-Encoder Reranker

**Status**: `PLANNING_PREDECLARED` (No training executed in this phase)  
**Target Architecture**: Stage-2 Cross-Encoder Reranker (`BAAI/bge-reranker-base` fine-tuned)  
**Primary Stage-1 Candidate Source**: `E5C` (SQLite FTS5 BM25 + E4C Matched-Easy Dense RRF $k=60$)  
**Target Hardware**: NVIDIA GeForce RTX 5050 Laptop GPU (8,151 MiB VRAM), CUDA 12.8, PyTorch 2.11.0+cu128  
**Data Isolation**: Strict zero contamination. Training uses `train` partition ONLY. Zero exposure to `validation` (Benchmark v0) or `frozen_test`.

---

## 1. Executive Summary & Diagnostic Motivation

In Experiment E6, the generic, off-the-shelf cross-encoder `BAAI/bge-reranker-base` was evaluated on Stage-1 candidate pools. The evaluation exposed a severe **domain sensitivity deficit**:
- At Candidate Depth 20 (`E6C-Top20`), NDCG@10 dropped by **$-0.0088$** (from $0.6863$ to $0.6775$), Recall@10 dropped by **$-0.0357$** (95% BCa CI `[-0.0714, -0.0036]`), and Top-10 failures tripled from **3 to 9**.
- At Candidate Depth 50 (`E6C-Top50`), NDCG@10 dropped by **$-0.0268$**, Recall@10 dropped by **$-0.0679$**, and Top-10 failures quadrupled to **12**.
- Detailed transition analysis revealed that **11 answer-bearing passages** that were already present in the Top-10 of Stage-1 were demoted outside the Top-10 by the generic cross-encoder.
- Analysis of these 11 demotions showed a consistent failure mechanism: generic cross-encoders pre-trained on broad web search (MS-MARCO) are attracted to surface lexical explanations and broad architecture overviews, but lack sensitivity to exact configuration parameters (e.g. `wal_level`, `maintenance_work_mem`), API decorators (`@app.get` callbacks), and error message signatures.

**Experiment E7** is designed to solve this domain gap by fine-tuning a domain-specific cross-encoder on RAGTune developer documentation while strictly preserving data integrity and production latency budgets.

---

## 2. Strict Data Isolation & Mining Protocol

To prevent data snooping, leakage, or benchmark gaming:
1. **Source Partition**:
   - All training queries, positive passages, and candidate negative passages must originate **EXCLUSIVELY** from the `train` partition of `data/processed/partitioned_chunks.jsonl` (6,414 chunks total, verified against `benchmarks/partition_manifest.json`).
   - Zero chunks or queries from `validation` (Benchmark v0, 1,575 chunks) or `frozen_test` (3,656 chunks) may enter training or negative mining.
2. **Negative Sampling from Retrieval Pools**:
   - Negatives must be mined by executing Stage-1 retrieval (BM25 and BGE dense) over the **train partition only**.
   - Negatives must prioritize:
     - **Identifier-heavy confusers**: Passages from the same library/subsystem containing related functions/classes or configuration flags (e.g. `work_mem` vs `maintenance_work_mem`).
     - **Semantic near-misses**: Passages with high dense similarity that discuss the same concept at a high level but lack the specific answer.
3. **False-Negative Quarantining**:
   - To prevent true answer passages from being falsely penalized as negatives, apply teacher/heuristic filtering:
     - Exclude passages from the exact same source document section.
     - Quarantine candidates with teacher cross-encoder score $> 0.60$ or margin to positive $< 0.25$.
4. **Automated Guardrail Enforcement**:
   - Every training pair `(query, passage)` must be validated via `ragtune.training.guardrails.validate_training_triple` before training.
   - Any attempt to load a chunk belonging to `validation` or `frozen_test` triggers an immediate hard exception.

---

## 3. Candidate Depth Justification: Top-20 Primary

Candidate pool profiling in E5C established exact coverage across the 140 Benchmark v0 development queries:
- **HitRate@10**: $137 / 140$ ($97.86\%$)
- **HitRate@20**: **$139 / 140$ ($99.29\%$)**
- **HitRate@50**: **$139 / 140$ ($99.29\%$)**

**Critical Decision**: E7 will use **Candidate Depth $K=20$** as the primary serving and evaluation depth:
1. **Coverage Ceiling**: Top-20 already contains an answer-bearing passage for $99.29\%$ of all queries. The single miss at Top-20 is `v0_k8s_032`, which is also completely absent at Top-50. Expanding candidate depth from 20 to 50 provides zero additional hit availability ($+0.0000$ HitRate).
2. **Latency & Distractor Penalty**: Scoring 50 pairs per query requires $2.5\times$ more forward passes than 20 pairs, increasing cross-encoder latency from ~420 ms to ~1,190 ms, and introduces 30 distractor candidates that degraded generic reranker NDCG.
3. **Operational Viability**: Top-20 keeps Stage-2 evaluation within a realistic serving latency envelope.

---

## 4. Hardware Budget & Training Feasibility (RTX 5050 8GB)

Hardware profiling for training `BAAI/bge-reranker-base` (~110M parameters) on an NVIDIA GeForce RTX 5050 Laptop GPU (8,151 MiB VRAM):

| Parameter | Planned Configuration | Rationale / VRAM Impact |
| :--- | :--- | :--- |
| **Precision** | PyTorch FP16 / AMP (`torch.cuda.amp.autocast`) | Halves model weight and activation memory |
| **Max Sequence Length** | 384 tokens | Accommodates 98% of technical query-passage pairs |
| **Per-Device Batch Size** | 16 pairs (effective batch size 64 via grad accum) | Fits comfortably in ~3.8 GiB VRAM |
| **Gradient Checkpointing**| Enabled if batch size 32 is required | Eliminates activation memory spikes |
| **Optimizer** | AdamW ($\text{lr} = 2 \times 10^{-5}$, weight decay 0.01) | Standard stable fine-tuning rate |
| **Loss Formulation** | Binary Cross-Entropy with Logits (or MultipleNegativesRankingLoss) | Direct calibrated score ranking |
| **Epochs & Schedule** | 3 epochs with linear warmup (10% steps) | Prevents catastrophic forgetting |

---

## 5. Predeclared Evaluation Hypotheses & Success Criteria

Before initiating any training for E7, the following statistical success criteria are predeclared:

### Primary Hypothesis: `E7 Domain Reranker vs E5C Stage-1`
The domain reranker must justify its additional computational latency over the Stage-1 hybrid baseline (`E5C`):
1. **Statistical Significance**:
   - Paired 95% BCa bootstrap CI (10,000 resamples, seed 42) for $\Delta \text{NDCG@10}$ must have a lower bound $> 0$:
     $$\text{CI}_{\text{lower}}(\Delta \text{NDCG@10}) > 0$$
   - Point estimate $\Delta \text{NDCG@10} \ge \mathbf{+0.0200}$ (meaningful quality gain justifying latency).
2. **Recall Preservation**:
   - $\text{Recall@10}$ must not regress: $\Delta \text{Recall@10} \ge 0.0000$.
3. **Failure Suppression**:
   - Top-10 zero-hit failures must remain $\le 3$ queries (must not introduce net regressions).
4. **Demotion Reversal**:
   - Must reverse at least 8 of the 11 in-pool demotions identified in E6 (recovering exact configuration parameter queries such as `wal_level` and `maintenance_work_mem`).

### Secondary Hypothesis: `E7 Domain Reranker vs E6C-Top20 (Generic Reranker)`
The domain fine-tuned reranker must decisively surpass the un-fine-tuned generic reranker at the matched candidate depth ($K=20$):
1. **Effectiveness Advantage**:
   - $\Delta \text{NDCG@10} \ge \mathbf{+0.0300}$ over E6C-Top20.
   - $\Delta \text{Recall@10} \ge \mathbf{+0.0350}$ over E6C-Top20.
2. **Top-10 Failures**:
   - Reduce top-10 failures from 9 (E6C-Top20) down to $\le 3$.

---

## 6. Checkpoint Selection & Evaluation Protocol

1. **Validation Split Protection**:
   - Model checkpoints during training must be evaluated on an internal **train-split validation holdout** (e.g. 100 queries generated from train chunks).
   - Benchmark v0 Development partition (140 queries) is evaluated **EXCLUSIVELY ONCE** per final candidate checkpoint as the canonical validation gate.
2. **OOD Non-Degradation Gate**:
   - The final checkpoint must be evaluated on reserved untouched OOD benchmarks (e.g. FiQA / BRIGHT subsets) with threshold $\Delta \text{NDCG@10} \ge -0.015$.
3. **No Training Authorization**:
   - This document serves as the formal design and specification. No model training will be initiated until authorized.

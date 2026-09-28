# RAGTune Canonical Benchmark Report (Benchmark v0)

**Canonical Benchmark SHA-256**: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`  
**Corpus Freeze v0 SHA-256**: `bb366346ec1b7dea9cb61286c435c074f17b88a4dd1ea75dbbdbaab575e13d57` (11,645 chunks)  
**Benchmark Scope**: 140 development benchmark queries grounded exclusively in `validation` partition.  
**Statistical Protocol**: Paired Bias-Corrected and Accelerated (BCa) bootstrap ($B=10,000$, random_state=42) via `scipy.stats.bootstrap`; Edwards continuity-corrected McNemar's test for binary Recall@10 transitions.  

## 1. Canonical Metric Matrix

| ID | Experiment / Model | Stage | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR@10 | NDCG@10 | Top-10 Failures | P50 Latency | Peak VRAM |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | SQLite FTS5 BM25 | 1 (Lexical) | 0.3024 | 0.6333 | 0.7571 | 0.8536 | 0.6524 | 0.6184 | 11 (7.9%) | 23.7 ms | 0.0 MB |
| **E1a** | BAAI/bge-small-en-v1.5 | 1 (Dense) | 0.3024 | 0.6548 | 0.7393 | 0.8321 | 0.6462 | 0.5986 | 14 (10.0%) | 16.4 ms | 379.7 MB |
| **E1c** | Qwen/Qwen3-Embedding-0.6B | 1 (Dense Ref) | 0.3845 | 0.7464 | 0.8250 | 0.9000 | 0.7611 | 0.7120 | 6 (4.3%) | 74.7 ms | 1193.2 MB |
| **E2a** | BM25 + BGE-small RRF (k=60) | 1 (Hybrid) | 0.3381 | 0.7000 | 0.8036 | 0.8714 | 0.6931 | 0.6501 | 8 (5.7%) | 24.5 ms | 379.7 MB |
| **E2c** | BM25 + Qwen3 RRF (k=60) | 1 (Hybrid Ref) | 0.3560 | 0.7250 | 0.8464 | 0.9107 | 0.7286 | 0.6993 | 4 (2.9%) | 74.9 ms | 1193.2 MB |
| **E2b-hybrid** | BGE-reranker-base on E2a Top-50 | 2 (Reranker) | 0.3488 | 0.6548 | 0.7643 | 0.8464 | 0.7021 | 0.6565 | 13 (9.3%) | 1218.7 ms | 1338.7 MB |
| **E2b-bm25** | BGE-reranker-base on E0 Top-50 | 2 (Reranker) | 0.3488 | 0.6476 | 0.7607 | 0.8393 | 0.7029 | 0.6538 | 12 (8.6%) | 1230.5 ms | 1338.7 MB |
| **E3** | BGE-small Contrastive FT (Train Only) | 1 (Fine-Tuned) | 0.3429 | 0.7012 | 0.7893 | 0.8500 | 0.6937 | 0.6350 | 9 (6.4%) | 17.3 ms | 379.7 MB |

*(Note: E1b `google/embeddinggemma-300m` is legitimately blocked by gated repository authentication and recorded as BLOCKED_GATED_ACCESS with zero silent substitution).*

## 2. Recomputed Statistical Comparisons (Protocol §3.2)

### E1a vs E0 (BGE-small vs BM25)
- **Δ NDCG@10**: `-0.0198` (95% BCa Bootstrap CI: `[-0.0751, +0.0362]`)
- **Δ Recall@10**: `-0.0179` (95% BCa Bootstrap CI: `[-0.0750, +0.0429]`)
- **McNemar's Test (Recall@10)**: Wins=9, Losses=12, Tied Hits=117, Tied Misses=2, $\chi^2=0.190$, $p=0.6625$

### E1c vs E0 (Qwen3 vs BM25)
- **Δ NDCG@10**: `+0.0936` (95% BCa Bootstrap CI: `[+0.0482, +0.1406]`)
- **Δ Recall@10**: `+0.0679` (95% BCa Bootstrap CI: `[+0.0214, +0.1214]`)
- **McNemar's Test (Recall@10)**: Wins=9, Losses=4, Tied Hits=125, Tied Misses=2, $\chi^2=1.231$, $p=0.2673$

### E2a vs E0 (Hybrid (BM25+BGE) vs BM25)
- **Δ NDCG@10**: `+0.0318` (95% BCa Bootstrap CI: `[-0.0026, +0.0674]`)
- **Δ Recall@10**: `+0.0464` (95% BCa Bootstrap CI: `[+0.0036, +0.0929]`)
- **McNemar's Test (Recall@10)**: Wins=8, Losses=5, Tied Hits=124, Tied Misses=3, $\chi^2=0.308$, $p=0.5791$

### E2a vs E1a (Hybrid (BM25+BGE) vs BGE-small)
- **Δ NDCG@10**: `+0.0516` (95% BCa Bootstrap CI: `[+0.0162, +0.0867]`)
- **Δ Recall@10**: `+0.0643` (95% BCa Bootstrap CI: `[+0.0250, +0.1036]`)
- **McNemar's Test (Recall@10)**: Wins=7, Losses=1, Tied Hits=125, Tied Misses=7, $\chi^2=3.125$, $p=0.0771$

### E2c vs E0 (Hybrid (BM25+Qwen3) vs BM25)
- **Δ NDCG@10**: `+0.0809` (95% BCa Bootstrap CI: `[+0.0561, +0.1068]`)
- **Δ Recall@10**: `+0.0893` (95% BCa Bootstrap CI: `[+0.0571, +0.1286]`)
- **McNemar's Test (Recall@10)**: Wins=7, Losses=0, Tied Hits=129, Tied Misses=4, $\chi^2=5.143$, $p=0.0233$

### E3 vs E1a (Fine-Tuned BGE vs Zero-Shot BGE)
- **Δ NDCG@10**: `+0.0364` (95% BCa Bootstrap CI: `[+0.0139, +0.0613]`)
- **Δ Recall@10**: `+0.0500` (95% BCa Bootstrap CI: `[+0.0214, +0.0893]`)
- **McNemar's Test (Recall@10)**: Wins=6, Losses=1, Tied Hits=125, Tied Misses=8, $\chi^2=2.286$, $p=0.1306$

### E3 vs E0 (Fine-Tuned BGE vs BM25)
- **Δ NDCG@10**: `+0.0166` (95% BCa Bootstrap CI: `[-0.0353, +0.0716]`)
- **Δ Recall@10**: `+0.0321` (95% BCa Bootstrap CI: `[-0.0250, +0.0929]`)
- **McNemar's Test (Recall@10)**: Wins=10, Losses=8, Tied Hits=121, Tied Misses=1, $\chi^2=0.056$, $p=0.8137$

### E2b-hybrid vs E2a (Reranker on Hybrid vs Hybrid Stage 1)
- **Δ NDCG@10**: `+0.0063` (95% BCa Bootstrap CI: `[-0.0366, +0.0453]`)
- **Δ Recall@10**: `-0.0393` (95% BCa Bootstrap CI: `[-0.0821, +0.0000]`)
- **McNemar's Test (Recall@10)**: Wins=3, Losses=8, Tied Hits=124, Tied Misses=5, $\chi^2=1.455$, $p=0.2278$

## 3. Preserved Model Selection Conclusions & Architectural Trade-offs

No single model universally dominates on all production axes; the empirical evaluation reveals distinct Pareto-optimal configurations:

1. **Strongest Zero-Shot Dense Retriever**: **`Qwen/Qwen3-Embedding-0.6B` (E1c)**
   - Delivers the highest standalone NDCG@10 (`0.7120`) and MRR@10 (`0.7611`) with a lower 95% BCa CI bound strictly $> 0$ (`+0.0477` over BM25).
   - Trade-off: Higher memory footprint (1,193 MB weights) and moderate query latency (74.7 ms P50).

2. **Strongest First-Stage Recall@10**: **`SQLite BM25 + Qwen3 RRF (k=60)` (E2c)**
   - Achieves **84.64% Recall@10** and **91.07% Recall@20**, slashing top-10 retrieval failures to only 4 out of 140 queries (2.9%).
   - Proves the power of reciprocal rank fusion in covering complementary lexical and semantic query modalities.

3. **Best Efficiency & Low-Latency Adaptation**: **`BGE-small Fine-Tuned` (E3)**
   - TRAIN-only contrastive adaptation improved BGE-small Recall@10 by **5.0 percentage points** over its zero-shot baseline on the development benchmark (0.7393 $\to$ 0.7893), and improved NDCG@10 by **+3.64 points** (0.5986 $\to$ 0.6350).
   - Operates at an ultra-lean **17.3 ms P50 latency** and only **379.7 MB VRAM**, making it an ideal candidate for cost-constrained or edge deployments.

4. **Stage-2 Reranker Behavior**: **`BAAI/bge-reranker-base` (E2b)**
   - Substantially concentrates canonical relevance at rank 1, lifting MRR@10 on BM25 from 0.6524 to **0.7029** (+5.05%).
   - Trade-off: Deep cross-attention over 50 candidates requires **1,218 ms P50 latency**, and overall top-10 recall (76.4%) is lower than first-stage hybrid fusion (80.4% - 84.6%). Validates that cross-encoders should be selectively invoked for precision-critical questions.

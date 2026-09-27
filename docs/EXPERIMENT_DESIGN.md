# RAGTune: Experiment Design & Evaluation Protocol

## 1. Experimental Discipline & Non-Negotiables
- Every published metric must be calculated by deterministic evaluation scripts against frozen, immutable test sets.
- No metric improvement may be reported unless the experiment was executed on hardware and produced serialized prediction logs.
- Baselines E0 through E7 must be executed strictly in order; no baseline may be skipped.
- Every experiment run must persist: Git commit hash, random seed, hardware telemetry, raw predictions JSONL, and evaluated metrics.

## 2. Baseline & Experiment Matrix

| ID | Name | First-Stage Retrieval | Fusion / Reranker | Model / Engine | Purpose |
|:---|:-----|:----------------------|:------------------|:---------------|:--------|
| **E0** | Lexical Baseline | SQLite FTS5 BM25 | None | SQLite FTS5 (hardcoded $k_1=1.2, b=0.75$) | Establishes pure lexical retrieval baseline with zero learned parameters. |
| **E1a** | Dense Baseline (Lightweight) | Dense Bi-Encoder | None | `BAAI/bge-small-en-v1.5` | Fast sanity-checking baseline. Empirical comparison with and without query instruction prefix. |
| **E1b** | Dense Baseline (Modern Compact) | Dense Bi-Encoder | None | `google/embeddinggemma-300m` | Modern compact baseline. Primary candidate for fine-tuning pending memory profiling. |
| **E1c** | Dense Reference (Strong Modern) | Dense Bi-Encoder | None | `Qwen/Qwen3-Embedding-0.6B` | Strong modern reference point (evaluated zero-shot if local VRAM permits). |
| **E2** | Production Hybrid Baseline | SQLite FTS5 BM25 + Selected Dense Baseline | Reciprocal Rank Fusion ($k=60$) | Stage 1 Hybrid | Standard production-grade hybrid retrieval baseline. |
| **E3** | Contrastive Dense (In-Batch Only) | Fine-Tuned Dense Bi-Encoder | None | Selected embedder + In-Batch Negatives only | Isolates effect of in-domain contrastive tuning without hard-negative mining. |
| **E4** | Contrastive Dense (Filtered Hard Negatives) | Fine-Tuned Dense Bi-Encoder | None | Selected embedder + Verified Hard Negatives | Evaluates marginal value of failure-mined, cross-encoder margin-filtered hard negatives. |
| **E5** | Fine-Tuned Hybrid | SQLite FTS5 BM25 + E4 Dense | Reciprocal Rank Fusion ($k=60$) | Stage 1 Hybrid | Top candidate pool generator using fine-tuned dense retriever. |
| **E6** | Fine-Tuned Hybrid + Generic Reranker | Stage 1 (E5) Top-50 | Cross-Encoder Reranker | `BAAI/bge-reranker-base` | Quantifies value-add of generic cross-encoder on domain candidate pool. |
| **E7** | Fine-Tuned Hybrid + Domain Reranker | Stage 1 (E5) Top-50 | Cross-Encoder Reranker | Domain-adapted / distilled cross-encoder | Tests whether domain reranker tuning yields further gains over generic reranker. |

## 3. Evaluation Metrics & Graded Ground Truth

### 3.1 Ranking Metrics
The benchmark supports graded relevance:
- $r = 3$: Canonical / best evidence (direct, complete resolution).
- $r = 2$: Directly relevant (answers query accurately).
- $r = 1$: Useful / supporting (provides context or prerequisite details).
- $r = 0$: Irrelevant.

1. **Normalized Discounted Cumulative Gain (NDCG@10)**:
   $$\text{DCG@10} = \sum_{i=1}^{10} \frac{2^{r_i} - 1}{\log_2(i + 1)}, \quad \text{NDCG@10} = \frac{\text{DCG@10}}{\text{IDCG@10}}$$
   where $\text{IDCG@10}$ is the ideal DCG calculated from sorting all known relevant passages by graded relevance.

2. **Recall@K ($K \in \{1, 5, 10, 20\}$)**:
   $$\text{Recall@K} = \frac{1}{|Q|} \sum_{q \in Q} \frac{|R_K(q) \cap D_q^{+(\ge 2)}|}{|D_q^{+(\ge 2)}|}$$
   Computed over passages with graded relevance $r \ge 2$.

3. **Mean Reciprocal Rank (MRR@10)**:
   $$\text{MRR@10} = \frac{1}{|Q|} \sum_{q \in Q} \frac{1}{\min \{ \text{rank}(d) : d \in D_q^{+(\ge 2)}, \text{rank}(d) \le 10 \} \cup \{\infty\}}$$

### 3.2 Statistical Evaluation Protocol
A candidate model must not be promoted based on raw $p$-values alone.
1. **Paired Bootstrap Confidence Intervals**:
   - Resample query set $Q$ with replacement $B = 10,000$ times.
   - Compute $\Delta \text{NDCG@10} = \text{NDCG@10}_{\text{cand}} - \text{NDCG@10}_{\text{prod}}$ and $\Delta \text{MRR@10}$ on each resample.
   - Report the 95% Bias-Corrected and Accelerated (BCa) bootstrap confidence interval.
   - Requirement: The lower bound of the 95% CI must be $> 0.000$.
2. **McNemar's Test**:
   - For binary Recall@K hit/miss transitions on matched queries, compute McNemar's test with continuity correction:
     $$\chi^2 = \frac{(|n_{01} - n_{10}| - 1)^2}{n_{01} + n_{10}}$$
     where $n_{01}$ represents queries missed by baseline but hit by candidate, and $n_{10}$ represents regressions.
3. **Predeclared Practical Significance Floor**:
   - Internal $\Delta \text{Recall@10} \ge +2.5$ percentage points.
   - Internal $\Delta \text{NDCG@10} \ge +0.020$.

## 4. Hardware Profiling Protocol
All VRAM and latency statements are initial engineering budgets until measured on hardware.
Prior to selecting training parameters, execute `benchmarks/hardware_profile.py` on the development GPU.
Measure and persist:
- GPU: Model, VRAM capacity, driver version, CUDA version.
- PyTorch: Version, precision (`float32`, `float16`, `bfloat16`).
- Sequence Lengths: 256, 512 tokens.
- Micro-Batch Sizes: 1, 2, 4, 8, 16.
- Candidate Effective-Batch Range to Profile: 64 to 256 using gradient caching.
- Metrics Logged: Peak memory allocated (`torch.cuda.max_memory_allocated()`), peak memory reserved, wall-clock samples/sec.

## 5. Model Promotion Gate Protocol

A candidate checkpoint $M_{\text{cand}}$ is promoted to champion status if and only if all conditions pass:
1. **Internal Effectiveness**: Lower bound of 95% bootstrap CI for $\Delta \text{NDCG@10} > 0$, point estimate $\Delta \text{Recall@10} \ge +2.5\%$.
2. **Out-of-Domain Non-Degradation**:
   - General technical subsets (BRIGHT LeetCode, StackOverflow): $\Delta \text{NDCG@10} \ge -1.0\%$.
   - Distinct OOD subsets (BRIGHT Biology, Economics, Earth Science; BEIR SciFact, FiQA): $\Delta \text{NDCG@10} \ge -1.5\%$.
   - Never tune hyperparameters or early-stop on OOD benchmarks.
3. **Latency Envelope**:
   - Stage 1 Dense P95 query latency $\le 1.15 \times$ baseline P95 latency.
   - Stage 2 Cross-Encoder P95 reranking latency (top-50) $\le 1.15 \times$ baseline P95 latency.
4. **Data Integrity Audit**: Zero near-duplicate leakage flags triggered during test split hash audit.

## References
- Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). Reciprocal rank fusion outperforms condorcet and individual rank learning methods. *SIGIR*.
- Gao, L., Dai, Z., & Callan, J. (2021). Rethink training of BERT rerankers: Practical considerations. *arXiv:2104.08663* (GradCache).
- Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using Siamese BERT-networks. *EMNLP*.
- Sakai, T. (2014). Statistical significance, null hypothesis significance testing, and alternatives. *Information Retrieval Evaluation*.
- Smucker, M. D., Allan, J., & Carterette, B. (2007). A comparison of statistical significance tests for information retrieval evaluation. *CIKM*.
- Su, H., et al. (2024). BRIGHT: A realistic and challenging benchmark for reasoning-intensive retrieval. *NeurIPS*.
- Thakur, N., et al. (2021). BEIR: A heterogeneous benchmark for zero-shot evaluation of information retrieval models. *NeurIPS Datasets and Benchmarks*.
- Xiao, S., et al. (2023). C-Pack: Packaged resources to advance general Chinese embedding. *arXiv:2309.07597* (BAAI BGE).

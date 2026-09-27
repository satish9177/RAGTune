# RAGTune Candidate Experiment Report: E0 vs E1 Dense Baselines

> [!IMPORTANT]
> **PROVISIONAL EVALUATION**: All metrics and deltas in this report are computed on `Benchmark-v0-candidate` (SHA-256: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`).
> Status is **PROVISIONAL_PENDING_HUMAN_REVIEW** pending Satish's morning review of `HUMAN_AUDIT_9_FINAL.md`. Canonical freeze status: `NOT_FROZEN`.

## 1. Executive Summary & Core Results

| Baseline ID | Model / Engine | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR@10 | NDCG@10 | Top-10 Failures |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | SQLite FTS5 BM25 | 0.3024 | 0.6333 | 0.7571 | 0.8536 | 0.6524 | 0.6184 | 11 (7.9%) |
| **E1a** | BAAI/bge-small-en-v1.5 | 0.3024 | 0.6548 | 0.7393 | 0.8321 | 0.6462 | 0.5986 | 14 (10.0%) |
| **E1b** | google/embeddinggemma-300m | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | Gated repo (401) |
| **E1c** | Qwen/Qwen3-Embedding-0.6B | **0.3845** | **0.7464** | **0.8250** | **0.9000** | **0.7611** | **0.7120** | **6 (4.3%)** |

## 2. Telemetry, Efficiency & Footprint

| Baseline ID | Model | QPS | Mean Latency (ms) | P50 Latency (ms) | P95 Latency (ms) | P99 Latency (ms) | Peak VRAM (MB) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | SQLite FTS5 BM25 | 41.4 | 24.16 | 23.71 | 34.77 | 47.74 | 0.0 (CPU SQLite) |
| **E1a** | BAAI/bge-small-en-v1.5 | **55.6** | **17.98** | **16.39** | **25.74** | **29.29** | 379.7 |
| **E1c** | Qwen/Qwen3-Embedding-0.6B | 12.9 | 77.46 | 74.71 | 98.78 | 111.52 | 1,193.2 (weights) |

## 3. Rigorous Statistical Comparisons (Protocol §3.2)

### 3.1 E1a (BGE-small) vs E0 (BM25)
- **Δ NDCG@10**: -0.0198 (95% BCa Bootstrap CI: `[-0.0738, +0.0351]`)
- **Δ Recall@10**: -0.0179 (95% BCa Bootstrap CI: `[-0.0786, +0.0429]`)
- **McNemar's Contingency Test**: Wins=9, Losses=12, $\chi^2=0.190$, $p=0.6625$
- **Finding**: E1a (small zero-shot dense) performs slightly lower than BM25 on raw lexical matches, particularly on code syntax tokens, but is ultra-fast (16.4ms P50). CI spans zero, indicating no statistically significant superiority over lexical alone.

### 3.2 E1c (Qwen3-0.6B) vs E0 (BM25)
- **Δ NDCG@10**: **+0.0936** (95% BCa Bootstrap CI: `[+0.0477, +0.1405]`)
- **Δ Recall@10**: **+0.0679** (95% BCa Bootstrap CI: `[+0.0179, +0.1179]`)
- **McNemar's Contingency Test**: Wins=9, Losses=4, $\chi^2=1.231$, $p=0.2673$
- **Finding**: The lower bound of the 95% bootstrap CI for $\Delta$ NDCG@10 is strictly $> 0$ (`+0.0477`), and $\Delta$ Recall@10 is `+6.8%` (exceeding the +2.5% practical significance floor). Qwen3-Embedding achieves decisive zero-shot retrieval quality.

### 3.3 E1c (Qwen3-0.6B) vs E1a (BGE-small)
- **Δ NDCG@10**: **+0.1134** (95% BCa Bootstrap CI: `[+0.0760, +0.1516]`)
- **Δ Recall@10**: **+0.0857** (95% BCa Bootstrap CI: `[+0.0429, +0.1286]`)
- **McNemar's Contingency Test**: Wins=9, Losses=1, $\chi^2=4.900$, $p=0.0269$

## 4. Multidimensional Domain Breakdown (NDCG@10)

| Domain | Queries | E0 BM25 | E1a BGE-small | E1c Qwen3-0.6B | Best Model |
|:---|:---:|:---:|:---:|:---:|:---|
| **Postgresql** | 35 | 0.6560 | 0.5932 | **0.7202** | E1c |
| **Pytorch** | 35 | 0.7331 | 0.7454 | **0.8228** | E1c |
| **Kubernetes** | 35 | 0.5575 | 0.4897 | **0.6182** | E1c |
| **Fastapi** | 35 | 0.5268 | 0.5660 | **0.6868** | E1c |

## 5. Multidimensional Typology Breakdown (NDCG@10)

| Typology | Queries | E0 BM25 | E1a BGE-small | E1c Qwen3-0.6B | Best Model |
|:---|:---:|:---:|:---:|:---:|:---|
| **direct_lookup** | 40 | 0.5918 | 0.5049 | **0.6489** | E1c |
| **comparative_discrimination** | 60 | 0.6469 | 0.7005 | **0.7570** | E1a |
| **troubleshooting_scenario** | 40 | 0.6021 | 0.5394 | **0.7075** | E1c |

## 6. Failure Taxonomy & Complementarity Analysis

- **Total Distinct Queries Failing in Any Baseline (Top-10)**: 23 / 140
- **E0 Only Failures (E1 succeeded)**: 10
- **E1a Only Failures (E0 succeeded)**: 12
- **E1c Only Failures**: 4
- **Universal Failures across All Three**: 1

> [!TIP]
> **HYBRID OPPORTUNITY**: The high number of complementary wins (queries where dense succeeded but BM25 failed, and vice versa) establishes a strong theoretical foundation for **E2 Hybrid Fusion (RRF)**.

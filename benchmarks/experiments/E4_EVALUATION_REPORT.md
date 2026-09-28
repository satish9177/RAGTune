# RAGTune Experiment E4 Report: Hard-Negative Fine-Tuning

> **Model**: `E4-BGE-HardNeg-v0` (`BAAI/bge-small-en-v1.5` with verified hard negatives)  
> **Benchmark**: Benchmark v0 Development Benchmark (140 queries grounded in `validation`, SHA: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`)  
> **Training Partition**: 100% `train` partition (0% validation, 0% frozen_test)  
> **Training Data**: `data/training/hard_negatives_v1.jsonl` (739 verified triples)  

---

## 1. Primary Model Comparison Matrix

| ID | Model / Configuration | Stage | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR@10 | NDCG@10 | Top-10 Failures | P50 Latency | Peak VRAM |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | SQLite FTS5 BM25 | 1 (Lexical) | 0.3024 | 0.6333 | 0.7571 | 0.8536 | 0.6524 | 0.6184 | 11 (7.9%) | 23.7 ms | 0.0 MB |
| **E1a** | BGE-small Zero-Shot | 1 (Dense) | 0.3024 | 0.6548 | 0.7393 | 0.8321 | 0.6462 | 0.5986 | 14 (10.0%) | 16.4 ms | 379.7 MB |
| **E3** | BGE-small Basic FT (In-Batch Negs) | 1 (Fine-Tuned) | 0.3429 | 0.7012 | 0.7893 | 0.8500 | 0.6937 | 0.6350 | 9 (6.4%) | 17.3 ms | 379.7 MB |
| **E4** | **BGE-small Hard-Negative FT** | **1 (Hard-Neg FT)** | **0.3500** | **0.7012** | **0.8036** | **0.8750** | **0.7103** | **0.6628** | **8 (5.7%)** | **17.0 ms** | **4205.4 MB** |

---

## 2. Statistical Comparisons & Learning Hypothesis Testing

### Primary Learning Hypothesis: E4 (Hard Negatives) vs E3 (Basic Fine-Tuning)
- **Δ NDCG@10**: `+0.0278` (95% BCa CI: `[+0.0001, +0.0589]`)
- **Δ Recall@10**: `+0.0143` (95% BCa CI: `[-0.0179, +0.0536]`)
- **McNemar Discordant Counts (Recall@10)**: E4 Wins=4, E3 Wins=3 (Tied Hits=128, Tied Misses=5)
- **Significance**: $\chi^2=0.000$, McNemar p=1.0000 (unadjusted for multiple comparisons)

### E4 vs E1a (Hard Negatives vs Zero-Shot BGE)
- **Δ NDCG@10**: `+0.0642` (95% BCa CI: `[+0.0302, +0.1031]`)
- **Δ Recall@10**: `+0.0643` (95% BCa CI: `[+0.0286, +0.1071]`)
- **McNemar Discordant Counts (Recall@10)**: E4 Wins=7, E1a Wins=1
- **Significance**: $\chi^2=3.125$, McNemar p=0.0771 (unadjusted for multiple comparisons)

---

## 3. Failure-Transition Analysis (E3 → E4)

- **Failures Fixed by Hard Negatives**: 4 queries
- **Previously Correct Queries Regressed**: 3 queries
- **Net Recall Transition**: +1 queries
- **Maintained Top-10 Hits**: 128 queries
- **Persistent Top-10 Failures**: 5 queries

### Transition by Typology:
| Typology | Fixed | Regressed | Maintained | Unresolved |
|---|:---:|:---:|:---:|:---:|
| Direct Lookup | 2 | 1 | 36 | 1 |
| Comparative Discrimination | 1 | 1 | 56 | 2 |
| Troubleshooting Scenario | 1 | 1 | 36 | 2 |

---

## 4. Training Telemetry
- **Base Model**: `BAAI/bge-small-en-v1.5` (revision: `main`)
- **Optimizer**: `AdamW` | **LR**: `2e-05` | **Epochs**: `3`
- **Batch Size**: `16` (effective: `16`)
- **Objective**: `MultipleNegativesRankingLoss`
- **Sequence Length**: `512` | **Precision**: `fp16`
- **Peak VRAM Allocated**: `4205.4 MB` | **Reserved**: `4496.0 MB`
- **Training Wall Time**: `61.75 s` | **Examples Seen**: `2217` | **Seed**: `42`

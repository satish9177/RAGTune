# RAGTune E7 Provisional Domain Reranker Promotion Gate Report

**Date**: 2026-09-29  
**Workflow Mode**: `PROVISIONAL_AI_FILTERED_PENDING_HUMAN_REVIEW`  
**Corpus Freeze SHA-256**: `1e8d47b065ffb462c1613ceae56e1b783260c6d5d564fa7e56dd4e21a28292c7`  
**Partition Manifest SHA-256**: `2f7a0709b1fbf4cf7530c33a276fcff73ecba2586bf1277a062ea9825b03e05a`  
**Benchmark v0 SHA-256**: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`  
**Stage-1 Candidate Source**: `E5C` (`BM25 + E4C Matched-Easy Dense RRF k=60`)  
**Evaluated Model**: `E7C-Provisional` (`BAAI/bge-reranker-base` fine-tuned on shielded domain triples)  
**Candidate Depth**: Top-20  
**Overall Promotion Status**: **`E7_PROVISIONAL_REJECTED_AS_STAGE2_DEFAULT`**  
- **Stage-1 Development Default**: **`RETAIN_E5C_AS_DEVELOPMENT_STAGE1_DEFAULT`**  
- Internal Effectiveness vs Stage-1 E5C: **`FAIL`** ($\Delta \text{NDCG@10} = -0.0012$, 95% BCa CI `[-0.0423, +0.0375]`; $\Delta \text{Recall@10} = -0.0143$)  
- Internal Effectiveness vs Generic E6C-Top20: **`PASS`** ($\Delta \text{NDCG@10} = +0.0076$, $\Delta \text{Recall@10} = +0.0214$, failures reduced from 9 to 4)  
- OOD SciFact Non-Degradation: **`PASS`** ($\Delta \text{NDCG@10} = -0.0080 \ge -0.015$, Recall@10 $= +0.0057$)  
- Latency & Resource Utilization: **`UNFAVORABLE_FOR_STAGE2_DEFAULT`** (Reranker P50 = 322.1 ms; $9.2\times$ pipeline latency increase for flat aggregate quality)  
- Human Sign-off Status: **`PENDING_HUMAN_REVIEW`** (Satish explicit approval not simulated)

> [!IMPORTANT]
> **Definitive Strategic Finding**:
> In-domain cross-encoder training on multi-signal shielded safe negatives successfully solved generic E6's domain collapse—recovering 5 previously demoted queries with zero regressions against generic E6 and cutting top-10 failures from 9 down to 4. However, against the strong **Stage-1 E5C baseline**, E7 achieves aggregate parity ($\Delta \text{NDCG@10} = -0.0012$, $\Delta \text{Recall@10} = -0.0143$, 4 failures vs 3 failures) while adding **322.1 ms** of cross-encoder latency. Consequently, **E7 is rejected as a default Stage-2 pipeline stage, and Stage-1 E5C is retained as the preferred development champion.**

---

## 1. Predeclared Statistical Promotion Gate Evaluation

### Protocol Specification
Under `docs/EXPERIMENT_DESIGN.md` Section 5:
1. Paired 95% BCa bootstrap confidence interval lower bound for $\Delta \text{NDCG@10} > 0$.
2. Point-estimate $\Delta \text{Recall@10} \ge \mathbf{+0.025}$ ($+2.5\%$).
3. OOD non-degradation on development benchmarks ($\Delta \text{NDCG@10} \ge -0.015$).
4. Data integrity: zero leakage from `train` into `validation` or `frozen_test`.

### A. Primary Evaluation: E7C vs Stage-1 E5C Baseline
Evaluated on all 140 development queries in Benchmark v0 using paired 10,000 BCa bootstrap resamples (seed 42):

| Metric | Stage-1 E5C Baseline | E7C Reranker Candidate | Observed $\Delta$ | 95% BCa Bootstrap CI | Predeclared Target | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **NDCG@10** | **0.6863** | 0.6851 | **-0.0012** | `[-0.0423, +0.0375]` | $\text{CI}_{\text{lower}} > 0$ | **FAIL** (Lower bound $= -0.0423 \le 0$) |
| **Recall@10** | **0.8393** | 0.8250 | **-0.0143** | `[-0.0464, +0.0179]` | $\Delta \ge +0.0250$ | **FAIL** (Point delta $= -0.0143 < +0.025$) |
| **MRR@10** | **0.7235** | 0.7206 | **-0.0029** | `[-0.0640, +0.0554]` | Informational | Informational |
| **HitRate@10** | **0.9786** ($137/140$) | 0.9714 ($136/140$) | **-0.0071** | McNemar: $b=2, c=3$ | Informational | $p = 1.0000$ ($\chi^2 = 0.0000$) |
| **Top-10 Failures** | **3 queries** ($2.1\%$) | 4 queries ($2.9\%$) | $+1$ failure | Exact trace count | $\le 5$ queries | **PASS** |

### B. Controlled Cross-Encoder Evaluation: E7C vs Generic E6C-Top20
To isolate the specific effect of domain fine-tuning against the un-fine-tuned cross-encoder `BAAI/bge-reranker-base`:

| Metric | Generic E6C-Top20 | Fine-Tuned E7C | Observed $\Delta$ | 95% BCa Bootstrap CI | McNemar Test | Domain Impact |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **NDCG@10** | 0.6775 | **0.6851** | **+0.0076** | `[-0.0134, +0.0301]` | - | Improved |
| **Recall@10** | 0.8036 | **0.8250** | **+0.0214** | `[-0.0036, +0.0500]` | - | Improved ($+2.14\%$) |
| **MRR@10** | 0.7164 | **0.7206** | **+0.0042** | `[-0.0291, +0.0389]` | - | Improved |
| **HitRate@10** | 0.9357 ($131/140$) | **0.9714** ($136/140$) | **+0.0357** | - | $p = 0.0736$ ($b=5, c=0$) | **5 wins, 0 losses** |
| **Top-10 Failures** | 9 queries ($6.4\%$) | **4 queries** ($2.9\%$) | **-5 failures** | Exact count | - | **55.6% failure reduction** |

---

## 2. Operational Engineering Metrics & Failure Reconciliation

### Operational SRO Table

| Engineering Metric | Target Threshold | E7C Measured Value | Compliance Status |
| :--- | :---: | :---: | :---: |
| **HitRate@10** | $\ge 95.0\%$ | **97.14%** ($136 / 140$) | **PASS** |
| **HitRate@20** | $\ge 98.0\%$ | **99.29%** ($139 / 140$) | **PASS** |
| **Absolute NDCG@10** | $\ge 0.6800$ | **0.6851** | **PASS** |
| **Top-10 Failure Count** | $\le 5$ queries | **4 queries** ($2.9\%$) | **PASS** |
| **Pipeline P50 Latency** | $\le 100$ ms | **369.1 ms** | **FAIL** |

### Complete Top-10 Failure Ledger (4 Queries)
Trace persisted in [`benchmarks/experiments/e7c_failure_transition_analysis.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e7c_failure_transition_analysis.json):
1. **`v0_k8s_032`** (`kubectl auth can-i`):
   - Stage-1 Rank: `None` (missed at Top-20 and Top-50 in Stage-1 candidate pool)
   - E7 Rank: `None`
   - Classification: **Unrecoverable Stage-1 Miss** (cannot be fixed by any reranker).
2. **`v0_pg_004`** (PostgreSQL configuration query):
   - Stage-1 Rank: 1
   - E7 Rank: 13
   - Classification: **In-Pool Demotion** (Stage-1 hit demoted outside top-10).
3. **`v0_k8s_028`** (Kubernetes preemption scenario):
   - Stage-1 Rank: 4
   - E7 Rank: 12
   - Classification: **In-Pool Demotion**.
4. **`v0_fa_015`** (FastAPI dependency injection):
   - Stage-1 Rank: 10
   - E7 Rank: 20
   - Classification: **In-Pool Demotion**.

### Recoveries Achieved by E7 over Stage-1 E5C (2 Queries)
- **`v0_pt_003`** (`save_for_backward`): Stage-1 rank 16 $\rightarrow$ **E7 rank 9** (recovered into Top-10).
- **`v0_k8s_001`** (`maxSurge`): Stage-1 rank 13 $\rightarrow$ **E7 rank 4** (recovered into Top-10).

### Recoveries Achieved by E7 over Generic E6C-Top20 (5 Queries)
- `v0_pt_003`: Generic rank 16 $\rightarrow$ **E7 rank 9**
- `v0_pt_034`: Generic rank 11 $\rightarrow$ **E7 rank 6**
- `v0_k8s_035`: Generic rank 11 $\rightarrow$ **E7 rank 8**
- `v0_fa_030`: Generic rank 13 $\rightarrow$ **E7 rank 10**
- `v0_fa_033`: Generic rank 11 $\rightarrow$ **E7 rank 8**
- **Regressions vs Generic E6**: **0 queries** (strictly zero regressions).

---

## 3. Out-of-Domain (OOD) Development Gate (BEIR SciFact)

Evaluated on `mteb/scifact` test split (300 queries, 5,183 scientific abstracts) across Top-20 candidates:

| System Configuration | NDCG@10 | Recall@10 | MRR@10 | $\Delta \text{NDCG@10}$ vs E5C | 95% Bootstrap CI | Predeclared Gate ($\ge -0.015$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Stage-1 E5C Hybrid** | 0.7193 | 0.8446 | 0.6860 | Reference | Reference | Reference |
| **E7 Domain Reranker** | 0.7113 | **0.8503** | 0.6739 | **-0.0080** | `[-0.0378, +0.0222]` | **PASS** ($-0.0080 \ge -0.0150$) |

- **Non-Degradation Verdict**: **`PASSED`**. In-domain fine-tuning on RAGTune software documentation did not cause catastrophic forgetting on scientific prose. Recall@10 slightly improved ($+0.57\%$).

---

## 4. Hardware Profiling & Latency Gate

Measured on dedicated **NVIDIA GeForce RTX 5050 Laptop GPU** (8,150.6 MiB VRAM):

| Pipeline Stage | P50 Latency | P95 Latency | P99 Latency | Peak VRAM Allocated | Peak VRAM Reserved |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Stage-1 E5C (BM25 + Dense RRF)** | **35.0 ms** | **47.0 ms** | **52.0 ms** | ~1,280 MiB | ~1,450 MiB |
| **Stage-2 E7 Reranker Only** | 322.1 ms | 346.1 ms | 366.5 ms | 1,320.3 MiB | 1,440.0 MiB |
| **Total End-to-End Pipeline** | **369.1 ms** | **402.3 ms** | **418.5 ms** | ~1,320 MiB | ~1,440.0 MiB |

- **Latency Analysis**: Adding the E7 cross-encoder increases P50 latency from 35.0 ms to 369.1 ms ($10.5\times$ increase). Because the aggregate retrieval metrics ($\Delta \text{NDCG@10} = -0.0012$, $\Delta \text{Recall@10} = -0.0143$) show no overall benefit over Stage-1 E5C, this latency penalty cannot be justified for production default serving.

---

## 5. Domain & Typology Breakdown

| Slice | Metric | Stage-1 E5C | E7C Reranker | Generic E6C |
| :--- | :--- | :---: | :---: | :---: |
| **PostgreSQL** ($N=35$) | NDCG@10 / Recall@10 | 0.7061 / 0.8571 | 0.7010 / 0.8429 | 0.6974 / 0.8429 |
| **PyTorch** ($N=35$) | NDCG@10 / Recall@10 | 0.8037 / 0.8857 | **0.8046** / **0.8857** | 0.7854 / 0.8286 |
| **Kubernetes** ($N=35$) | NDCG@10 / Recall@10 | 0.6409 / 0.7714 | 0.6425 / 0.7571 | 0.6277 / 0.7429 |
| **FastAPI** ($N=35$) | NDCG@10 / Recall@10 | 0.5946 / 0.8429 | 0.5923 / 0.8143 | 0.5996 / 0.8000 |
| **Comparative** ($N=60$) | NDCG@10 / Recall@10 | 0.7291 / 0.8833 | 0.7264 / 0.8667 | 0.7226 / 0.8667 |
| **Direct Lookup** ($N=40$) | NDCG@10 / Recall@10 | 0.6720 / 0.8750 | **0.6751** / **0.8750** | 0.6624 / 0.8500 |
| **Troubleshooting** ($N=40$) | NDCG@10 / Recall@10 | 0.6364 / 0.7375 | 0.6331 / 0.7125 | 0.6249 / 0.6625 |

---

## 6. Promotion Gate Summary & Next Steps

```
================================================================================
E7 PROVISIONAL PROMOTION GATE VERDICT
================================================================================
[FAIL] Predeclared Statistical Gate vs E5C:
       - Delta NDCG@10: -0.0012 (95% BCa CI: [-0.0423, +0.0375], lower <= 0)
       - Delta Recall@10: -0.0143 (Target: >= +0.0250)
[PASS] Controlled Domain Repair vs Generic E6C:
       - Delta NDCG@10: +0.0076 | Delta Recall@10: +0.0214
       - Top-10 failures cut from 9 to 4 (5 wins, 0 losses)
[PASS] OOD SciFact Non-Degradation:
       - Delta NDCG@10: -0.0080 >= -0.0150
[FAIL] Production Latency & Serving Efficiency:
       - End-to-end P50 latency 369.1 ms vs Stage-1 35.0 ms
--------------------------------------------------------------------------------
FINAL DECISION:
1. RETAIN E5C (BM25 + Matched-Easy Dense RRF k=60) as the PREFERRED DEVELOPMENT
   CHAMPION for Stage-1.
2. REJECT E7 as the default Stage-2 pipeline stage.
3. PRESERVE E7 checkpoint as an audited specialized cross-encoder artifact.
================================================================================
```

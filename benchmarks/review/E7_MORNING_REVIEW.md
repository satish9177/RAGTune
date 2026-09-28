# RAGTune E7 Experiment: Complete Autonomous Implementation Review

**Review Date**: 2026-09-29  
**Review Target**: Satish (Human Reviewer & Benchmark Owner)  
**Execution Mode**: `PROVISIONAL_AI_FILTERED_PENDING_HUMAN_REVIEW`  
**Pipeline Champion**: `E5C` (`BM25 + E4C Matched-Easy Dense RRF k=60`)  
**Evaluated Candidate**: `E7C-Provisional` (`BAAI/bge-reranker-base` domain fine-tuned cross-encoder)  
**Primary Recommendation**: **`RETAIN_E5C_AS_DEVELOPMENT_STAGE1_DEFAULT`** (Do NOT promote E7 as default Stage-2)

---

## 1. Executive Summary: Autonomous Execution Complete

All autonomous engineering, filtering, training, evaluation, statistical analysis, failure transition tracing, OOD validation, and documentation steps have been completed tonight without blocking on intermediate approvals:

1. **Benchmark v0 Freeze Protected**: Strictly `CANONICAL_FROZEN`. `frozen_test` was **NEVER** touched or loaded.
2. **Untouched OOD Final Datasets Protected**: `mteb/fiqa` and `BRIGHT` remain 100% untouched and uninspected.
3. **No Simulated Approvals**: Human audit fields in all audit documents remain strictly blank.
4. **Conservative Query Exclusions**: All 11 queries flagged in `E7_QUERY_POSITIVE_AUDIT.json` were strictly excluded from provisional training data.
5. **Multi-Signal Semantic Shields Enforced**: Reclassified all candidates; quarantined same-doc leaks, comparative partial answers, entity action overlaps, and diagnostic resolutions.
6. **Provisional Dataset Built**: 289 high-hardness training records across 122 unique training queries (well exceeding the $\ge 75$ threshold).
7. **E7 Model Trained**: Single predeclared run on `BAAI/bge-reranker-base` (3 epochs, FP16 AMP, lr=2e-5, AdamW) on RTX 5050 GPU in 24.30s. Checkpoint saved to `data/models/e7_bge_reranker_provisional_v0`.
8. **Development Evaluation Completed**: Reranked E5C Top-20 candidates for all 140 Benchmark v0 queries.
9. **Paired 10,000 BCa Bootstrap & McNemar Tests Executed**: Tested vs Stage-1 E5C and vs Generic E6C.
10. **OOD SciFact Evaluated**: Passed predeclared non-degradation gate ($\Delta \text{NDCG@10} = -0.0080 \ge -0.0150$).
11. **Failure Transitions & Latency Traced**: Full query-level trace and GPU latency profiling recorded.

---

## 2. Core Empirical Findings & Strategic Decision

### The Key Scientific Result
| Pipeline Configuration | NDCG@10 | Recall@10 | MRR@10 | HitRate@10 | Top-10 Failures | P50 Latency | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Stage-1 E5C Hybrid (Development Default)** | **0.6863** | **0.8393** | **0.7235** | **0.9786** | **3 queries** | **35.0 ms** | **CHAMPION** |
| **Generic E6C Cross-Encoder (Top-20)** | 0.6775 | 0.8036 | 0.7164 | 0.9357 | 9 queries | 357.1 ms | REJECTED |
| **E7 Domain Reranker (Top-20)** | 0.6851 | 0.8250 | 0.7206 | 0.9714 | 4 queries | 369.1 ms | **REJECTED AS DEFAULT** |

### What Domain Fine-Tuning Succeeded At:
- **Repaired Generic E6's Failures**: Cut top-10 failures from 9 down to 4.
- **Recovered 5 Demoted Queries**: Successfully restored `v0_pt_003`, `v0_pt_034`, `v0_k8s_035`, `v0_fa_030`, and `v0_fa_033` into the Top-10 with **zero regressions** compared to generic E6.
- **Controlled Comparison vs E6C**: $\Delta \text{NDCG@10} = +0.0076$, $\Delta \text{Recall@10} = +0.0214$, McNemar $p = 0.0736$ (5 wins, 0 losses).

### Why E7 Must NOT Be Promoted Over Stage-1 E5C:
- **Failed Predeclared Statistical Gate**:
  - $\Delta \text{NDCG@10} = -0.0012$ (95% BCa CI `[-0.0423, +0.0375]`; lower bound $\le 0$).
  - $\Delta \text{Recall@10} = -0.0143$ (target was $\ge +0.0250$).
- **Top-10 Failures**: 4 queries vs 3 in Stage-1 E5C. E7 recovered 2 queries (`v0_pt_003`, `v0_k8s_001`), but regressed 3 queries (`v0_pg_004`, `v0_k8s_028`, `v0_fa_015`).
- **Prohibitive Latency Penalty**:
  - Stage-1 E5C serves in **35.0 ms** P50 (47.0 ms P95).
  - Cross-encoder reranking adds **322.1 ms** (total pipeline **369.1 ms** P50, **402.3 ms** P95).
  - Incurring a $10.5\times$ latency penalty for neutral-to-slightly-negative aggregate accuracy is strictly unacceptable for production serving.

---

## 3. Top-10 Failure Reconciliation Ledger

| Query ID | Domain | Query Typology | Stage-1 Rank | E7 Rank | Failure Mechanism |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **`v0_k8s_032`** | Kubernetes | troubleshooting | None | None | **Unrecoverable Stage-1 Miss**: Absent from candidate pool at depth 20 & 50. |
| **`v0_pg_004`** | PostgreSQL | direct_lookup | 1 | 13 | **In-Pool Demotion**: Cross-encoder scored adjacent doc section higher. |
| **`v0_k8s_028`** | Kubernetes | comparative | 4 | 12 | **In-Pool Demotion**: Preemption flag subtlety demoted below generic controller text. |
| **`v0_fa_015`** | FastAPI | direct_lookup | 10 | 20 | **In-Pool Demotion**: Dependency scope section demoted below middleware guide. |

---

## 4. Pending Human Audits for Morning Review

Two structured audit files await Satish's explicit review:

### A. Query-Positive Audit (11 Queries)
- **Path**: [`data/training/E7_QUERY_POSITIVE_AUDIT.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_QUERY_POSITIVE_AUDIT.md) & [`.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_QUERY_POSITIVE_AUDIT.json)
- **Contents**: 4 PostgreSQL queries with `REL_16_STABLE` git heading artifacts, 7 PyTorch queries with very low lexical overlap.
- **Current Status**: All 11 queries were excluded from the provisional run.
- **Action Required**: Satish marks `VALID`, `REVISE`, or `REJECT`.

### B. Regenerated Negative Verification Audit V2 (40 Items)
- **Path**: [`data/training/E7_NEGATIVE_AUDIT_40_V2.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40_V2.md) & [`.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40_V2.json)
- **Contents**: Stratified sample of 40 hard candidates (10 PostgreSQL, 10 PyTorch, 10 Kubernetes, 10 FastAPI).
- **Predeclared Acceptance Gate**:
  - Zero confirmed `FALSE_NEGATIVE`
  - At most 2 `AMBIGUOUS`
  - All `TRUE_NEGATIVE` judged at least `MODERATE_CONFUSER`
- **Action Required**: Satish reviews classifications.

---

## 5. Summary of Persisted Artifacts

| Artifact | Path | Description |
| :--- | :--- | :--- |
| **Provisional Exclusions** | [`data/training/E7_PROVISIONAL_QUERY_EXCLUSIONS.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_PROVISIONAL_QUERY_EXCLUSIONS.json) | 11 excluded queries |
| **Provisional Negative Ledger** | [`data/training/e7_provisional_negative_ledger.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_provisional_negative_ledger.jsonl) | 652 candidates classified |
| **Provisional Training Data** | [`data/training/e7_reranker_train_provisional_v1.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_reranker_train_provisional_v1.jsonl) | 289 training records (122 queries) |
| **Dataset Disposition** | [`data/training/e7_provisional_dataset_disposition.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_provisional_dataset_disposition.json) | Filtering breakdown |
| **Model Checkpoint** | `data/models/e7_bge_reranker_provisional_v0` | Trained cross-encoder model & tokenizer |
| **Training Manifest** | [`benchmarks/experiments/e7_domain_reranker_provisional_manifest.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e7_domain_reranker_provisional_manifest.json) | GPU telemetry, losses, SHA-256 |
| **Prediction Traces** | [`benchmarks/experiments/e7c_provisional_predictions.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e7c_provisional_predictions.jsonl) | 140 query predictions |
| **Evaluation Metrics** | [`benchmarks/experiments/e7c_provisional_metrics.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e7c_provisional_metrics.json) | Full metrics & bootstrap results |
| **Evaluation Manifest** | [`benchmarks/experiments/e7c_provisional_manifest.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e7c_provisional_manifest.json) | Evaluation metadata |
| **Failure Transition Trace** | [`benchmarks/experiments/e7c_failure_transition_analysis.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e7c_failure_transition_analysis.json) | Transition and demotion ledger |
| **SciFact OOD Metrics** | [`benchmarks/experiments/ood_scifact_e7_metrics.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/ood_scifact_e7_metrics.json) | SciFact non-degradation results |
| **SciFact OOD Manifest** | [`benchmarks/experiments/ood_scifact_e7_manifest.json`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/ood_scifact_e7_manifest.json) | SciFact run metadata |
| **Promotion Gate Report** | [`benchmarks/canonical/E7_PROVISIONAL_PROMOTION_GATE.md`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/canonical/E7_PROVISIONAL_PROMOTION_GATE.md) | Formal gate evaluation |

---

## 6. Strategic Architecture Decision for Satish

```
================================================================================
RAGTUNE ARCHITECTURAL DECISION MATRIX
================================================================================
Option A (RECOMMENDED):
- Retain E5C (BM25 + Matched-Easy Dense RRF k=60) as the SINGLE-STAGE PRODUCTION PIPELINE.
- Rationale: High accuracy (0.6863 NDCG@10, 0.8393 Recall@10, 97.86% HitRate@10),
  ultra-low latency (35 ms P50), only 3 failures, zero cross-encoder complexity.
- Preserve E7 as a specialized fallback for high-confuser offline scenarios.

Option B:
- After Satish reviews the audits, retrain E7 on the human-adjudicated dataset
  using listwise LambdaLoss or cross-entropy with hard margin.
- Caveat: The cross-encoder latency envelope will remain ~320-350 ms.
================================================================================
```

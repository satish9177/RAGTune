# Historical E4 Hard-Negative Audit: AI Review & Diagnostic Report

> [!IMPORTANT]
> **PROVENANCE & STATUS**: This document records **AI-assisted recommendations only**.
> It does **NOT** constitute human review or approval by Satish.
> Human approval remains `PENDING_SATISH_HUMAN_REVIEW`.
> The historical audit document `data/training/HARD_NEGATIVE_AUDIT_40.md` is preserved unchanged as historical evidence.

## 1. Summary of Classifications (40 Triples)

- **Total Sample Size**: 40 triples (10 per ecosystem: PostgreSQL, PyTorch, Kubernetes, FastAPI)
- **FALSE_NEGATIVE**: 4 items (10.0%)
- **AMBIGUOUS_UNSAFE_NEGATIVE**: 6 items (15.0%)
- **LIKELY_TRUE_NEGATIVE**: 30 items (75.0%)

### Multi-Dimensional Breakdown

| Dimension | Category | Count | Percentage |
|---|---|---:|---:|
| **Negative Semantic Status** | `FALSE_NEGATIVE` | 4 | 10.0% |
| **Negative Semantic Status** | `AMBIGUOUS_UNSAFE_NEGATIVE` | 6 | 15.0% |
| **Negative Semantic Status** | `LIKELY_TRUE_NEGATIVE` | 30 | 75.0% |
| **Query Quality** | `SYNTHETIC_TEMPLATED` | 24 | 60.0% |
| **Query Quality** | `WELL_FORMED` | 7 | 17.5% |
| **Query Quality** | `HEADING_ARTIFACT` | 8 | 20.0% |
| **Query Quality** | `QUERY_POSITIVE_MAPPING_DEFECT` | 1 | 2.5% |
| **Positive Support** | `DIRECT_SUPPORT` | 37 | 92.5% |
| **Positive Support** | `WEAK_SUPPORT` | 2 | 5.0% |
| **Positive Support** | `MISALIGNED_MAPPING` | 1 | 2.5% |
| **Negative Difficulty** | `MODERATE_CONFUSER` | 21 | 52.5% |
| **Negative Difficulty** | `WEAK_CONFUSER` | 10 | 25.0% |
| **Negative Difficulty** | `HARD_CONFUSER` | 9 | 22.5% |

## 2. Identified High-Severity Defects

### A. `train_fa_0377` — `QUERY_POSITIVE_MAPPING_DEFECT` & `FALSE_NEGATIVE`
- **Query**: `How to use and configure yield in fastapi?`
- **Assigned Positive Chunk**: `b677a28e08d6` (`tutorial/middleware.md`)
- **Assigned Negative Chunk**: `90ba95ef41da` (`tutorial/dependencies/dependencies-with-yield.md`)
- **Diagnosis**: The positive chunk explains `@app.middleware('http')` and never mentions `yield`. The negative candidate from `dependencies-with-yield.md` contains the actual code pattern (`async def get_db(): try: yield db finally: db.close()`). Thus the model was asked to treat the true answer as a negative.

### B. `train_py_0226` — `SAME_FILE_ANSWER_BEARING` & `FALSE_NEGATIVE`
- **Query**: `What is the configuration and purpose of PyTorch 20 Troubleshooting  Minifying TorchInductor Errors in pytorch?`
- **Positive Chunk**: `torch.compiler_troubleshooting.rst` (running the minifier)
- **Negative Chunk**: `torch.compiler_troubleshooting.rst` (isolating `backend="aot_eager"`)
- **Diagnosis**: Both chunks provide legitimate, directly relevant troubleshooting advice from the same section.

### C. `train_ku_0252` — `CANONICAL_DOCUMENT_FALSE_NEGATIVE`
- **Query**: `What is the configuration and purpose of Resource metrics pipeline in kubernetes?`
- **Positive Chunk**: `tasks/debug/debug-cluster/resource-usage-monitoring.md`
- **Negative Chunk**: `tasks/debug/debug-cluster/resource-metrics-pipeline.md`
- **Diagnosis**: The candidate negative is the canonical document for the resource metrics pipeline itself.

### D. `train_fa_0466` — `SAME_FILE_ANSWER_BEARING` & `FALSE_NEGATIVE`
- **Query**: `How to use and configure yield in fastapi?`
- **Positive Chunk**: `tutorial/dependencies/dependencies-with-yield.md`
- **Negative Chunk**: `tutorial/dependencies/dependencies-with-yield.md`
- **Diagnosis**: Both chunks are from the same chapter explaining yield dependencies in FastAPI.

## 3. Ambiguous / Unsafe Negatives (6 Items)

| Query ID | Ecosystem | Query Excerpt | Reason for Ambiguity |
|---|---|---|---|
| `train_fa_0489` | fastapi | What is the difference and interaction betwee... | Positive discusses Response headers and return types. Negative discusses additional response declarations and combining response schemas. Closely related API response semantics. |
| `train_ku_0340` | kubernetes | What is the difference and interaction betwee... | Positive defines preemptionPolicy. Negative defines the fundamental concept of preemption and scheduling queues in Kubernetes. High semantic overlap on preemption mechanics. |
| `train_py_0166` | pytorch | What is the configuration and purpose of CUDA... | Query asks for CUDA graphs non-constraints. Negative discusses live tensor limitations in CUDA graph trees. Both discuss constraints/limitations of CUDA graphs in PyTorch. |
| `train_py_0176` | pytorch | How to use and configure autograd_tutorial in... | Query asks about autograd_tutorial. Positive discusses modules, while negative discusses extending autograd with custom Functions. Negative is semantically adjacent and could confuse training. |
| `train_py_0189` | pytorch | What is the difference and interaction betwee... | Query asks about float32 and uint8 tensors. Negative covers IEEE 754 floating point arithmetic and precision, which directly addresses the precision aspects of float32. |
| `train_py_0216` | pytorch | What is the difference and interaction betwee... | Positive and negative are from the same document (torch.compiler_guards_overview.rst). Positive discusses VariableBuilder and make_guards, negative discusses guard.create and check_fn. Inter-dependent compilation internals make this an unsafe negative. |

## 4. Item-by-Item Review Ledger

| # | Query ID | Eco | Semantic Status | Quality | Support | Difficulty | Teacher Marg |
|---:|---|---|---|---|---|---|---:|
| 1 | `train_po_0002` | postgresql | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.71 |
| 2 | `train_po_0018` | postgresql | `LIKELY_TRUE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.87 |
| 3 | `train_po_0032` | postgresql | `LIKELY_TRUE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.87 |
| 4 | `train_po_0045` | postgresql | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.78 |
| 5 | `train_po_0056` | postgresql | `LIKELY_TRUE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.59 |
| 6 | `train_po_0069` | postgresql | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.97 |
| 7 | `train_po_0080` | postgresql | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.61 |
| 8 | `train_po_0089` | postgresql | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.32 |
| 9 | `train_po_0100` | postgresql | `LIKELY_TRUE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.95 |
| 10 | `train_po_0111` | postgresql | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.94 |
| 11 | `train_py_0126` | pytorch | `LIKELY_TRUE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.52 |
| 12 | `train_py_0140` | pytorch | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.84 |
| 13 | `train_py_0152` | pytorch | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.83 |
| 14 | `train_py_0166` | pytorch | `AMBIGUOUS_UNSAFE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.82 |
| 15 | `train_py_0176` | pytorch | `AMBIGUOUS_UNSAFE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.61 |
| 16 | `train_py_0189` | pytorch | `AMBIGUOUS_UNSAFE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.84 |
| 17 | `train_py_0201` | pytorch | `LIKELY_TRUE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.96 |
| 18 | `train_py_0216` | pytorch | `AMBIGUOUS_UNSAFE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.41 |
| 19 | `train_py_0226` | pytorch | `FALSE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.57 |
| 20 | `train_py_0237` | pytorch | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.86 |
| 21 | `train_ku_0252` | kubernetes | `FALSE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.98 |
| 22 | `train_ku_0265` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.35 |
| 23 | `train_ku_0276` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.78 |
| 24 | `train_ku_0289` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.64 |
| 25 | `train_ku_0304` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.69 |
| 26 | `train_ku_0314` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.97 |
| 27 | `train_ku_0326` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.67 |
| 28 | `train_ku_0340` | kubernetes | `AMBIGUOUS_UNSAFE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.69 |
| 29 | `train_ku_0353` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `WELL_FORMED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.53 |
| 30 | `train_ku_0364` | kubernetes | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `WEAK_SUPPORT` | `MODERATE_CONFUSER` | 0.36 |
| 31 | `train_fa_0377` | fastapi | `FALSE_NEGATIVE` | `QUERY_POSITIVE_MAPPING_DEFECT` | `MISALIGNED_MAPPING` | `MODERATE_CONFUSER` | 0.59 |
| 32 | `train_fa_0387` | fastapi | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.59 |
| 33 | `train_fa_0397` | fastapi | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.86 |
| 34 | `train_fa_0414` | fastapi | `LIKELY_TRUE_NEGATIVE` | `HEADING_ARTIFACT` | `WEAK_SUPPORT` | `WEAK_CONFUSER` | 0.30 |
| 35 | `train_fa_0427` | fastapi | `LIKELY_TRUE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.95 |
| 36 | `train_fa_0440` | fastapi | `LIKELY_TRUE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.89 |
| 37 | `train_fa_0452` | fastapi | `LIKELY_TRUE_NEGATIVE` | `HEADING_ARTIFACT` | `DIRECT_SUPPORT` | `HARD_CONFUSER` | 0.90 |
| 38 | `train_fa_0466` | fastapi | `FALSE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.64 |
| 39 | `train_fa_0476` | fastapi | `LIKELY_TRUE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `WEAK_CONFUSER` | 0.59 |
| 40 | `train_fa_0489` | fastapi | `AMBIGUOUS_UNSAFE_NEGATIVE` | `SYNTHETIC_TEMPLATED` | `DIRECT_SUPPORT` | `MODERATE_CONFUSER` | 0.75 |

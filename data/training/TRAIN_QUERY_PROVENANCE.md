# Training Query Universes: Provenance, Definitions, and Overlap Reconciliation

> [!IMPORTANT]
> **CANONICAL PARTITION DISCIPLINE**:
> Across all three query universes analyzed below, **100.0% of queries, positive chunks, and negative candidates belong strictly to the canonical `train` partition** (6,414 chunks).
> Exactly **zero** chunks or queries originate from or touch `validation` (1,575 chunks) or `frozen_test` (3,656 chunks).

---

## 1. Population Definitions & Provenance

During the progression from baseline retriever training (E0–E3) to hard-negative mining (E4) and candidate accounting, three distinct query populations were generated:

### Population 1: Canonical Retriever Training Set (`N = 188`)
- **Artifact**: `data/training/retriever_train_v0.jsonl`
- **Purpose**: The primary, hand-curated and synthetically augmented training set utilized for training Stage-1 dense retrievers (`E3-BGE-v0`, `E4-BGE-HardNeg-v0`, and `E4C-BGE-MatchedEasy-v0`).
- **Composition**: Exactly 188 distinct queries, each mapped to a single ground-truth positive chunk in the `train` partition.

### Population 2: Expanded Mining Candidate Pool (`N = 501`)
- **Artifact**: `data/training/hard_negative_audit_v0.jsonl`
- **Purpose**: An expanded pool of candidate queries generated across all 4 ecosystems (~125 queries per ecosystem) to serve as a broad query pool for discovering challenging hard-negative confusers across the corpus.
- **Composition**: Exactly 501 distinct queries, each mapped to a single ground-truth positive chunk in the `train` partition.

### Population 3: Surviving Negative-Mining Query Set (`N = 375`)
- **Artifact**: Represented within `data/training/hard_negatives_v1.jsonl` (739 triples)
- **Purpose**: The subset of queries from Population 2 that successfully yielded at least one accepted hard negative passing all 4 false-negative protection layers (known positive exclusion, document/section proximity, lexical overlap, and teacher cross-encoder margin $\ge 0.25$).
- **Composition**: Exactly 375 distinct queries across 739 training triples (up to 2 verified negatives per query).

---

## 2. Ecosystem & Typology Distributions

| Ecosystem | Pop 1: Canonical Train (`retriever_train_v0`) | Pop 2: Expanded Pool (`hard_negative_audit_v0`) | Pop 3: Accepted HN Pool (`hard_negatives_v1`) | Total Triples in Pop 3 |
|---|---:|---:|---:|---:|
| **PyTorch** | 59 (31.4%) | 125 (25.0%) | 108 (28.8%) | 213 (28.8%) |
| **PostgreSQL** | 45 (23.9%) | 126 (25.1%) | 89 (23.7%) | 175 (23.7%) |
| **Kubernetes** | 43 (22.9%) | 125 (25.0%) | 84 (22.4%) | 165 (22.3%) |
| **FastAPI** | 41 (21.8%) | 125 (25.0%) | 94 (25.1%) | 186 (25.2%) |
| **Total** | **188** | **501** | **375** | **739** |

---

## 3. Exact Mathematical Overlap Matrix

The mathematical relationship between the three populations is a strict nested lattice:

$$\text{Pop 1 (188)} \subset \text{Pop 2 (501)}$$
$$\text{Pop 3 (375)} \subset \text{Pop 2 (501)}$$

```
+-------------------------------------------------------------+
| Population 2: Expanded Pool (501)                           |
|                                                             |
|   +-----------------------+     +-----------------------+   |
|   | Population 1 (188)    |     | Population 3 (375)    |   |
|   |                       |     |                       |   |
|   |      15 queries       | 173 |      202 queries      |   |
|   |    (no accepted HN)   |  ∩  |    (not in Pop 1)     |   |
|   |                       |     |                       |   |
|   +-----------------------+     +-----------------------+   |
|                                                             |
|                 111 queries in neither Pop 1 nor 3          |
+-------------------------------------------------------------+
```

### Pairwise Intersections

1. **Pop 1 $\cap$ Pop 2 = 188**:
   - Every single query in Population 1 is contained within Population 2 ($188 / 188 = 100.0\%$).
   - Queries unique to Pop 1 relative to Pop 2: **0**.

2. **Pop 3 $\cap$ Pop 2 = 375**:
   - Every single query in Population 3 is contained within Population 2 ($375 / 375 = 100.0\%$).
   - Queries unique to Pop 3 relative to Pop 2: **0**.

3. **Pop 1 $\cap$ Pop 3 = 173**:
   - Exactly 173 queries from the canonical 188-query set yielded accepted hard negatives in the 739-triple pool.
   - Exactly **15 queries** in Population 1 produced **no** accepted hard negatives in `hard_negatives_v1.jsonl`.
   - Exactly **202 queries** in Population 3 originated from the expanded pool (Pop 2) but were not part of Pop 1.

4. **Remainder of Pop 2**:
   - Queries in Pop 2 that are in neither Pop 1 nor Pop 3: $501 - 375 - 15 = \mathbf{111}$.

---

## 4. Disposition Analysis of the 15 Pop-1 Queries Without Accepted Negatives

The 15 queries in Population 1 that did not yield an accepted negative in `hard_negatives_v1.jsonl` are:
`train_fa_0401`, `train_fa_0416`, `train_fa_0449`, `train_ku_0266`, `train_ku_0284`, `train_ku_0331`, `train_ku_0343`, `train_ku_0347`, `train_ku_0366`, `train_po_0006`, `train_po_0054`, `train_po_0073`, `train_py_0190`, `train_py_0214`, `train_py_0242`.

According to `hard_negative_candidate_ledger_v1.jsonl`, all 337 candidates mined for these 15 queries were legitimately filtered by false-negative protection rules:
- **`QUARANTINED_AMBIGUOUS_MARGIN`** (142 candidates): Teacher cross-encoder margin was positive but below the strict 0.25 discrimination threshold.
- **`REJECTED_LOW_POSITIVE_TEACHER_SCORE`** (88 candidates): Teacher score on the positive chunk was $< 0.30$, failing confidence verification.
- **`QUARANTINED_HIGH_TEACHER_SCORE`** (46 candidates): Negative candidate scored $\ge 0.60$, quarantined as a likely unannotated true positive.
- **`QUARANTINED_TEACHER_INVERSION`** (23 candidates): Candidate scored higher than or equal to positive ($\Delta \le 0$).
- **`QUARANTINED_SAME_DOCUMENT_SUBTOPIC`** (23 candidates): Candidate was from the same file with high lexical overlap or matching breadcrumb.
- **`KNOWN_POSITIVE_EXCLUSION`** (13 candidates): Candidate matched the positive chunk ID directly.
- **`QUARANTINED_HIGH_LEXICAL_OVERLAP`** (2 candidates): Candidate exhibited $> 0.40$ Jaccard overlap with positive text.

This confirms that the absence of accepted negatives for these 15 queries was the intended behavior of the multi-layer false-negative shield, rather than an indexing omission.

---

## 5. Architectural Alignment for E7

For upcoming domain reranker training (E7):
- **Canonical Primary Query Set**: Locked strictly to **Population 1 (`N = 188`)**.
- **Mining Strategy**: Re-mine candidates for all 188 primary queries using the preferred development retriever pipeline (`E5C = BM25 + E4C dense` with RRF $k=60$) over all 6,414 `train` chunks.
- **Negative Protection**: Retain all 4 protection layers and generate an E7-specific candidate ledger and human audit sample.

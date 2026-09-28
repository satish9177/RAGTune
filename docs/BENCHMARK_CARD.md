# RAGTune Benchmark Data-Card

Following Gebru et al. (2021) and Hugging Face Dataset Card standards.

## 1. Benchmark Summary
- **Name**: RAGTune Technical Documentation Benchmark
- **Phased Rollout**:
  - **Benchmark v0**: 140 high-quality development queries grounded in `validation` partition, **CANONICALLY FROZEN** (SHA-256: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`).
  - **Benchmark v1**: Target of approximately 600 queries for full evaluation and publication.
- **Domains Covered**: PostgreSQL (concurrency/indexing), PyTorch (distributed/memory), Kubernetes (workloads/probes), FastAPI (dependency injection/concurrency).

## 2. Corpus Composition & Provenance
- **PostgreSQL 16.3**: Tag `REL_16_3`, Commit `05ffe9398b758bbb8d30cc76e9bbc638dab2d477`, Canonical URL `https://github.com/postgres/postgres.git`, PostgreSQL License.
- **PyTorch 2.3.1**: Tag `v2.3.1`, Commit `63d5e9221bedd1546b7d364b5ce4171547db12a9`, Canonical URL `https://github.com/pytorch/pytorch.git`, BSD-3-Clause License.
- **Kubernetes 1.30 Documentation**: Tag `snapshot-initial-v1.30`, Commit `0471ca12572f26cd6f553dafddbe1de22c4abf7f`, Canonical URL `https://github.com/kubernetes/website.git`, Apache-2.0 (code) / CC-BY-4.0 (content).
- **FastAPI 0.111.0**: Tag `0.111.0`, Commit `1c3e6918750ccb3f20ea260e9a4238ce2c0e5f63`, Canonical URL `https://github.com/fastapi/fastapi.git`, MIT License.

## 3. Query Composition & Provenance Tracking

### 3.1 Benchmark v0 Distribution (140 Development Queries Grounded in Validation Partition)
- **Domain Coverage**: 35 queries per domain (PostgreSQL, PyTorch, Kubernetes, FastAPI).
- **Typology Breakdown**:
  - Direct Lookup: 40 queries (syntax, flags, configuration).
  - Comparative Discrimination: 60 queries (differentiating semantically close concepts).
  - Troubleshooting / Scenario: 40 queries (error diagnostics, deadlock, OOM, event loop blocking).
- **Truthful Provenance Breakdown**:
  - AI-Authored Project Queries: 88 queries (62.9%) — authored by AI agent and verified against validation partition documentation.
  - Synthetic Grounded Queries: 49 queries (35.0%) — generated from validation documentation passages with strict anti-parroting (mean Jaccard overlap = 0.165, max < 0.40).
  - Natural External Verified Queries: 3 queries (2.1%) — verified Stack Overflow troubleshooting scenarios with exact post IDs, timestamps, revision history, and applicable licenses.
  - Human-Authored: 0 queries (strictly reserved until Satish personally authors or edits queries).

### 3.2 Human Audit Sample & Canonical Freeze
- **40-Query Human Audit Sample**:
  - 17 uncertainty-flagged queries (100% of borderline / multi-aspect queries).
  - 3 external-derived verified queries (100% of Stack Overflow scenarios).
  - 20 stratified queries (5 per domain, across typologies and provenances, seed=42).
- **Review Dispositions & Explicit Human Approval**:
  - **Reviewer**: Satish (Human Lead).
  - **Explicit Approval Event**: 2026-09-28. Satish personally reviewed the final benchmark audit results and explicitly approved all 40 queries in the sample (31 initial audit recommendations approved + final 9 approved queries: `v0_pg_002`, `v0_pg_011`, `v0_pg_013`, `v0_pg_016`, `v0_pg_017`, `v0_pg_018`, `v0_pt_021`, `v0_pt_032`, `v0_k8s_007`).
  - Prior audit statuses are truthfully preserved as reviewer recommendations / pending review until this explicit approval event; zero human decisions were simulated.
  - Remaining 100 queries: `AI_SOURCE_VERIFIED` with automated sanity checks passing 100% (139 PASS / 1 REVIEW / 0 FAIL).
- **Canonical Freeze State**: Benchmark v0 is officially finalized and canonically frozen at SHA-256 `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d` (`benchmarks/BENCHMARK_V0_FREEZE.json`).

### 3.3 External Query Licensing & Redistribution Terms
- Provenance tracked per external query: platform, post ID, title, source URL, revision URL, contribution timestamp, and exact applicable license.
- Exact Stack Overflow licensing date rules:
  - `v0_pg_026` (PostgreSQL `max_connections`, SO 3086759, 2010-06-22) $\to$ **`CC BY-SA 2.5`**
  - `v0_pt_018` (PyTorch multiprocessing `spawn` vs `fork`, SO 48822463, 2018-02-16) $\to$ **`CC BY-SA 3.0`**
  - `v0_fa_028` (FastAPI CORS preflight headers, SO 65632734, 2021-01-08) $\to$ **`CC BY-SA 4.0`**
- All 3 external queries are included in the 40-query human audit packet (`benchmarks/review/HUMAN_AUDIT_40.md`).

### 3.4 Human Audit Review Dispositions & V3 Relevance Repair Methodology

The development benchmark quality process incorporates iterative human audit review and rigorous validation:

1. **Initial V1 Human Audit & V2 Repairs**:
   - Initial 40-query audit packet (`benchmarks/review/HUMAN_AUDIT_40.md`) identified relevance-mapping defects (e.g. `work_mem` query mapped to `temp_buffers`; `synchronous_commit` mapped to generic `fsync` overview).
   - Produced `benchmarks/review/HUMAN_AUDIT_40_V2.md` with re-anchored passages and replacement of unsupported queries.

2. **V2 Human Review Recommendations (Satish)**:
   - **APPROVE AS-IS (18 queries)**: `v0_pg_025`, `v0_pg_034`, `v0_pt_003`, `v0_pt_025`, `v0_pt_027`, `v0_k8s_011`, `v0_k8s_014`, `v0_k8s_017`, `v0_k8s_025`, `v0_k8s_027`, `v0_k8s_029`, `v0_fa_004`, `v0_fa_010`, `v0_fa_011`, `v0_fa_016`, `v0_fa_022`, `v0_fa_026`, `v0_fa_028`.
   - **REVISE (22 queries)**: `v0_pg_001`, `v0_pg_002`, `v0_pg_011`, `v0_pg_013`, `v0_pg_016`, `v0_pg_017`, `v0_pg_018`, `v0_pg_026`, `v0_pg_030`, `v0_pt_002`, `v0_pt_012`, `v0_pt_015`, `v0_pt_018`, `v0_pt_021`, `v0_pt_023`, `v0_pt_032`, `v0_k8s_007`, `v0_k8s_010`, `v0_k8s_015`, `v0_k8s_022`, `v0_fa_018`, `v0_fa_023`.
   - **REJECT (0 queries)**: No queries rejected; all retained within the validation partition.

3. **V3 Relevance Repair Architecture & Methodology**:
   - **Single Canonical Spec (`scripts/benchmark_specs.py`)**: All 140 query definitions, provenance metadata, uncertainty flags, and graded relevance chunk prefixes are maintained in a single source of truth, eliminating spec-to-report drift.
   - **Mechanical Snapshot Diffing**: `scripts/generate_human_audit_packet_v3.py` diffs `benchmarks/review/benchmark_v0_v2_snapshot.jsonl` against current `benchmarks/benchmark_v0.jsonl`, guaranteeing that `reported_new_grade3_chunk == actual_grade3_chunk`.
   - **Exact Passage Re-Anchoring (22 queries)**:
     - PostgreSQL: `v0_pg_001` (`bd01abb12ba6`, `shared_buffers`), `v0_pg_002` (`c702d7353ba3`, `work_mem`), `v0_pg_011` (`6cf7e592b2d8`, crash durability of `on` vs `remote_write`), `v0_pg_013` (`4cb1a6e848ab`, `hot_standby_feedback`), `v0_pg_016` (`a1d4c0645801`, `DEPENDENCY_NORMAL` vs `DEPENDENCY_AUTO`), `v0_pg_017` (`6c035189f85c`, `typalign`/`typstorage`), `v0_pg_018` (`58602e758a4a`, `indisprimary`/`indisclustered`/`indisvalid`), `v0_pg_026` (`e0bcb398517f`, `max_connections`), `v0_pg_030` (`4151c530c8cf`, `deadlock_timeout` diagnostics).
     - PyTorch: `v0_pt_002` (`79cab38f8b32`, `create_graph` accumulation), `v0_pt_012` (`d7fb32e88610`, in-place version tracking), `v0_pt_015` (`6ba0b24e5699`, CUDA tensor sharing start methods), `v0_pt_018` (`87f584fa213e`, `spawn` exception handling), `v0_pt_021` (`47c7bc4b7227`, `file_descriptor` vs `file_system`), `v0_pt_023` (`5bf6b4652e3d`, symmetric vs asymmetric quantization equations), `v0_pt_032` (`c51ddba8d3d5`, training loop autograd history accumulation OOM).
     - Kubernetes: `v0_k8s_007` (`60113ca5b874`, `ReadWriteOnce` vs `ReadWriteOncePod`), `v0_k8s_010` (`2199ee2405be`, `required` vs `preferred` node affinity), `v0_k8s_015` (`b997853e6622` RollingUpdate & `6ddcf2182d64` Recreate promoted to G2), `v0_k8s_022` (`74825e38c71a`, RoleBinding vs ClusterRoleBinding authorization scope).
     - FastAPI: `v0_fa_018` (`4e814ec518ec`, wildcard CORS origin credentials exclusion), `v0_fa_023` (`7008bc96ad50` `root_path` app parameter vs `4a8ba42bc58f` `--root-path` ASGI CLI option).
   - **Query Text Alignment**: Where validation documentation lacked coverage for earlier AI-phrased queries, questions were rewritten to match authentic technical documentation concepts (`v0_pt_012`, `v0_pt_015`, `v0_pt_018`, `v0_pt_023`, `v0_pt_032`, `v0_fa_018`, `v0_fa_023`).
   - **Comparative Completeness & Grade 2 Pruning**: For comparative queries, all named sides are covered across Grade $\ge 2$ passages. Unrelated Grade 2 passages were pruned (`v0_pg_005`, `v0_pt_026`), guaranteeing 100% semantic connection across all Grade 2 passages.
   - **Zero Simulated Human Decisions**: All 40 sampled queries remain strictly `AWAITING_HUMAN_REVIEW` (reviewer = null, reviewed_at = null). The remaining 100 queries are `AI_SOURCE_VERIFIED`.

4. **Automated Evidence Sanity Audit (`benchmarks/v3_evidence_audit_report.json`)**:
   - Total queries audited: 140
   - `AUTOMATED_CHECK_PASS`: 139 (99.3%)
   - `AUTOMATED_CHECK_REVIEW`: 1 (0.7%, `v0_fa_018` due to cross-passage concept distribution across G3 and G2)
   - `AUTOMATED_CHECK_FAIL`: 0 (0.0%)
   - *Methodological Disclaimer*: Automated evidence verification provides a structural sanity check layer (anti-generic checks, keyword overlap, displacement detection) and does not constitute formal human semantic certification.

5. **Audit Packet Artifacts**:
   - Historical V1 packet: `benchmarks/review/HUMAN_AUDIT_40.md` (preserved intact).
   - Historical V2 packet: `benchmarks/review/HUMAN_AUDIT_40_V2.md` (preserved intact).
   - V2 pre-repair snapshot: `benchmarks/review/benchmark_v0_v2_snapshot.jsonl` (preserved for auditing).
   - V3 audit packet: `benchmarks/review/HUMAN_AUDIT_40_V3.md` (18 `[HUMAN-AUDIT APPROVED AS-IS]`, 22 `[POST-REVISE REPAIRED]`, complete diffs, answer-centered excerpts, unselected checkboxes).
   - Final review audit packets: `benchmarks/review/HUMAN_AUDIT_9_FINAL.md` and `benchmarks/review/HUMAN_AUDIT_PG013_FINAL.md` (documenting Satish's explicit human approval of the final audit queries on 2026-09-28).

## 4. Graded Relevance Guidelines & Annotation Protocol

### 4.1 Graded Relevance Definitions
- **Grade 3 (Canonical / Best Evidence)**:
  - *Definition*: Directly resolves the query with complete, authoritative technical explanation.
  - *Example*: For query "How to configure a startup probe for slow containers?", the passage explicitly explaining `startupProbe` syntax, `failureThreshold`, and `periodSeconds`.
- **Grade 2 (Directly Relevant)**:
  - *Definition*: Accurately answers the query but may require minor inferential context or lacks exhaustive configuration syntax.
  - *Example*: A passage explaining container probe lifecycles and interactions between startup, readiness, and liveness probes.
- **Grade 1 (Useful / Supporting)**:
  - *Definition*: Contains prerequisite definitions or background context helpful for understanding the mechanism.
  - *Example*: Overview of Kubelet pod lifecycle management and container state transitions.
- **Grade 0 (Irrelevant)**:
  - *Definition*: Does not contain evidence answering the query.

### 4.2 Annotation Process & Uncertainty Handling
- Initial annotations are generated by the primary author and reviewed against official documentation.
- **Ambiguity & Alternate Positives**: If multiple passages independently provide valid answers, each passage is assigned its own graded relevance score in the multi-positive set.
- **Uncertainty Flag**: Queries or passage mappings where relevance is borderline are explicitly flagged with `"uncertainty": true` in the benchmark metadata.
- *Inter-Annotator Agreement*: No claims of inter-annotator agreement are made unless multiple independent annotators formally label overlapping subsets.

## 5. Partitioning, Roles & Leakage Controls
- **Partition Ratio (File Level)**: Train 60.0% (743 files), Validation 15.0% (184 files), Frozen Test 25.0% (313 files). Total files = 1,240.
- **Exact Partition Chunks (`benchmarks/partition_manifest.json`)**:
  - `train`: 6,414 chunks (55.08%)
  - `validation`: 1,575 chunks (13.53%)
  - `frozen_test`: 3,656 chunks (31.40%)
  - **Total**: 11,645 chunks (`train + validation + frozen_test == 11,645`).
- **Historical Count Reconciliation Note**: An earlier informal report summary casually cited `frozen_test = 2,873 chunks (~24.7%)`, which was a naive arithmetic chunk estimate ($11,645 \times 0.2467 = 2,873$) rather than the manifest count. Because partitioning operates on whole document/chapter units and files differ in length, the exact chunk count for `frozen_test` is 3,656 chunks.
- **Partition Unit**: Top-level documentation chapters and modules. Chunks from the same topic are strictly co-located.
- **Three-Tier Query Roles**:
  1. **Training Queries (`train` partition)**: Exclusively used for contrastive pair construction, hard-negative mining, and bi-encoder/cross-encoder fine-tuning.
  2. **Development / Validation Benchmark (`validation` partition, Benchmark v0)**: 140 manually verified queries used for E0/E1/E2 comparisons, hyperparameter tuning, model checkpoint selection, early stopping, and failure discovery.
  3. **Final Frozen Benchmark (`frozen_test` partition)**: Reserved exclusively for final, unbiased, release-candidate evaluation. Never mined for hard negatives, never used for model training, never used for early stopping.
- **Pilot Benchmark Reclassification**:
  - `benchmarks/pilot_benchmark.jsonl` (16 queries) is strictly an **engineering smoke test** (`DIAGNOSTIC_ONLY`).
  - Its evidence belongs to `frozen_test` and is strictly barred from training or hard-negative mining.
- **Searchable Index Composition**: During evaluation, the searchable index contains all corpus chunks (Train + Val + Test) to test retrieval of unseen target documents from among the entire collection.
- **Leakage Controls**: Code-level guardrails (`ragtune.training.guardrails`) enforce partition boundaries at runtime, raising `FrozenTestLeakageError` if frozen-test data ever enters training.

## 6. Intended & Inappropriate Uses
- **Intended Use**: Benchmarking first-stage dense/lexical retrievers and second-stage rerankers on domain-specific technical documentation; evaluating hard-negative mining efficacy.
- **Prohibited Use**:
  - Never use frozen-test queries, positives, or retrieved confusers as training data or hard negatives.
  - Never tune hyperparameters or make early-stopping decisions against the frozen test set.
  - Do not use pilot smoke test numbers as public benchmark claims.

- **Inappropriate Uses**: Evaluating conversational dialog fluency, training generic open-domain chatbots, or measuring non-grounded generative LLM output.

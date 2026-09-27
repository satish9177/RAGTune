# RAGTune: Dataset Design & Split Manifesto

## 1. Corpus Manifest

Upstream technical documentation is captured as frozen snapshots. Each snapshot is tracked in `benchmarks/manifest.json`.

| Ecosystem | Exact Version / Tag | Resolved Commit SHA | Canonical Source URL | License | Snapshot Hash (SHA-256) |
|:---|:---|:---|:---|:---|:---|
| **PostgreSQL** | `REL_16_3` | `05ffe9398b758bbb8d30cc76e9bbc638dab2d477` | `https://github.com/postgres/postgres.git` | PostgreSQL License | Measured upon archive creation |
| **PyTorch** | `v2.3.1` | `63d5e9221bedd1546b7d364b5ce4171547db12a9` | `https://github.com/pytorch/pytorch.git` | BSD-3-Clause | Measured upon archive creation |
| **Kubernetes**| `snapshot-initial-v1.30` | `0471ca12572f26cd6f553dafddbe1de22c4abf7f` | `https://github.com/kubernetes/website.git` | Apache-2.0 / CC-BY-4.0 | Measured upon archive creation |
| **FastAPI** | `0.111.0` | `1c3e6918750ccb3f20ea260e9a4238ce2c0e5f63` | `https://github.com/fastapi/fastapi.git` | MIT License | Measured upon archive creation |

*Note on Kubernetes*: The `kubernetes/website` repository does not use Kubernetes patch release tags (such as `v1.30.2`). Instead, documentation for version 1.30 is tagged via documentation release snapshots. The verified tag `snapshot-initial-v1.30` (commit `0471ca12572f26cd6f553dafddbe1de22c4abf7f`) is selected as the authoritative snapshot for Kubernetes 1.30 concepts and tasks.

## 2. Document Split vs. Retrieval Corpus Semantics

This distinction is mandatory and strictly enforced:

### The Source Partition (Splitting Phase)
- **Train Source Partition (60%)**: Documents allocated exclusively for generating training queries, positives, and candidate pools.
- **Validation Source Partition (15%)**: Documents used for hyperparameter calibration, temperature tuning, and early stopping.
- **Frozen Test Source Partition (25%)**: Documents reserved strictly for the benchmark evaluation queries.
- **Non-Negotiable Leakage Rules**:
  - Chunks from the Frozen Test Source Partition **must never** be used as training positives.
  - Chunks from the Frozen Test Source Partition **must never** be used as mined training negatives.
  - Chunks from the Frozen Test Source Partition **must never** influence hyperparameter selection or early stopping.

### The Searchable Retrieval Corpus (Evaluation Phase)
- When evaluating the frozen test benchmark, **all chunks from all partitions (Train + Validation + Test)** are present in the searchable index.
- **Evaluation Task Definition**:
  *"Given a query whose canonical evidence resides in a document from the previously unseen test partition, can the retrieval system rank that evidence at the top of the collection when searching across the entire corpus?"*

## 3. Chunking Specification

1. **Header-Aware Structural Chunking**:
   - Chunk boundaries are anchored to Markdown headings (`#`, `##`, `###`, `####`).
   - Every chunk is prefixed with its structural context breadcrumb:
     `[PostgreSQL > Chapter 13. Concurrency Control > 13.2. Transaction Isolation > 13.2.1. Read Committed Isolation Level]`
2. **Code Block Atomicity**:
   - Fenced code blocks are never split across chunks. If a code block exceeds 384 tokens, it forms an independent standalone chunk.
3. **Chunk Sizing Parameters**:
   - Maximum token count: 512 tokens.
   - Stride / Overlap: 64 tokens (sentence-boundary aligned).
4. **Deterministic Chunk Identity**:
   $$\text{chunk\_id} = \text{SHA256}(\text{ecosystem} + "::" + \text{file\_path} + "::" + \text{header\_breadcrumb} + "::" + \text{chunk\_index})$$

## 4. Query Typology & External Query Licensing

### 4.1 Query Categories
1. **Synthetic Grounded Queries**:
   - Generated from test-partition passages using structured prompt templates (comparative distinction, diagnostic troubleshooting, configuration).
   - Anti-parroting filter: Discard any synthetic query whose unigram Jaccard overlap with the source passage exceeds 0.50.
2. **Human-Authored Project Queries**:
   - Authored and manually reviewed project queries reflecting realistic implementation bugs and architectural trade-offs.
3. **Natural External Queries**:
   - Derived from public GitHub issues and Stack Overflow discussions.
   - **Licensing & Redistribution Protocol**:
     - Provenance recorded per query: source URL, repository/site, author attribution, and applicable license/terms.
     - Stack Overflow queries follow CC BY-SA terms.
     - GitHub issues follow originating repository terms.
     - Where redistribution rights are ambiguous, the benchmark stores **only provenance metadata and a manually authored paraphrase** capturing the technical scenario, avoiding redistribution of substantial original text.

## 5. Near-Duplicate Audit
- Reproducibility is improved by pinning the SQLite build, tokenizer, schema, corpus snapshot, insertion order, and evaluation code.
- Prior to freezing splits, execute MinHash LSH (5-gram character shingles) and pairwise dense cosine similarity audits across partition boundaries.
- The audit detects and quarantines near-duplicates above defined thresholds (Jaccard $> 0.65$, cosine $> 0.90$). It is acknowledged that undetected subtle semantic overlap may remain.

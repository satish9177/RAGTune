# RAGTune: Adversarial Risk Analysis & Project Invalidation Defense

This document systematically analyzes failure modes, leakage risks, and unverified assumptions.

---

### Risk 1: Train/Test Partition Leakage Across Related Documents
- **Threat Vector**: Technical documentation frequently repeats API signatures, parameter definitions, and architectural overviews across multiple chapters. If related files are split across train and test sets, the model learns surface-level textual memorization rather than generalized retrieval.
- **Severity**: Critical. Inflates Recall@K and NDCG by 15–25%, rendering reported improvements spurious.
- **Defense Mechanism**:
  - Enforce partition separation at the **document root/topic level**, not at the chunk level.
  - Run MinHash LSH and pairwise dense cosine similarity audits across partition boundaries.
  - Quarantining Rule: Any passage pair spanning train and test partitions with 5-gram Jaccard similarity $> 0.65$ or cosine similarity $> 0.90$ is quarantined.
  - *Acknowledged Limitation*: Audits detect and quarantine near-duplicates above defined thresholds; subtle semantic overlap may remain.

---

### Risk 2: Synthetic Query Hallucination & Lexical Parroting
- **Threat Vector**: LLM-generated queries often copy distinctive phrasing from the target passage, converting semantic retrieval into trivial substring matching.
- **Severity**: High. Bi-encoders overfit to exact lexical matches, degrading on natural user questions.
- **Defense Mechanism**:
  - Multi-perspective query generation templates (comparative distinction, diagnostic troubleshooting, architectural trade-offs).
  - Lexical Overlap Gate: Discard any synthetic query whose unigram Jaccard overlap with the source passage exceeds 0.50.
  - Tri-Partite Benchmark Composition: Benchmark v0 and v1 balance synthetic queries, human-authored project queries, and external queries.
  - Disaggregate reported metrics across all three query categories to detect synthetic-specific bias.

---

### Risk 3: False-Negative Penalization in Hard-Negative Mining
- **Threat Vector**: In comprehensive documentation, multiple passages often provide valid answers. If a candidate retrieval passage is actually relevant and labeled as a negative, contrastive InfoNCE loss heavily penalizes the model for retrieving correct information.
- **Severity**: Critical. Destabilizes gradient updates and causes representational collapse.
- **Defense Mechanism**:
  - Abolish arbitrary raw threshold cutoffs (`score < 0.60`).
  - Score Margin Filter: Accept hard negative $d^-$ if and only if $s_{\text{CE}}(q, d^+) - s_{\text{CE}}(q, d^-) > \Delta_{\text{margin}}$.
  - Multi-Positive Promotion: If candidate negative $d^-$ receives high teacher relevance or ranks alongside ground-truth positives, it is promoted to an alternate positive or quarantined, never treated as negative.

---

### Risk 4: Catastrophic Forgetting & Domain Over-Specialization
- **Threat Vector**: Fine-tuning an embedding model on technical documentation compresses its representation space, degrading performance on general reasoning, semantic search, and out-of-domain technical queries.
- **Severity**: High. Yields a brittle model that fails on realistic multi-domain enterprise workloads.
- **Defense Mechanism**:
  - Multi-Tiered Out-of-Domain Promotion Gate:
    - Near-Domain / General Technical: Evaluate on BRIGHT LeetCode and StackOverflow subsets (allowed degradation $\le 1.0\%$).
    - Strong Out-of-Domain: Evaluate on BRIGHT Biology, Economics, Earth Science, and BEIR SciFact / FiQA (allowed degradation $\le 1.5\%$).
  - Any model failing out-of-domain gates is automatically rejected regardless of internal metric gains.

---

### Risk 5: Metric Inflation via Flawed Statistical Testing
- **Threat Vector**: Running multiple evaluation checkpoints and selecting the one with Wilcoxon $p < 0.05$ exploits sample variance without demonstrating meaningful engineering improvement.
- **Severity**: Medium-High.
- **Defense Mechanism**:
  - Compute 10,000-sample paired bootstrap confidence intervals (BCa 95%) for $\Delta \text{NDCG@10}$ and $\Delta \text{MRR@10}$.
  - Compute McNemar's test for binary Recall@K hit/miss transitions.
  - Require the lower bound of the 95% bootstrap confidence interval to be $> 0.000$ and require a minimum practical effect size ($\Delta \text{Recall@10} \ge +2.5\%$).

---

### Risk 6: Hardware Hypotheses vs. Empirical Measurements
- **Threat Vector**: Assuming training hyperparameters (batch size, VRAM footprint, latency) without empirical profiling risks CUDA OOM crashes, uncalibrated latency claims, and non-reproducible runtimes.
- **Severity**: Medium.
- **Defense Mechanism**:
  - Treat all memory numbers as initial hypotheses until `benchmarks/hardware_profile.py` is executed on the target machine.
  - Persist exact GPU model, driver, CUDA/PyTorch versions, micro-batch sizes, and measured peak allocated VRAM.

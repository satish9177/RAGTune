# E7 Safe-Negative Audit: AI Review & Quality Gate Failure Report

> [!CAUTION]
> **AUDIT QUALITY GATE FAILED**: `AI_REVIEW_FAILED_NEGATIVE_QUALITY_GATE`
> An AI-assisted semantic review of `E7_NEGATIVE_AUDIT_40.md` revealed a **32.5% False-Negative Rate** (13/40) and **17.5% Ambiguous/Unsafe Rate** (7/40).
> Only 50.0% (20/40) of sampled items were confirmed as true negatives.
> **Under no circumstances may E7 domain reranker training proceed with these candidates.**
> These classifications are AI review recommendations only and do NOT represent Satish human signoff.

## 1. Audit Summary

- **Total Candidates Audited**: 40
- **TRUE_NEGATIVE**: 20 (50.0%)
- **FALSE_NEGATIVE**: 13 (32.5%) — **GATE FAILURE**
- **AMBIGUOUS / UNSAFE**: 7 (17.5%)
- **Gate Requirement**: ZERO FALSE_NEGATIVE, $\le 2$ AMBIGUOUS.

## 2. Root Cause Analysis: Circular Teacher Certification

The previous mining pipeline relied circularly on `BAAI/bge-reranker-base` teacher margins as the primary determinant of `SAFE_NEGATIVE`:
1. **Pretrained Model Blindspot**: As demonstrated in experiment E6, generic BGE reranker weights frequently misjudge technical documentation, assigning high confidence to general prose and low scores to concise YAML/code syntax.
2. **Same-Document Subtopic Leaks**: Candidates residing in the exact same document as the positive were accepted if their breadcrumb differed slightly, allowing adjacent procedural steps and explanations to be labeled as negatives.
3. **Entity Match Neglect**: When a query asked about a specific configuration key (e.g. `priorityClassName`), candidates containing that exact key and explaining how to use it in YAML were classified as safe negatives simply because the teacher produced a wide margin.
4. **Comparative Query Asymmetry**: For comparative queries ('What is the difference between A and B'), candidates explaining A or B in full detail were labeled negatives because they did not explicitly mention the other entity.

## 3. Itemized Failure Ledger

### A. FALSE_NEGATIVE Items (13 Items — Disqualifying)

| # | Query ID | Ecosystem | Query Text | Diagnostic Finding |
|---:|---|---|---|---|
| 11 | `train_py_0126` | pytorch | `What is the configuration and purpose of Guar...` | Same document (torch.compiler_guards_overview.rst) detailing downstream VariableBuilder and VariableTracker logic directly addressing Guards Variables. |
| 16 | `train_py_0141` | pytorch | `What is the difference and interaction betwee...` | Same document (distributed.rst) explaining TORCH_DISTRIBUTED_DEBUG usage, monitored_barrier, and debug log levels. |
| 17 | `train_py_0151` | pytorch | `What is the configuration and purpose of CUDA...` | Same document (notes/cuda.rst) explaining CUDA device semantics and tensor device assignment best practices. |
| 21 | `train_ku_0265` | kubernetes | `How to use and configure AdmissionReview in k...` | Same document (reference/access-authn-authz/extensible-admission-controllers.md) showing webhook POST requests with AdmissionReview API object structure. |
| 22 | `train_ku_0268` | kubernetes | `How to use and configure priorityClassName in...` | Same document (concepts/scheduling-eviction/pod-priority-preemption.md) explaining how to configure priorityClassName in Pod specs. |
| 26 | `train_ku_0278` | kubernetes | `What is the configuration and purpose of Inst...` | Same document (tasks/administer-cluster/network-policy-provider/romana-network-policy.md) containing procedural instructions for installing and applying Romana network policy. |
| 28 | `train_ku_0289` | kubernetes | `What is the configuration and purpose of Depl...` | Same document (tasks/administer-cluster/network-policy-provider/antrea-network-policy.md) containing procedural instructions for deploying Antrea CNI on Kubernetes. |
| 29 | `train_ku_0299` | kubernetes | `What is the difference and interaction betwee...` | Candidate from horizontal-pod-autoscale.md substantively explains how HPA interacts with spec.replicas in Deployments/StatefulSets. |
| 32 | `train_fa_0383` | fastapi | `What is the difference and interaction betwee...` | Candidate from features.md explicitly defines and validates both dict and list Python data types in FastAPI. |
| 33 | `train_fa_0384` | fastapi | `What is the configuration and purpose of Depl...` | Same document (deployment/concepts.md) explaining automatic restarts and process managers for crash recovery. |
| 35 | `train_fa_0387` | fastapi | `What is the difference and interaction betwee...` | Same document (tutorial/extra-models.md) explaining how user_in maps to UserIn / UserInDB. |
| 36 | `train_fa_0392` | fastapi | `What is the configuration and purpose of Get ...` | Candidate from advanced/security/oauth2-scopes.md explains the get_current_user dependency tree and security scope propagation. |
| 37 | `train_fa_0393` | fastapi | `How to use and configure get_current_user in ...` | Candidate from advanced/security/oauth2-scopes.md explains how get_current_user is configured as a dependency. |

### B. AMBIGUOUS / UNSAFE Items (7 Items)

| # | Query ID | Ecosystem | Query Text | Diagnostic Finding |
|---:|---|---|---|---|
| 5 | `train_po_0018` | postgresql | `How to resolve warning issues with pg_subscri...` | Candidate from alter_subscription.sgml covers logical replication constraint error skipping, semantically adjacent to subscription warnings. |
| 7 | `train_po_0022` | postgresql | `How to resolve error issues with lo_read in p...` | Same document (lobj.sgml) discussing server-side lo_read and lo_write function calls. |
| 8 | `train_po_0028` | postgresql | `What is the difference and interaction betwee...` | Candidate explains postgresql.conf parameter settings and reload behavior without restart, covering one side of the comparative query. |
| 13 | `train_py_0131` | pytorch | `What is the difference and interaction betwee...` | Candidate from fx.rst provides code example of torch.fx.symbolic_trace, directly addressing one side of the comparative query. |
| 27 | `train_ku_0287` | kubernetes | `What is the difference and interaction betwee...` | Same document (reference/access-authn-authz/kubelet-tls-bootstrapping.md) explaining --client-ca-file and certificate authentication. |
| 30 | `train_ku_0300` | kubernetes | `What is the configuration and purpose of Metr...` | Same document (tasks/debug/debug-cluster/resource-metrics-pipeline.md) discussing kubelet node metrics and Kubernetes API access. |
| 34 | `train_fa_0385` | fastapi | `What is the configuration and purpose of Extr...` | Same document (tutorial/extra-models.md) discussing response declarations with plain arbitrary dict and Pydantic models. |

### C. TRUE_NEGATIVE Items (20 Items)

| # | Query ID | Ecosystem | Query Text | Hybrid Rank | Teacher Margin |
|---:|---|---|---|---:|---:|
| 1 | `train_po_0002` | postgresql | `How to use and configure REL_16_STABLE in postgres...` | #7 | 0.7111 |
| 2 | `train_po_0011` | postgresql | `How to use and configure vacuum_freeze_table_age i...` | #11 | 0.5165 |
| 3 | `train_po_0013` | postgresql | `What is the configuration and purpose of Example P...` | #1 | 0.7524 |
| 4 | `train_po_0017` | postgresql | `What is the difference and interaction between pg_...` | #4 | 0.8578 |
| 6 | `train_po_0021` | postgresql | `What is the difference and interaction between lo_...` | #4 | 0.8676 |
| 9 | `train_po_0030` | postgresql | `How to use and configure REL_16_STABLE in postgres...` | #7 | 0.7029 |
| 10 | `train_po_0034` | postgresql | `What is the difference and interaction between tup...` | #19 | 0.6280 |
| 12 | `train_py_0129` | pytorch | `What is the configuration and purpose of Quantizat...` | #2 | 0.4179 |
| 14 | `train_py_0133` | pytorch | `What is the difference and interaction between tor...` | #2 | 0.6223 |
| 15 | `train_py_0140` | pytorch | `How to use and configure TORCH_DISTRIBUTED_DEBUG i...` | #9 | 0.9058 |
| 18 | `train_py_0152` | pytorch | `How to use and configure argparse in pytorch?...` | #3 | 0.8343 |
| 19 | `train_py_0153` | pytorch | `What is the difference and interaction between arg...` | #9 | 0.8802 |
| 20 | `train_py_0154` | pytorch | `How to resolve fail issues with argparse in pytorc...` | #3 | 0.8737 |
| 23 | `train_ku_0275` | kubernetes | `How to use and configure ownerReference in kuberne...` | #8 | 0.2629 |
| 24 | `train_ku_0276` | kubernetes | `What is the difference and interaction between own...` | #5 | 0.7770 |
| 25 | `train_ku_0277` | kubernetes | `How to resolve warning issues with ownerReference ...` | #3 | 0.3420 |
| 31 | `train_fa_0379` | fastapi | `How to use and configure app in fastapi?...` | #2 | 0.2772 |
| 38 | `train_fa_0408` | fastapi | `What is the configuration and purpose of Path Oper...` | #4 | 0.9581 |
| 39 | `train_fa_0409` | fastapi | `How to use and configure response_description in f...` | #3 | 0.9324 |
| 40 | `train_fa_0410` | fastapi | `What is the difference and interaction between res...` | #2 | 0.9498 |

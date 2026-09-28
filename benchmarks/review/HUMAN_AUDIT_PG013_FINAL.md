# RAGTune Benchmark Audit: Focused Evidence Review for `v0_pg_013`

**Query ID**: `v0_pg_013`  
**Query Text**: *"How does enabling hot_standby_feedback prevent query cancellation on physical replicas compared to increasing max_standby_streaming_delay?"*  
**Ecosystem**: `postgresql` | **Typology**: `comparative_discrimination` | **Role**: `development`  
**Provenance**: `ai_authored_project_query` | **Generator**: `ai_agent` | **Inspiration**: `Replication query cancellation conflicts`  
**Audit Status**: **`[PENDING FINAL HUMAN REVIEW]`**  
**AI Recommendation**: **`APPROVE_CANDIDATE`**  
**Uncertainty Flag**: `TRUE (Borderline / Nuanced Comparative Relevance)`  

---

## 1. Verified Evidence Passages

Both sides of the comparative query are directly grounded in the official PostgreSQL 16 `config.sgml` (Server Configuration) documentation within the `validation` partition:

| Relevance Grade | Chunk ID | File Path | Token Count | Key Functionality Covered |
|:---|:---:|:---|:---:|:---|
| **Grade 3 (Canonical Best Evidence)** | `4cb1a6e848ab` | `doc/src/sgml/config.sgml` | 450 | `hot_standby_feedback` mechanics: feedback to primary, eliminates cleanup record query cancellations, risk of primary bloat |
| **Grade 2 (Directly Relevant Supporting)** | `7ebc2979ff55` | `doc/src/sgml/config.sgml` | 384 | `max_standby_streaming_delay` mechanics: wait window before canceling conflicting queries, cumulative WAL apply grace time |

*(Note: Unrelated fsync passage `b239bf42ebfe` was removed in Phase A repair).*

---

## 2. Exact Answer-Bearing Spans (Ground-Truth Citations)

### Side A — Grade 3: `hot_standby_feedback` Mechanics (Chunk ID: `4cb1a6e848ab`)

> "_Specifies whether or not a hot standby will send feedback to the primary or upstream standby about queries currently executing on the standby. This parameter can be used to eliminate query cancels caused by cleanup records, but can cause database bloat on the primary for some workloads. Feedback messages will not be sent more frequently than once per wal_receiver_status_interval . The default value is off . This parameter can only be set in the postgresql.conf file or on the server command line._"

### Side B — Grade 2: `max_standby_streaming_delay` Mechanics (Chunk ID: `7ebc2979ff55`)

> "_When hot standby is active, this parameter determines how long the standby server should wait before canceling standby queries that conflict with about-to-be-applied WAL entries, as described in Section 27.4.2. max_standby_streaming_delay applies when WAL data is being received via streaming replication. If this value is specified without units, it is taken as milliseconds. The default is 30 seconds. A value of -1 allows the standby to wait forever for conflicting queries to complete. This parameter can only be set in the postgresql.conf file or on the server command line._
> 
> _Note that max_standby_streaming_delay is not the same as the maximum length of time a query can run before cancellation; rather it is the maximum total time allowed to apply WAL data once it has been received from the primary server. Thus, if one query has resulted in significant delay, subsequent conflicting queries will have much less grace time until the standby server has caught up again._"

---

## 3. Comparative Technical Discrimination

The two passages collectively answer the full comparative question:

1. **How `hot_standby_feedback` prevents cancellation**:
   By actively informing the primary server of the oldest active transaction on the standby, `hot_standby_feedback` prevents `VACUUM` on the primary from removing dead row versions that might still be needed by standby queries. Because cleanup records for those rows are never emitted, the standby avoids conflict-induced cancellations at the root cause, accepting the operational trade-off of potential table bloat on the primary.

2. **How `max_standby_streaming_delay` handles cancellation differently**:
   Rather than preventing conflicts at the primary, `max_standby_streaming_delay` operates strictly locally on the replica. It pauses the application of conflicting incoming WAL entries up to a configured threshold (default 30s, or -1 for infinite), granting the executing query a grace window to finish before canceling it to prevent runaway replication lag.

---

## 4. Human Reviewer Decision (Satish)

- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**
- **Reviewer Notes**: _____________________________________________________
- **Decision Date**: ____________________

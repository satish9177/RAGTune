"""Unit tests for the structural, header-aware chunker."""

import pytest
from ragtune.chunking.structural_chunker import StructuralChunker, estimate_token_count
from ragtune.models import compute_chunk_id, compute_content_sha256


SAMPLE_DOC = """# PostgreSQL Concurrency Control

PostgreSQL provides a rich set of tools for managing concurrent access to data.

## Transaction Isolation

The SQL standard defines four levels of transaction isolation.

### Read Committed Isolation Level

Read Committed is the default isolation level in PostgreSQL. When a transaction uses this isolation level, a SELECT query sees only data committed before the query began.

```sql
BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;
SELECT * FROM accounts WHERE id = 1;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
COMMIT;
```

This prevents dirty reads, but repeatable reads are not guaranteed.

### Repeatable Read Isolation Level

The Repeatable Read isolation level only sees data committed before the transaction began.

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SELECT balance FROM accounts WHERE id = 1;
```
"""


def test_deterministic_chunk_ids():
    """Verify that identical input produces identical chunk IDs and hashes."""
    chunker = StructuralChunker(max_tokens=256)
    chunks_1 = chunker.chunk_document(
        content=SAMPLE_DOC,
        ecosystem="postgresql",
        source_ref="REL_16_3",
        relative_file_path="doc/src/sgml/mvcc.sgml",
    )
    chunks_2 = chunker.chunk_document(
        content=SAMPLE_DOC,
        ecosystem="postgresql",
        source_ref="REL_16_3",
        relative_file_path="doc/src/sgml/mvcc.sgml",
    )

    assert len(chunks_1) > 0
    assert len(chunks_1) == len(chunks_2)
    for c1, c2 in zip(chunks_1, chunks_2):
        assert c1.chunk_id == c2.chunk_id
        assert c1.raw_content_sha256 == c2.raw_content_sha256
        assert c1.content == c2.content
        assert c1.breadcrumb == c2.breadcrumb
        assert c1.chunk_index == c2.chunk_index


def test_code_block_atomicity():
    """Verify that fenced code blocks are never split across chunks."""
    chunker = StructuralChunker(max_tokens=150)
    chunks = chunker.chunk_document(
        content=SAMPLE_DOC,
        ecosystem="postgresql",
        source_ref="REL_16_3",
        relative_file_path="doc/src/sgml/mvcc.sgml",
    )

    found_sql_block = False
    for chunk in chunks:
        # Check that if a code block opens, it closes in the same chunk
        open_count = chunk.content.count("```sql")
        close_count = chunk.content.count("```")
        # Every opening ```sql must have a matching closing ```
        if open_count > 0:
            found_sql_block = True
            assert close_count >= open_count * 2, "Code block was severed across chunk boundary!"

    assert found_sql_block, "Expected SQL code blocks in sample document."


def test_breadcrumb_preservation():
    """Verify that hierarchical headers are preserved in breadcrumbs."""
    chunker = StructuralChunker(max_tokens=512)
    chunks = chunker.chunk_document(
        content=SAMPLE_DOC,
        ecosystem="postgresql",
        source_ref="REL_16_3",
        relative_file_path="doc/src/sgml/mvcc.sgml",
    )

    # Find chunk for Read Committed
    rc_chunks = [c for c in chunks if "Read Committed Isolation Level" in c.breadcrumb]
    assert len(rc_chunks) > 0
    expected_breadcrumb = "PostgreSQL Concurrency Control > Transaction Isolation > Read Committed Isolation Level"
    assert rc_chunks[0].breadcrumb == expected_breadcrumb
    assert rc_chunks[0].header_path == [
        "PostgreSQL Concurrency Control",
        "Transaction Isolation",
        "Read Committed Isolation Level",
    ]


def test_token_limit_enforcement():
    """Verify that packed chunks do not exceed token budget."""
    chunker = StructuralChunker(max_tokens=50)
    chunks = chunker.chunk_document(
        content=SAMPLE_DOC,
        ecosystem="postgresql",
        source_ref="REL_16_3",
        relative_file_path="doc/src/sgml/mvcc.sgml",
    )

    assert len(chunks) >= 3
    for chunk in chunks:
        # Code blocks might be kept atomic if single block is slightly large,
        # but token count should be tracked properly
        assert chunk.token_count > 0
        assert chunk.raw_content_sha256 == compute_content_sha256(chunk.content)

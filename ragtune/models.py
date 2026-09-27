"""Core data models for RAGTune."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


def compute_chunk_id(
    ecosystem: str,
    source_ref: str,
    relative_file_path: str,
    header_path: List[str],
    chunk_index: int,
) -> str:
    """Generate a deterministic SHA256 chunk identifier."""
    key = f"{ecosystem}::{source_ref}::{relative_file_path}::{' > '.join(header_path)}::{chunk_index}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def compute_content_sha256(content: str) -> str:
    """Generate SHA256 of raw chunk content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PassageChunk(BaseModel):
    """Normalized structural chunk representing a single retrieval candidate."""

    chunk_id: str = Field(description="Deterministic hash identifier")
    ecosystem: Literal["postgresql", "pytorch", "kubernetes", "fastapi"]
    source_ref: str = Field(description="Source Git tag or commit hash")
    relative_file_path: str = Field(description="Relative path within documentation source")
    header_path: List[str] = Field(default_factory=list, description="List of hierarchical headers")
    breadcrumb: str = Field(description="Human-readable header breadcrumb")
    chunk_index: int = Field(description="Zero-indexed ordinal within the document section")
    content: str = Field(description="Clean text/markdown content including code blocks")
    raw_content_sha256: str = Field(description="SHA-256 hash of the exact content")
    token_count: int = Field(description="Estimated or exact token length")
    partition: Optional[Literal["train", "validation", "frozen_test"]] = Field(
        default=None, description="Assigned partition split"
    )
    continuation_index: int = Field(
        default=0, description="Zero-indexed ordinal if section was split across chunks"
    )
    continuation_total: int = Field(
        default=1, description="Total number of chunks created from this section"
    )
    original_section_id: str = Field(
        default="", description="Unique identifier of the logical section before fallback splitting"
    )
    content_type: Literal["prose", "code", "table", "mixed"] = Field(
        default="mixed", description="Dominant content type of the chunk"
    )
    is_code_continuation: bool = Field(
        default=False, description="True if this chunk continues an earlier code block"
    )
    is_table_continuation: bool = Field(
        default=False, description="True if this chunk continues an earlier table"
    )

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }


class RelevanceJudgment(BaseModel):
    """Graded relevance assignment for a single passage chunk."""

    chunk_id: str = Field(description="Referenced PassageChunk chunk_id")
    grade: Literal[0, 1, 2, 3] = Field(
        description="Relevance grade: 0=irrelevant, 1=useful/supporting, 2=directly relevant, 3=canonical best evidence"
    )
    notes: str = Field(default="", description="Annotation justification")

    model_config = {"frozen": True}


class BenchmarkQuery(BaseModel):
    """Unified schema for benchmark evaluation queries."""

    query_id: str = Field(description="Unique query identifier, e.g. pilot_pg_001")
    domain: Literal["postgresql", "pytorch", "kubernetes", "fastapi"]
    query_text: str = Field(description="Exact query string presented to retrieval systems")
    typology: Literal["direct_lookup", "comparative_discrimination", "troubleshooting_scenario"]
    provenance_type: Literal[
        "synthetic_grounded",
        "ai_authored_project_query",
        "external_derived_verified",
        "human_authored",
        "human_reviewed_project_query",
        "external_derived",
    ]
    provenance_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Provenance tracking: URL, license, author attribution, paraphrase status"
    )
    relevant_chunks: List[RelevanceJudgment] = Field(
        description="List of multi-positive graded relevance judgments"
    )
    source_partition: Literal["train", "validation", "frozen_test"] = Field(
        default="frozen_test", description="Source partition of ground-truth evidence: train, validation, or frozen_test"
    )
    role: Literal["training", "development", "final_test", "engineering_smoke_test"] = Field(
        default="engineering_smoke_test",
        description="Role: training (train), development (validation / Benchmark v0), final_test (frozen_test), or engineering_smoke_test (pilot)"
    )
    uncertainty: bool = Field(default=False, description="Flag indicating borderline or ambiguous relevance")
    annotation_notes: str = Field(default="", description="Reviewer notes and guidelines adherence")
    review_status: Literal["UNREVIEWED", "APPROVED", "REVISE", "REJECTED"] = Field(
        default="UNREVIEWED", description="Human review state"
    )
    reviewer: Optional[str] = Field(default=None, description="Human reviewer identifier")
    review_notes: str = Field(default="", description="Human reviewer notes or change requests")
    reviewed_at: Optional[str] = Field(default=None, description="UTC timestamp of human review")
    ai_recommendation: Literal["APPROVE_CANDIDATE", "REVISE_CANDIDATE", "REJECT_CANDIDATE"] = Field(
        default="APPROVE_CANDIDATE", description="Preliminary AI quality audit recommendation"
    )

    model_config = {"frozen": True}


"""Automated Evidence Sanity Verifier for Benchmark v0.

NOTE: This automated verifier is a sanity check layer, NOT a human-equivalent
semantic certification. Passing this check does not equate to formal human relevance.

Classifies queries into:
- AUTOMATED_CHECK_PASS: Evidence passes structural sanity checks, contains key entities, and avoids generic intros.
- AUTOMATED_CHECK_REVIEW: Candidate evidence requires manual inspection (e.g. subtle multi-aspect, potential displacement).
- AUTOMATED_CHECK_FAIL: Defective evidence mapping (generic intro, missing key entity, or cross-partition reference).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple


GENERIC_INTRO_PATTERNS = [
    r"The previous chapter discussed",
    r"The system catalogs are the place where",
    r"This document describes\s+persistent volumes",
    r"Managing storage is a distinct problem from managing compute",
    r"A _Deployment_ provides declarative updates for",
    r"The following are typical use cases for Deployments",
    r"Details about the `async def` syntax for \*path operation",
    r"backward\s+grad\s+Forward-mode Automatic Differentiation",
    r"The ONNX exporter for TorchDynamo is a rapidly evolving beta",
    r"\*\*FastAPI\*\* allows you to declare additional information and validation for your parameters",
    r"In some situations, you might need to use a \*\*proxy\*\*",
    r"configuration\s+of the server\s+There are many configuration parameters",
    r"Valid memory units are B \(bytes\)",
]


def is_generic_intro(text: str) -> bool:
    for pat in GENERIC_INTRO_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def extract_answer_span(content: str, query_terms: List[str], window_chars: int = 550) -> str:
    """Extract an answer-bearing window centered on the most relevant sentences.
    
    Ensures that the distinguishing statement is not prematurely truncated.
    Expands across sentence and paragraph boundaries up to window_chars.
    """
    clean_content = content.strip()
    if len(clean_content) <= window_chars:
        return clean_content.replace("\n", " ").strip()

    # Split into clean paragraphs first
    paragraphs = [p.strip() for p in clean_content.split("\n\n") if p.strip()]
    best_para_idx = 0
    best_para_score = -1

    for idx, p in enumerate(paragraphs):
        score = sum(1 for t in query_terms if re.search(r"\b" + re.escape(t) + r"\b", p, re.IGNORECASE))
        if score > best_para_score:
            best_para_score = score
            best_para_idx = idx

    # If target paragraph is large, split into sentences
    if len(paragraphs[best_para_idx]) > window_chars:
        sentences = re.split(r"(?<=[.!?])\s+", paragraphs[best_para_idx])
        best_sent_idx = 0
        best_score = -1

        for idx, sent in enumerate(sentences):
            score = sum(1 for t in query_terms if re.search(r"\b" + re.escape(t) + r"\b", sent, re.IGNORECASE))
            if score > best_score:
                best_score = score
                best_sent_idx = idx

        # Window around best sentence
        start = best_sent_idx
        end = best_sent_idx + 1
        total_len = len(sentences[best_sent_idx])

        while total_len < window_chars and (start > 0 or end < len(sentences)):
            if end < len(sentences):
                total_len += len(sentences[end])
                end += 1
            if start > 0 and total_len < window_chars:
                start -= 1
                total_len += len(sentences[start])

        span = " ".join(s.strip() for s in sentences[start:end])
        return span.replace("\n", " ").strip()

    # Otherwise expand paragraph window around best_para_idx
    start = best_para_idx
    end = best_para_idx + 1
    total_len = len(paragraphs[best_para_idx])

    while total_len < window_chars and (start > 0 or end < len(paragraphs)):
        if end < len(paragraphs):
            total_len += len(paragraphs[end])
            end += 1
        if start > 0 and total_len < window_chars:
            start -= 1
            total_len += len(paragraphs[start])

    span = " ".join(p.strip() for p in paragraphs[start:end])
    span = span.replace("\n", " ").strip()
    if len(span) > window_chars + 100:
        span = span[:window_chars] + "..."
    return span

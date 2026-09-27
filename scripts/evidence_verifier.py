"""Evidence Verification and Answer-Bearing Chunk Finder for Benchmark v0.

Evaluates relevance judgments across:
1. Direct Lookup: target identifier/option/behavior must be defined in the passage.
2. Comparative Discrimination: both compared entities must be covered.
3. Troubleshooting: error condition/symptom and resolution/mechanism must be present.
4. Anti-generic check: flags generic introductions, TOCs, and high-level summaries.

Classifies queries into:
- EVIDENCE_STRONG
- EVIDENCE_NEEDS_REVIEW
- EVIDENCE_INVALID
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


def extract_answer_span(content: str, query_terms: List[str], window_chars: int = 300) -> str:
    """Extract a window centered on the most relevant sentence or term match."""
    # Split into sentences or paragraphs
    sentences = re.split(r"(?<=[.!?\n])\s+", content)
    best_sent_idx = 0
    best_score = -1

    for idx, sent in enumerate(sentences):
        score = sum(1 for t in query_terms if re.search(r"\b" + re.escape(t) + r"\b", sent, re.IGNORECASE))
        if score > best_score:
            best_score = score
            best_sent_idx = idx

    # If no match on word boundary, try substring
    if best_score <= 0:
        for idx, sent in enumerate(sentences):
            score = sum(1 for t in query_terms if t.lower() in sent.lower())
            if score > best_score:
                best_score = score
                best_sent_idx = idx

    # Window around best sentence
    matched_sent = sentences[best_sent_idx].strip()
    if len(matched_sent) >= window_chars:
        # Center inside sentence
        return matched_sent[:window_chars].strip() + "..."

    # Expand to adjacent sentences
    start = best_sent_idx
    end = best_sent_idx + 1
    total_len = len(matched_sent)

    while total_len < window_chars and (start > 0 or end < len(sentences)):
        if end < len(sentences):
            total_len += len(sentences[end])
            end += 1
        if start > 0 and total_len < window_chars:
            start -= 1
            total_len += len(sentences[start])

    span = " ".join(s.strip() for s in sentences[start:end])
    span = span.replace("\n", " ").strip()
    if len(span) > window_chars + 50:
        span = span[:window_chars] + "..."
    return span

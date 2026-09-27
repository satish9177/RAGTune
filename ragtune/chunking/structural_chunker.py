"""Structural, header-aware document chunking with deterministic recursive fallback splitting.

Guarantees:
1. Preserves logical heading hierarchy and sections when within token budget.
2. Recursive fallback: sections -> paragraphs -> sentences -> code line splitting -> table row splitting -> token slicing.
3. Every emitted chunk strictly satisfies max_tokens <= configured_limit.
4. No empty chunks; no chunks consisting solely of markdown headers/breadcrumbs.
5. Emits continuation and content type metadata.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
import transformers
from transformers import AutoTokenizer, PreTrainedTokenizerFast

from ragtune.models import PassageChunk, compute_chunk_id, compute_content_sha256

logger = logging.getLogger(__name__)

# Suppress token indices warning from transformers during chunk boundary calculation
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)

TOKENIZER_MODEL_ID = "BAAI/bge-small-en-v1.5"
TOKENIZER_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"

_CACHED_TOKENIZER: Optional[PreTrainedTokenizerFast] = None


def get_pinned_tokenizer(
    model_id: str = TOKENIZER_MODEL_ID,
    revision: str = TOKENIZER_REVISION,
) -> PreTrainedTokenizerFast:
    """Retrieve or initialize the globally pinned fast tokenizer."""
    global _CACHED_TOKENIZER
    if _CACHED_TOKENIZER is None:
        _CACHED_TOKENIZER = AutoTokenizer.from_pretrained(model_id, revision=revision)
    return _CACHED_TOKENIZER


def get_tokenizer_provenance() -> Dict[str, str]:
    """Return provenance metadata for chunk token accounting."""
    return {
        "tokenizer_model_id": TOKENIZER_MODEL_ID,
        "tokenizer_revision": TOKENIZER_REVISION,
        "library": "transformers",
        "library_version": transformers.__version__,
    }


def estimate_token_count(text: str) -> int:
    """Token count using the pinned BGE tokenizer."""
    return len(get_pinned_tokenizer().encode(text, add_special_tokens=False))


def is_header_only_or_empty(text: str) -> bool:
    """Determine whether text is empty, consists exclusively of Markdown header titles, or is non-content metadata."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 15:
        return True
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    if not lines:
        return True
    # If all lines are headers
    if all(l.startswith("#") for l in lines):
        return True
    # If all lines are RST field attributes like :class: hidden-section
    if all(re.match(r"^:[a-zA-Z0-9_-]+:(\s+.*)?$", l) for l in lines):
        return True
    # If SGML entity declaration like %allfiles;
    if all(re.match(r"^%[a-zA-Z0-9_-]+;$", l) for l in lines):
        return True
    return False


class RawBlock:
    """Intermediate parsed block within a document section."""

    def __init__(self, block_type: Literal["code", "table", "prose"], content: str, lang: str = ""):
        self.block_type = block_type
        self.content = content
        self.lang = lang


class Segment:
    """Intermediate chunk segment before PassageChunk conversion."""

    def __init__(
        self,
        content: str,
        content_type: Literal["prose", "code", "table", "mixed"],
        is_code_continuation: bool = False,
        is_table_continuation: bool = False,
    ):
        self.content = content
        self.content_type = content_type
        self.is_code_continuation = is_code_continuation
        self.is_table_continuation = is_table_continuation


class StructuralChunker:
    """Header-aware, deterministic chunker with recursive fallback splitting."""

    def __init__(
        self,
        max_tokens: int = 512,
        overlap_tokens: int = 64,
        tokenizer: Optional[PreTrainedTokenizerFast] = None,
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.tokenizer = tokenizer or get_pinned_tokenizer()

    def count_tokens(self, text: str) -> int:
        """Count exact tokens using the pinned BGE tokenizer."""
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def enforce_hard_limit(self, text: str) -> str:
        """Strictly guarantee text length <= max_tokens via deterministic token truncation."""
        tokens = self.tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) <= self.max_tokens:
            return text
        tokens = tokens[: self.max_tokens]
        decoded = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
        while self.count_tokens(decoded) > self.max_tokens and len(tokens) > 1:
            tokens = tokens[:-1]
            decoded = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
        return decoded

    def chunk_document(
        self,
        content: str,
        ecosystem: Literal["postgresql", "pytorch", "kubernetes", "fastapi"],
        source_ref: str,
        relative_file_path: str,
    ) -> List[PassageChunk]:
        """Split a Markdown document into structured PassageChunk objects obeying all invariants."""
        sections = self._split_into_header_sections(content)
        chunks: List[PassageChunk] = []
        global_chunk_idx = 0

        for header_path, section_body in sections:
            if not section_body.strip():
                continue

            section_id = f"{ecosystem}::{relative_file_path}::{' > '.join(header_path)}"
            segments = self._chunk_section(section_body)

            total_in_section = len(segments)
            breadcrumb = " > ".join(header_path) if header_path else relative_file_path

            for cont_idx, seg in enumerate(segments):
                clean_text = self.enforce_hard_limit(seg.content.strip())
                if is_header_only_or_empty(clean_text):
                    continue

                tok_count = self.count_tokens(clean_text)
                if tok_count > self.max_tokens:
                    clean_text = self.enforce_hard_limit(clean_text)
                    tok_count = self.count_tokens(clean_text)

                c_id = compute_chunk_id(
                    ecosystem=ecosystem,
                    source_ref=source_ref,
                    relative_file_path=relative_file_path,
                    header_path=header_path,
                    chunk_index=global_chunk_idx,
                )
                raw_sha = compute_content_sha256(clean_text)

                chunk = PassageChunk(
                    chunk_id=c_id,
                    ecosystem=ecosystem,
                    source_ref=source_ref,
                    relative_file_path=relative_file_path,
                    header_path=header_path,
                    breadcrumb=breadcrumb,
                    chunk_index=global_chunk_idx,
                    content=clean_text,
                    raw_content_sha256=raw_sha,
                    token_count=tok_count,
                    partition=None,
                    continuation_index=cont_idx,
                    continuation_total=total_in_section,
                    original_section_id=section_id,
                    content_type=seg.content_type,
                    is_code_continuation=seg.is_code_continuation,
                    is_table_continuation=seg.is_table_continuation,
                )
                chunks.append(chunk)
                global_chunk_idx += 1

        return chunks

    def _split_into_header_sections(self, content: str) -> List[Tuple[List[str], str]]:
        """Splits markdown text into (header_hierarchy, text_body) tuples."""
        lines = content.splitlines()
        sections: List[Tuple[List[str], str]] = []

        current_headers: List[str] = []
        current_body_lines: List[str] = []

        header_regex = re.compile(r"^(#{1,6})\s+(.+)$")
        in_code_block = False

        for line in lines:
            if line.strip().startswith("```"):
                in_code_block = not in_code_block

            m = header_regex.match(line)
            if m and not in_code_block:
                if current_body_lines:
                    sections.append((list(current_headers), "\n".join(current_body_lines)))
                    current_body_lines = []

                level = len(m.group(1))
                title = m.group(2).strip()

                while len(current_headers) >= level:
                    current_headers.pop()
                current_headers.append(title)
            else:
                current_body_lines.append(line)

            # Defensive reset of in_code_block on blank lines if somehow desynced
            if not line.strip() and in_code_block:
                pass

        if current_body_lines:
            sections.append((list(current_headers), "\n".join(current_body_lines)))

        return sections

    def _split_section_into_blocks(self, text: str) -> List[RawBlock]:
        """Separates section body into code blocks, tables, and prose paragraphs."""
        lines = text.splitlines()
        blocks: List[RawBlock] = []
        current_lines: List[str] = []
        in_code = False
        code_lang = ""

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 1. Code fence boundary
            if stripped.startswith("```"):
                if in_code:
                    current_lines.append(line)
                    blocks.append(RawBlock("code", "\n".join(current_lines), lang=code_lang))
                    current_lines = []
                    in_code = False
                    code_lang = ""
                    i += 1
                    continue
                else:
                    if current_lines:
                        p_text = "\n".join(current_lines).strip()
                        if p_text:
                            blocks.append(RawBlock("prose", p_text))
                        current_lines = []
                    code_lang = stripped[3:].strip()
                    in_code = True
                    current_lines.append(line)
                    i += 1
                    continue

            if in_code:
                current_lines.append(line)
                i += 1
                continue

            # 2. Check for Table start: line starts and ends with | (or has |) followed by separator
            is_table_start = False
            if "|" in stripped and stripped.startswith("|") and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if re.match(r"^\|(\s*:?-+:?\s*\|)+\s*$", next_line):
                    is_table_start = True

            if is_table_start:
                if current_lines:
                    p_text = "\n".join(current_lines).strip()
                    if p_text:
                        blocks.append(RawBlock("prose", p_text))
                    current_lines = []

                table_lines = [line, lines[i + 1]]
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|") and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                blocks.append(RawBlock("table", "\n".join(table_lines)))
                continue

            # 3. Regular paragraph lines
            if not stripped:
                if current_lines:
                    p_text = "\n".join(current_lines).strip()
                    if p_text:
                        blocks.append(RawBlock("prose", p_text))
                    current_lines = []
            else:
                current_lines.append(line)
            i += 1

        if in_code:
            current_lines.append("```")
            blocks.append(RawBlock("code", "\n".join(current_lines), lang=code_lang))
        elif current_lines:
            p_text = "\n".join(current_lines).strip()
            if p_text:
                blocks.append(RawBlock("prose", p_text))

        return blocks

    def _chunk_section(self, section_body: str) -> List[Segment]:
        """Process and pack section blocks, invoking recursive fallback for oversized blocks."""
        raw_blocks = self._split_section_into_blocks(section_body)
        if not raw_blocks:
            return []

        segments: List[Segment] = []
        cur_parts: List[str] = []
        cur_types: List[str] = []

        def flush_current():
            nonlocal cur_parts, cur_types
            if not cur_parts:
                return
            combined_text = "\n\n".join(cur_parts).strip()
            if is_header_only_or_empty(combined_text):
                cur_parts = []
                cur_types = []
                return
            dominant_type = cur_types[0] if len(set(cur_types)) == 1 else "mixed"
            combined_text = self.enforce_hard_limit(combined_text)
            segments.append(
                Segment(
                    content=combined_text,
                    content_type=dominant_type,  # type: ignore[arg-type]
                    is_code_continuation=False,
                    is_table_continuation=False,
                )
            )
            cur_parts = []
            cur_types = []

        for b in raw_blocks:
            b_tokens = self.count_tokens(b.content)
            if b_tokens <= self.max_tokens:
                cand_text = "\n\n".join(cur_parts + [b.content])
                if self.count_tokens(cand_text) <= self.max_tokens:
                    cur_parts.append(b.content)
                    cur_types.append(b.block_type)
                else:
                    flush_current()
                    cur_parts.append(b.content)
                    cur_types.append(b.block_type)
            else:
                # Oversized block: flush current accumulated content
                flush_current()
                if b.block_type == "code":
                    split_segs = self._split_oversized_code(b)
                elif b.block_type == "table":
                    split_segs = self._split_oversized_table(b)
                else:
                    split_segs = self._split_oversized_prose(b)

                for seg in split_segs:
                    if not is_header_only_or_empty(seg.content):
                        seg.content = self.enforce_hard_limit(seg.content)
                        segments.append(seg)

        flush_current()
        return segments

    def _split_oversized_code(self, block: RawBlock) -> List[Segment]:
        """Split oversized code block across safe line boundaries with language fence and continuation metadata."""
        lines = block.content.splitlines()
        open_fence = lines[0] if lines[0].startswith("```") else f"```{block.lang}"
        close_fence = "```"
        code_lines = lines[1:-1] if len(lines) >= 2 and lines[-1].strip().startswith("```") else lines[1:]

        segments: List[Segment] = []
        current_lines: List[str] = []
        first = True

        for line in code_lines:
            cand = open_fence + "\n" + "\n".join(current_lines + [line]) + "\n" + close_fence
            if self.count_tokens(cand) <= self.max_tokens:
                current_lines.append(line)
            else:
                if current_lines:
                    seg_text = open_fence + "\n" + "\n".join(current_lines) + "\n" + close_fence
                    segments.append(Segment(seg_text, "code", is_code_continuation=(not first)))
                    first = False
                    current_lines = []

                cand_single = open_fence + "\n" + line + "\n" + close_fence
                if self.count_tokens(cand_single) <= self.max_tokens:
                    current_lines.append(line)
                else:
                    # Single code line exceeds max_tokens; token slice
                    tok_ids = self.tokenizer.encode(line, add_special_tokens=False)
                    overhead = self.count_tokens(open_fence + "\n\n" + close_fence) + 4
                    slice_sz = max(10, self.max_tokens - overhead)
                    for s in range(0, len(tok_ids), slice_sz):
                        sub_text = self.tokenizer.decode(tok_ids[s : s + slice_sz], skip_special_tokens=True)
                        seg_text = open_fence + "\n" + sub_text + "\n" + close_fence
                        seg_text = self.enforce_hard_limit(seg_text)
                        segments.append(Segment(seg_text, "code", is_code_continuation=(not first)))
                        first = False

        if current_lines:
            seg_text = open_fence + "\n" + "\n".join(current_lines) + "\n" + close_fence
            segments.append(Segment(seg_text, "code", is_code_continuation=(not first)))

        return segments

    def _split_oversized_table(self, block: RawBlock) -> List[Segment]:
        """Split oversized table across row boundaries, preserving table header on each segment."""
        lines = block.content.splitlines()
        header_lines = "\n".join(lines[:2]) if len(lines) >= 2 else lines[0]
        data_rows = lines[2:] if len(lines) >= 2 else []

        header_tok = self.count_tokens(header_lines)
        if header_tok >= self.max_tokens - 20:
            segments: List[Segment] = []
            cur: List[str] = []
            first = True
            for l in lines:
                cand = "\n".join(cur + [l])
                if self.count_tokens(cand) <= self.max_tokens:
                    cur.append(l)
                else:
                    if cur:
                        segments.append(Segment("\n".join(cur), "table", is_table_continuation=(not first)))
                        first = False
                        cur = []
                    cur.append(self.enforce_hard_limit(l))
            if cur:
                segments.append(Segment("\n".join(cur), "table", is_table_continuation=(not first)))
            return segments

        segments = []
        current_rows: List[str] = []
        first = True

        for row in data_rows:
            cand = header_lines + "\n" + "\n".join(current_rows + [row])
            if self.count_tokens(cand) <= self.max_tokens:
                current_rows.append(row)
            else:
                if current_rows:
                    seg_text = header_lines + "\n" + "\n".join(current_rows)
                    segments.append(Segment(seg_text, "table", is_table_continuation=(not first)))
                    first = False
                    current_rows = []

                cand_single = header_lines + "\n" + row
                if self.count_tokens(cand_single) <= self.max_tokens:
                    current_rows.append(row)
                else:
                    # Single row exceeds max_tokens; token slice row
                    tok_ids = self.tokenizer.encode(row, add_special_tokens=False)
                    slice_sz = max(10, self.max_tokens - header_tok - 6)
                    for s in range(0, len(tok_ids), slice_sz):
                        sub_row = self.tokenizer.decode(tok_ids[s : s + slice_sz], skip_special_tokens=True)
                        seg_text = header_lines + "\n" + sub_row
                        seg_text = self.enforce_hard_limit(seg_text)
                        segments.append(Segment(seg_text, "table", is_table_continuation=(not first)))
                        first = False

        if current_rows:
            seg_text = header_lines + "\n" + "\n".join(current_rows)
            segments.append(Segment(seg_text, "table", is_table_continuation=(not first)))

        return segments

    def _split_oversized_prose(self, block: RawBlock) -> List[Segment]:
        """Split oversized prose paragraph by sentences, sub-clauses, and word/token boundaries."""
        sentences = re.split(r"(?<=[.!?])\s+", block.content)
        segments: List[Segment] = []
        cur_sents: List[str] = []

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            cand = " ".join(cur_sents + [sent])
            if self.count_tokens(cand) <= self.max_tokens:
                cur_sents.append(sent)
            else:
                if cur_sents:
                    segments.append(Segment(" ".join(cur_sents), "prose"))
                    cur_sents = []

                if self.count_tokens(sent) <= self.max_tokens:
                    cur_sents.append(sent)
                else:
                    # Single sentence exceeds max_tokens: split by words
                    words = sent.split()
                    cur_words: List[str] = []
                    for w in words:
                        cand_w = " ".join(cur_words + [w])
                        if self.count_tokens(cand_w) <= self.max_tokens:
                            cur_words.append(w)
                        else:
                            if cur_words:
                                segments.append(Segment(" ".join(cur_words), "prose"))
                                cur_words = []
                            if self.count_tokens(w) <= self.max_tokens:
                                cur_words.append(w)
                            else:
                                # Single giant string (e.g. 5000 character token)
                                tok_ids = self.tokenizer.encode(w, add_special_tokens=False)
                                for s in range(0, len(tok_ids), self.max_tokens):
                                    sub_w = self.tokenizer.decode(
                                        tok_ids[s : s + self.max_tokens], skip_special_tokens=True
                                    )
                                    segments.append(Segment(sub_w, "prose"))
                    if cur_words:
                        segments.append(Segment(" ".join(cur_words), "prose"))

        if cur_sents:
            segments.append(Segment(" ".join(cur_sents), "prose"))

        return segments

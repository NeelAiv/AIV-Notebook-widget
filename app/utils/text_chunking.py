"""Shared text chunking and RAG context formatting for document indexing and retrieval."""
from __future__ import annotations

import re
from typing import Any

DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_MAX_CHUNKS = 500
DEFAULT_PREVIEW_CHARS = 20_000
DEFAULT_RAG_CHUNK_CHARS = 800
DEFAULT_RAG_TOTAL_CHARS = 8_000


def chunk_text_for_rag(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[str]:
    """
    Split document text into overlapping chunks suitable for embedding.
    Prefers paragraph boundaries; splits long paragraphs by sentence/word.
    """
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [ln.strip() for ln in text.splitlines() if ln.strip()]

    merged: list[str] = []
    buf = ""
    merge_target = max(200, chunk_size // 2)
    for para in paragraphs:
        if len(buf) + len(para) + 2 <= merge_target:
            buf = f"{buf}\n\n{para}".strip() if buf else para
        else:
            if buf:
                merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)

    raw_chunks: list[str] = []
    for para in merged:
        if len(para) <= chunk_size:
            raw_chunks.append(para)
        else:
            raw_chunks.extend(_split_long_text(para, chunk_size))

    if overlap > 0 and len(raw_chunks) > 1:
        raw_chunks = _apply_tail_overlap(raw_chunks, overlap)

    return raw_chunks[:max_chunks]


def _split_long_text(text: str, chunk_size: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_by_words(sent, chunk_size))
            continue
        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = sent
    if current:
        chunks.append(current.strip())
    return chunks


def _split_by_words(text: str, chunk_size: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        wlen = len(word) + (1 if current else 0)
        if length + wlen > chunk_size and current:
            chunks.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += wlen
    if current:
        chunks.append(" ".join(current))
    return chunks


def _apply_tail_overlap(chunks: list[str], overlap_chars: int) -> list[str]:
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            out.append(chunk)
            continue
        prev = chunks[i - 1]
        tail = prev[-overlap_chars:].strip() if len(prev) > overlap_chars else prev.strip()
        if tail and tail not in chunk[: len(tail) + 10]:
            chunk = f"{tail}\n\n{chunk}"
        out.append(chunk)
    return out


def dedupe_retrieved(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in retrieved:
        src = row.get("source_name", "")
        txt = (row.get("chunk_text") or "").strip()
        key = (src, txt[:240])
        if not txt or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def format_rag_excerpts(
    retrieved: list[dict[str, Any]],
    *,
    max_chunk_chars: int = DEFAULT_RAG_CHUNK_CHARS,
    max_total_chars: int = DEFAULT_RAG_TOTAL_CHARS,
) -> str:
    lines: list[str] = []
    total = 0
    for row in retrieved:
        src = row.get("source_name", "unknown")
        txt = (row.get("chunk_text") or "").strip()
        if not txt:
            continue
        if len(txt) > max_chunk_chars:
            txt = txt[:max_chunk_chars].rsplit(" ", 1)[0] + "..."
        line = f"[{src}]: {txt}"
        if total + len(line) > max_total_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)

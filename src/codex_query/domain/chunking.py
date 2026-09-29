from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator

from .models import Chapter, TextChunk

_WORD_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize whitespace in a string by collapsing multiple spaces into a single
    space.

    Args:
        text: The raw string to normalize.

    Returns:
        The string with normalized whitespace and leading/trailing spaces removed.
    """
    return _WORD_RE.sub(" ", text).strip()


def chunk_chapter(
    chapter: Chapter,
    *,
    series: str,
    book_title: str,
    max_chars: int = 1800,
    overlap: int = 250,
) -> Iterator[TextChunk]:
    """Split a book chapter into smaller, overlapping text chunks.

    Normalizes the chapter text and slices it into segments up to `max_chars` long,
    attempting to split at word boundaries. Generates a deterministic hash-based
    chunk ID and builds metadata for each produced chunk.

    Args:
        chapter: The chapter object containing text, book ID, href, title, and order.
        series: The name of the series the book belongs to.
        book_title: The title of the book.
        max_chars: The maximum character length for any single chunk. Defaults to 1800.
        overlap: The number of characters to overlap between consecutive chunks.
        Defaults to 250.

    Yields:
        TextChunk: Objects containing the chunked text, unique ID, index, and metadata.
    """
    text = normalize_text(chapter.text)
    if not text:
        return
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + max_chars // 2:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            digest = hashlib.sha256(
                f"{chapter.book_id}:{chapter.href}:{index}:{piece}".encode()
            ).hexdigest()[:24]
            yield TextChunk(
                chunk_id=f"{chapter.book_id}:{chapter.href}:{index}:{digest}",
                book_id=chapter.book_id,
                chapter_href=chapter.href,
                series=series,
                book_title=book_title,
                chapter_title=chapter.title,
                chunk_index=index,
                text=piece,
                metadata={
                    "series": series,
                    "book_id": chapter.book_id,
                    "book_title": book_title,
                    "chapter_href": chapter.href,
                    "chapter_title": chapter.title,
                    "chapter_order": chapter.order,
                    "chunk_index": index,
                },
            )
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
        index += 1

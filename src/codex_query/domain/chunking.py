from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator

from .models import Chapter, TextChunk

# Compile regex pattern to match one or more whitespace characters
_WORD_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize whitespace in a string by collapsing multiple spaces into a single
    space.

    Args:
        text: The raw string to normalize.

    Returns:
        The string with normalized whitespace and leading/trailing spaces removed.
    """
    # Replace whitespace sequences with a single space and strip edges
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
    # Clean up whitespace in the raw chapter text
    text = normalize_text(chapter.text)

    # Return early if chapter text is empty after normalization
    if not text:
        return

    # Initialize tracking variables for iteration window
    start = 0
    index = 0

    # Iterate through text to create chunks until reaching the end
    while start < len(text):
        # Calculate maximum possible end index for current chunk
        end = min(len(text), start + max_chars)

        # If not at text end, look for a word boundary to prevent cutting words
        if end < len(text):
            # Locate the last space within the chunk window
            boundary = text.rfind(" ", start, end)

            # Adjust end position if a space exists past the halfway threshold
            if boundary > start + max_chars // 2:
                end = boundary

        # Extract segment and strip surrounding whitespace
        piece = text[start:end].strip()

        # Build chunk payload if segment contains text
        if piece:
            # Generate deterministic short hash from chunk identity attributes
            digest = hashlib.sha256(
                f"{chapter.book_id}:{chapter.href}:{index}:{piece}".encode()
            ).hexdigest()[:24]

            # Yield current chunk object with metadata
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

        # Stop iteration if end of text has been processed
        if end >= len(text):
            break

        # Shift start pointer backward by overlap amount for next window
        start = max(start + 1, end - overlap)

        # Increment chunk counter
        index += 1

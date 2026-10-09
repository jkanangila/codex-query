from __future__ import annotations

import re
from collections.abc import Iterator
from typing import override

from codex_query.application.ports.indexing import TextChunksPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.errors import MissingBookIDError, MissingChapterIDError
from codex_query.domain.models.document import Chapter, TextChunk, TextChunkMetadata

_WHITESPACE_RE = re.compile(r"\s+")


class TextChunkService(TextChunksPort):
    def __init__(self, logger_factory: LoggerFactoryPort) -> None:
        """Initialize the text chunk service with a logger.

        Args:
            logger_factory: Factory port used to construct the class logger instance.
        """
        self._logger = logger_factory.create(__name__)

    @override
    def split(
        self,
        chapter: Chapter,
        series: str | None,
        book_title: str,
        max_chars: int = 1800,
        overlap: int = 250,
    ) -> Iterator[TextChunk]:
        """Split a chapter into smaller, overlapping text chunks.

        Chunks are deterministic: the generated chunk ID is based on the
        chapter identity, chunk index, and chunk content.

        Args:
            chapter: Chapter object containing metadata and raw content to split.
            series: Optional series title containing the book.
            book_title: Title of the book containing the chapter.
            max_chars: Maximum character length for an individual chunk. Must be
                strictly positive.
            overlap: Number of characters shared between consecutive chunks. Must be
                non-negative and strictly smaller than max_chars.

        Yields:
            TextChunk objects representing segments of the chapter text.

        Raises:
            MissingChapterIDError: If the chapter lacks a valid ID.
            MissingBookIDError: If the chapter lacks a valid book_id.
            ValueError: If chapter content is None, or if max_chars/overlap options
                are invalid.
        """
        if chapter.id is None:
            self._logger.error("Failed to split chapter: Missing chapter ID")
            raise MissingChapterIDError("Chapter ID cannot be None")

        if chapter.book_id is None:
            self._logger.error(
                "Failed to split chapter %s: Missing book_id", chapter.id
            )
            raise MissingBookIDError("Chapter is missing the value book_id")

        if chapter.content is None:
            self._logger.error(
                "Failed to split chapter %s: Content is None", chapter.id
            )
            raise ValueError("Tried to call split on a chapter with no content")

        if max_chars <= 0:
            self._logger.error(
                "Invalid max_chars parameter: %d (must be > 0)", max_chars
            )
            raise ValueError("max_chars must be greater than 0")

        if overlap < 0:
            self._logger.error("Invalid overlap parameter: %d (must be >= 0)", overlap)
            raise ValueError("overlap must be greater than or equal to 0")

        if overlap >= max_chars:
            self._logger.error(
                "Invalid overlap parameter: %d must be smaller than max_chars (%d)",
                overlap,
                max_chars,
            )
            raise ValueError("overlap must be smaller than max_chars")

        self._logger.debug(
            "Splitting chapter ID %s (book_id: %s, max_chars: %d, overlap: %d)",
            chapter.id,
            chapter.book_id,
            max_chars,
            overlap,
        )

        text = normalize_text(chapter.content)

        if not text:
            self._logger.warning(
                "Chapter %s contains only empty or whitespace content", chapter.id
            )
            return

        start = 0
        index = 0

        while start < len(text):
            end = min(len(text), start + max_chars)

            # Prefer a word boundary when doing so does not make the chunk
            # excessively short.
            if end < len(text):
                boundary = text.rfind(" ", start, end)

                if boundary > start + max_chars // 2:
                    end = boundary

            piece = text[start:end].strip()

            if piece:
                yield TextChunk(
                    id=None,
                    chapter_id=chapter.id,
                    series=series,
                    book_title=book_title,
                    chapter_title=chapter.title,
                    chunk_index=index,
                    text=piece,
                    meta=TextChunkMetadata(
                        series=series,
                        book_id=chapter.book_id,
                        book_title=book_title,
                        chapter_href=chapter.href,
                        chapter_title=chapter.title,
                        chapter_order=chapter.order,
                        chunk_index=index,
                    ),
                )

            if end >= len(text):
                break

            start = max(start + 1, end - overlap)
            index += 1

        self._logger.info(
            "Successfully split chapter %s into %d chunk(s)",
            chapter.id,
            index + 1,
        )

    @override
    def combine(self, chunks: Iterator[TextChunk], overlap: int = 250) -> str:
        """Reconstruct a chapter from previously generated text chunks.

        The chunks are ordered by ``chunk_index`` and their overlapping portions
        are removed while reconstructing the original chapter text.

        This function expects chunks belonging to a single chapter.

        Args:
            chunks: Iterator yielding TextChunk instances belonging to one chapter.
            overlap: Maximum expected overlap between adjacent chunks. Must be
                non-negative.

        Returns:
            The fully reconstructed chapter text as a single string.

        Raises:
            ValueError: If overlap is negative, no chunks are provided, chunk indices
                are non-contiguous or do not start at 0, or chunks originate from
                different chapters.
        """
        if overlap < 0:
            self._logger.error("Invalid overlap parameter: %d (must be >= 0)", overlap)
            raise ValueError("overlap must be greater than or equal to 0")

        ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)

        if not ordered:
            self._logger.error("Failed to reconstruct chapter: No chunks were supplied")
            raise ValueError("Cannot reconstruct a chapter from no chunks")

        first = ordered[0]

        expected_indices = range(len(ordered))
        actual_indices = [chunk.chunk_index for chunk in ordered]

        if actual_indices != list(expected_indices):
            self._logger.error(
                "Non-contiguous chunk sequence detected: expected %r, got %r",
                list(expected_indices),
                actual_indices,
            )
            raise ValueError(
                "Chunk indices must be contiguous and start at 0; "
                f"got {actual_indices!r}"
            )

        chapter_identity = (first.meta.book_id, first.meta.chapter_href)

        for chunk in ordered[1:]:
            current_identity = (chunk.meta.book_id, chunk.meta.chapter_href)
            if current_identity != chapter_identity:
                self._logger.error(
                    "Mismatched chapter identity in chunks: expected %r, got %r",
                    chapter_identity,
                    current_identity,
                )
                raise ValueError(
                    "All chunks must belong to the same chapter: "
                    f"expected {chapter_identity!r}, "
                    f"got {current_identity!r}"
                )

        self._logger.debug(
            "Combining %d chunks for chapter (book_id: %s, href: %s)",
            len(ordered),
            first.meta.book_id,
            first.meta.chapter_href,
        )

        reconstructed = first.text

        for chunk in ordered[1:]:
            reconstructed = _append_chunk(
                reconstructed,
                chunk.text,
                max_overlap=overlap,
            )

        self._logger.info(
            "Successfully combined %d chunks into %d characters",
            len(ordered),
            len(reconstructed),
        )

        return reconstructed


def normalize_text(text: str) -> str:
    """Normalize whitespace in a string.

    Collapses every whitespace sequence into a single space and removes
    leading/trailing whitespace.

    Args:
        text: The raw string to normalize.

    Returns:
        The normalized text with single-space whitespace separation.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def _append_chunk(
    current: str,
    chunk: str,
    *,
    max_overlap: int,
) -> str:
    """Append a chunk to existing text while deduplicating overlapping regions.

    Args:
        current: Cumulative text assembled so far.
        chunk: Incoming chunk text to merge.
        max_overlap: Upper bound for character length check on duplicate regions.

    Returns:
        The combined string with duplicated overlapping boundaries removed.
    """
    if not current:
        return chunk

    if not chunk:
        return current

    max_possible = min(
        len(current),
        len(chunk),
        max_overlap,
    )

    # Look for the largest suffix/prefix match.
    for size in range(max_possible, 0, -1):
        if current[-size:] == chunk[:size]:
            return current + chunk[size:]

    # No overlap found.
    return current + chunk

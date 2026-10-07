from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import override

from codex_query.application.ports.interfaces import (
    IBookReader,
    IEmbeddingModel,
    IGenerator,
    ILedger,
    IQueryService,
    IVectorStore,
)
from codex_query.domain.chunking import chunk_chapter
from codex_query.domain.models.document import Answer, Book, Chapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    phase: str
    message: str
    current: int = 0
    total: int = 0
    unit: str = "items"

    @property
    def percent(self) -> float:
        return (self.current / self.total * 100.0) if self.total else 0.0


Progress = Callable[[ProgressEvent], None]


@dataclass(frozen=True, slots=True)
class IndexSummary:
    """Summary metrics returned after running an indexing operation on a series.

    Attributes:
        series: Name or ID of the book series.
        books_seen: Total number of EPUB files discovered and processed.
        chapters_indexed: Number of chapters successfully chunked and vector indexed.
        chapters_skipped: Number of chapters skipped because they were already up to
        date.
        failures: Total count of chapter- or book-level errors encountered.
    """

    series: str
    books_seen: int
    chapters_indexed: int
    chapters_skipped: int
    failures: int
    chapters_removed: int = 0
    chunks_indexed: int = 0


class IndexService:
    """Service responsible for parsing, chunking, and vector-indexing ebook series."""

    def __init__(
        self,
        reader: IBookReader,
        ledger: ILedger,
        vectors: IVectorStore,
        embeddings: IEmbeddingModel,
        *,
        chunk_chars: int = 1800,
        chunk_overlap: int = 250,
        batch_size: int = 8,
    ) -> None:
        """Initialize the indexing service with required storage and processing ports.

        Args:
            reader: Adapter used to read and parse EPUB files.
            ledger: Adapter used to track indexing status and content state.
            vectors: Vector store interface for persisting and deleting embeddings.
            embeddings: Embedding model interface for generating vector representations.
            chunk_chars: Maximum character length per text chunk. Defaults to 1800.
            chunk_overlap: Overlap length in characters between adjacent chunks.
            Defaults to 250.
            batch_size: Number of text chunks to embed and upsert in a single batch.
            Defaults to 8.
        """
        # Store references to infrastructure adapters
        self._reader, self._ledger, self._vectors, self._embeddings = (
            reader,
            ledger,
            vectors,
            embeddings,
        )
        # Store chunking and batching parameters
        self._chunk_chars, self._chunk_overlap, self._batch_size = (
            chunk_chars,
            chunk_overlap,
            batch_size,
        )

    def index_series(
        self, series: str, root: Path, progress: Progress | None = None
    ) -> IndexSummary:
        books = sorted(root.rglob("*.epub"))
        indexed = skipped = failures = removed = chunks_indexed = 0
        self._emit(
            progress,
            "discover",
            f"Found {len(books)} EPUB books",
            0,
            len(books),
            "books",
        )
        logger.info(
            "Starting indexing: series=%r root=%s books=%d", series, root, len(books)
        )

        for book_no, path in enumerate(books, 1):
            self._emit(
                progress, "book", f"Reading {path.name}", book_no, len(books), "books"
            )
            logger.info("Book %d/%d: %s", book_no, len(books), path)
            try:
                book = self._reader.read(path)
                self._ledger.register_book(book, series)
                stale = self._ledger.remove_stale_chapters(
                    book.book_id, {c.href for c in book.chapters}
                )
                for href in stale:
                    logger.info(
                        "Removing stale chapter: book=%s chapter=%s", book.book_id, href
                    )
                    self._vectors.delete_chapter(series, book.book_id, href)
                removed += len(stale)
                pending = self._ledger.chapters_to_index(book.book_id, book.chapters)
                skipped += len(book.chapters) - len(pending)
                logger.info(
                    "Book %s: chapters=%d pending=%d skipped=%d removed=%d",
                    book.title,
                    len(book.chapters),
                    len(pending),
                    len(book.chapters) - len(pending),
                    len(stale),
                )
                for chapter_no, chapter in enumerate(pending, 1):
                    try:
                        self._emit(
                            progress,
                            "chapter",
                            f"Indexing {chapter.title}",
                            chapter_no,
                            len(pending),
                            "chapters",
                        )
                        chapter_chunks = self._index_chapter(
                            series, book, chapter, progress
                        )
                        self._ledger.mark_chapter_indexed(
                            book.book_id, chapter.href, chapter.content_hash
                        )
                        indexed += 1
                        chunks_indexed += chapter_chunks
                        logger.info(
                            "Indexed chapter: %s / %s chunks=%d",
                            book.title,
                            chapter.title,
                            chapter_chunks,
                        )
                    except Exception as exc:
                        self._ledger.mark_chapter_failed(
                            book.book_id, chapter.href, str(exc)
                        )
                        failures += 1
                        logger.exception(
                            "Failed chapter: book=%s chapter=%s",
                            book.title,
                            chapter.title,
                        )
            except Exception:
                failures += 1
                logger.exception("Failed book: %s", path)

        summary = IndexSummary(
            series, len(books), indexed, skipped, failures, removed, chunks_indexed
        )
        self._emit(
            progress,
            "complete",
            f"Indexing complete: {indexed} chapters",
            len(books),
            len(books),
            "books",
        )
        logger.info("Indexing complete: %s", summary)
        return summary

    def _index_chapter(
        self, series: str, book: Book, chapter: Chapter, progress: Progress | None
    ) -> int:
        self._vectors.delete_chapter(series, book.book_id, chapter.href)
        chunks = list(
            chunk_chapter(
                chapter,
                series=series,
                book_title=book.title,
                max_chars=self._chunk_chars,
                overlap=self._chunk_overlap,
            )
        )
        total = len(chunks)
        logger.debug("Chapter %s produced %d chunks", chapter.title, total)
        for offset in range(0, total, self._batch_size):
            batch = chunks[offset : offset + self._batch_size]
            batch_no = offset // self._batch_size + 1
            batch_total = (total + self._batch_size - 1) // self._batch_size
            self._emit(
                progress,
                "embed",
                f"Embedding {chapter.title}: batch {batch_no}/{batch_total}",
                batch_no,
                batch_total,
                "batches",
            )
            logger.debug(
                "Embedding batch %d/%d: chapter=%s chunks=%d",
                batch_no,
                batch_total,
                chapter.title,
                len(batch),
            )
            vectors = self._embeddings.embed([chunk.text for chunk in batch])
            self._vectors.upsert(series, batch, vectors)
            self._emit(
                progress,
                "persist",
                f"Stored {min(offset + len(batch), total)}/{total} chunks",
                min(offset + len(batch), total),
                total,
                "chunks",
            )
        return total

    @staticmethod
    def _emit(
        progress: Progress | None,
        phase: str,
        message: str,
        current: int,
        total: int,
        unit: str,
    ) -> None:
        event = ProgressEvent(
            phase=phase, message=message, current=current, total=total, unit=unit
        )
        if progress:
            progress(event)


class QueryServiceImpl(IQueryService):
    def __init__(
        self,
        embeddings: IEmbeddingModel,
        vectors: IVectorStore,
        generator: IGenerator,
        progress: Progress | None = None,
    ) -> None:
        self._embeddings, self._vectors, self._generator, self._progress = (
            embeddings,
            vectors,
            generator,
            progress,
        )

    @override
    def ask(self, series: str, question: str, limit: int = 6) -> Answer:
        logger.info(
            "Query started: series=%r limit=%d question=%r", series, limit, question
        )
        if self._progress:
            self._progress(ProgressEvent("query", "Embedding question", 1, 3, "steps"))
        embedding = self._embeddings.embed([question])[0]
        if self._progress:
            self._progress(
                ProgressEvent(
                    "retrieve", f"Retrieving top {limit} passages", 2, 3, "steps"
                )
            )
        hits = self._vectors.search(series, embedding, limit)
        logger.info("Retrieved %d passages", len(hits))
        if self._progress:
            self._progress(
                ProgressEvent("generate", "Generating answer", 3, 3, "steps")
            )
        answer = self._generator.answer(question, hits)
        logger.info(
            "Query complete: sources=%d answer_chars=%d", len(hits), len(answer)
        )
        return Answer(question, answer, tuple(hits))

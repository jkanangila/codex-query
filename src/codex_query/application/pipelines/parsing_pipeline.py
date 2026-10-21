import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace

from codex_query.application.ports.indexing import (
    DocumentParserPort,
    TextChunksPort,
)
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from codex_query.application.services.settings_service import SettingsService
from codex_query.domain.models.document import (
    Book,
    BookUpdate,
    Chapter,
    TextChunk,
)
from codex_query.domain.models.job import IndexingJob, Stage
from codex_query.domain.value_objects import Progress, QueueIndexJobRequest


class ParsePersistPipeline:
    """Parse a book file and persist its chapters and chunks atomically.

    The job comes from ``QueueIndexJob`` with a fresh UUID4 and ``book_id == -1``.
    The -1 is a placeholder: the book has no database row until this pipeline
    registers it. The job is returned with the real ``book_id`` and ``total``
    (the number of chunks in the whole book) filled in.

    The book may already be in the database. What happens then depends on what
    differs between the stored book and the file/settings we were just given:

    - File hash differs (e.g. a web novel gained chapters): only new or edited
      chapters are chunked; unchanged chapters and their chunks are kept.
      Chapters (matched by order) that are no longer in the file are deleted
      together with their chunks.
    - Chunk size or overlap differs: every chapter is re-chunked, because the
      stored chunks *are* the output of those settings.
    - Embedding model or provider differs: chapters and chunks are kept as they
      are and only the vectors are dropped, so the embed stage starts clean.
    - Nothing differs: nothing is re-chunked.

    Vectors are removed here, in step with the chunks they belong to, so the
    embed stage only has to embed chunks that have no vector yet. Edited and
    removed chapters lose only their own vectors; untouched chapters keep theirs.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        read_uow_factory: UnitOfWorkFactory,
        parser: DocumentParserPort,
        chunker: TextChunksPort,
        settings_service: SettingsService,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._read_uow_factory = read_uow_factory
        self._parser = parser
        self._chunker = chunker
        # Keep the service, not a snapshot: settings are a live view, and the
        # drift checks below are meaningless if we compare against stale values.
        self._settings_service = settings_service
        self._logger = logger_factory.create(__name__)

    async def __call__(
        self, job: IndexingJob, request: QueueIndexJobRequest
    ) -> AsyncIterator[tuple[Progress, IndexingJob]]:
        settings = self._settings_service.current

        self._logger.info(
            "Starting parsing pipeline for book title '%s' from source: %s",
            request.title,
            request.source,
        )
        yield (Progress(Stage.PARSE, 0, 0, 0, None), job)
        try:
            parsed_book = await self._parser.read(
                path=request.source,
                title=request.title,
                series=request.series,
                number=request.number,
                request=request,
            )
        except Exception:
            self._logger.exception(
                "Failed to parse source file for '%s'", request.title
            )
            raise
        chapters = parsed_book.chapters
        self._logger.debug(
            "Successfully parsed book. Found %d chapters.", len(chapters)
        )

        book = replace(
            parsed_book.book,
            meta=replace(
                parsed_book.book.meta,
                embedding_model=settings.embedding.model,
                embedding_provider=settings.embedding.provider,
                chunk_size=settings.chunk_size,
            ),
        )

        # Yield before opening the transaction: a suspended generator would
        # otherwise sit on the write lock while the consumer handles the event.
        yield (Progress(Stage.CHUNK, 0, 0, 0, None), job)

        # All writes happen in a single transaction so they are atomic.
        async with self._uow_factory() as uow:
            book_id, chunks_count = await self._persist(uow, book, chapters)
            indexing_job = await uow.jobs.add(
                replace(job, book_id=book_id, total=chunks_count)
            )
            await uow.commit()
        yield (Progress(Stage.EMBED, 0, chunks_count, 0, None), indexing_job)

    async def _persist(
        self, uow: UnitOfWork, book: Book, chapters: Sequence[Chapter]
    ) -> tuple[int, int]:
        """Register or update the book, (re)chunk what is stale, return counts.

        Returns:
            ``(book_id, total_chunks_in_book)``
        """
        existing = await uow.books.get_by_path(book.path)

        known_hashes: Mapping[int, str] = {}
        rechunk_all = False
        embeddings_stale = False

        if existing is None:
            book_id = await uow.books.register_book(book)
            file_changed = True
            self._logger.debug("Registered new book with ID %d", book_id)
        else:
            assert existing.id is not None
            book_id = existing.id
            file_changed = existing.file_hash != book.file_hash
            old, new = existing.meta, book.meta
            rechunk_all = (old.chunk_size, old.chunk_overlap) != (
                new.chunk_size,
                new.chunk_overlap,
            )
            embeddings_stale = (old.embedding_model, old.embedding_provider) != (
                new.embedding_model,
                new.embedding_provider,
            )
            self._logger.info(
                "Book ID %d already exists (file_changed=%s, rechunk_all=%s, "
                "embeddings_stale=%s)",
                book_id,
                file_changed,
                rechunk_all,
                embeddings_stale,
            )

        # When every vector is going away anyway there is no need to track which
        # individual chunks were removed.
        wipe_vectors = embeddings_stale or rechunk_all
        stale_chunk_ids: list[int] = []

        if file_changed or rechunk_all:
            if existing is not None:
                known_hashes = await uow.chapters.get_hashes_for_book(book_id)
                removed = sorted(known_hashes.keys() - {c.order for c in chapters})
                if removed:
                    self._logger.info(
                        "Removing %d chapter(s) no longer in the file", len(removed)
                    )
                    if not wipe_vectors:
                        stale_chunk_ids += await uow.chunks.get_ids_for_orders(
                            book_id, removed
                        )
                    # Chunks go with their chapter (ON DELETE CASCADE).
                    await uow.chapters.delete_by_order(book_id, removed)

            # Diff against the stored hashes *before* upserting: the upsert
            # overwrites content_hash.
            chapter_ids = await uow.chapters.upsert_bulk(book_id, chapters)

            for chapter_id, chapter in zip(chapter_ids, chapters, strict=True):
                unchanged = known_hashes.get(chapter.order) == chapter.content_hash
                if unchanged and not rechunk_all:
                    continue
                if chapter.order in known_hashes:
                    # Remember the ids first: SQLite reuses the ids of deleted
                    # rows, so a leftover vector could end up on a different chunk.
                    if not wipe_vectors:
                        stale_chunk_ids += await uow.chunks.get_ids_for_chapter(
                            chapter_id
                        )
                    # upsert_for_chapter never removes trailing chunks, so clear
                    # the old ones when an existing chapter is chunked again.
                    await uow.chunks.delete_for_chapter(chapter_id)
                chunks = await asyncio.to_thread(
                    _split_all, self._chunker, replace(chapter, id=chapter_id), book
                )
                await uow.chunks.upsert_for_chapter(chapter_id, chunks)

        chunks_count = await uow.chunks.count_for_book(book_id)
        self._logger.debug("Book ID %d now has %d chunks", book_id, chunks_count)

        await uow.books.update(
            book_id,
            BookUpdate(
                file_hash=book.file_hash,
                size=book.size,
                modified_ns=book.modified_ns,
                meta=replace(book.meta, chunks=chunks_count),
            ),
        )

        # Vectors must never outlive the model or chunks they were built from.
        # Done last: it is not transactional on every backend (e.g. Chroma).
        if wipe_vectors:
            await uow.vectors.delete_book(book_id)
        elif stale_chunk_ids:
            await uow.vectors.delete_chunks(book_id, stale_chunk_ids)

        return book_id, chunks_count


def _split_all(
    chunker: TextChunksPort, chapter: Chapter, book: Book
) -> list[TextChunk]:
    """Run the chunker to completion.

    ``split`` returns a generator, so the real work happens while iterating.
    The ``list()`` has to run here, inside the worker thread; calling
    ``to_thread(chunker.split, ...)`` alone only builds the generator and the
    splitting would then run on the event loop.
    """
    return list(
        chunker.split(
            chapter=chapter,
            series=book.series,
            book_title=book.title,
            max_chars=book.meta.chunk_size,
            overlap=book.meta.chunk_overlap,
        )
    )

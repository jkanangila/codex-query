import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.services.settings_service import SettingsService
from codex_query.application.services.test_connection_service import EmbeddingFactory
from codex_query.domain.errors import (
    CheckpointMismatchError,
    EmbeddingCountError,
    EmbeddingMismatchError,
)
from codex_query.domain.models.job import IndexingJob, Stage
from codex_query.domain.value_objects import Progress


@dataclass(frozen=True, slots=True)
class DatasetSize:
    small: int = 10000
    medium: int = 100000
    large: int = 1000000

    def get_batch_size(self, total: int) -> int:
        if total <= 0:
            return 0

        # Determine percentage dynamically based on scale
        if total <= self.small:
            batch = int(total * 0.01)  # 1% for small datasets
        elif total <= self.medium:
            batch = int(total * 0.005)  # 0.5% for medium datasets
        else:
            batch = int(total * 0.001)  # 0.1% or lower for massive datasets

        # Enforce hard boundaries to prevent API or DB crashes (e.g., max 500)
        return max(1, min(batch, 100))


DATA_SIZE = DatasetSize()


class IndexingPipeline:
    """Embed every chunk of a book that does not have a vector yet.

    The vector store is the source of truth for what is already embedded, so
    the same code covers a first run, a resume after a pause or crash, and an
    incremental update where only some chunks are new. ``job.checkpoint`` is
    reported for the UI but is not needed to resume.

    Anything that invalidates vectors (a different embedding model, re-chunked
    chapters) must delete them first; ``ParsePersistPipeline`` does that. To force
    a full re-embed, call ``uow.vectors.delete_book`` before running the job.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        read_uow_factory: UnitOfWorkFactory,
        embedding_factory: EmbeddingFactory,
        settings_service: SettingsService,
        logger_factory: LoggerFactoryPort,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._uow_factory = uow_factory
        self._read_uow_factory = read_uow_factory
        self._logger = logger_factory.create(__name__)
        self._clock = clock
        # Keep the factory and the service, not an embedder built from a settings
        # snapshot: this pipeline lives as long as the app, and the embedding
        # settings can change underneath it.
        self._embedding_factory = embedding_factory
        self._settings_service = settings_service

    async def __call__(self, job: IndexingJob) -> AsyncIterator[Progress]:
        async with self._read_uow_factory() as uow:
            book = await uow.books.get_by_id(job.book_id)
            assert book is not None
            model = book.meta.embedding_model
            provider = book.meta.embedding_provider
            if model is None or provider is None:
                raise EmbeddingMismatchError(
                    f"Book {job.book_id} has no recorded embedding model; re-index it."
                )
            total = await uow.chunks.count_for_book(job.book_id)
            embedded = await uow.vectors.embedded_chunk_ids(job.book_id)

        # Vectors are labelled with the book's model, so they must really come
        # from it. If the settings moved on since the book was set up (a paused
        # job outliving a settings change), embedding now would mislabel them.
        configured = self._settings_service.current.embedding
        if (str(configured.provider).lower(), configured.model.lower()) != (
            provider.lower(),
            model.lower(),
        ):
            raise EmbeddingMismatchError(
                f"Book {job.book_id} was set up for {provider}/{model} but the "
                f"embedding settings are now {configured.provider}/{configured.model}."
                " Re-index the book."
            )
        embedder = self._embedding_factory(configured)

        if total == 0:
            yield Progress(Stage.STORE, 0, 0, 0, 0.0)
            return
        if len(embedded) > total:
            raise CheckpointMismatchError(
                f"{len(embedded)} vectors stored for {total} chunks; "
                "the file or settings changed"
            )

        batch_size = DATA_SIZE.get_batch_size(total)
        start = done = len(embedded)
        started = self._clock()
        yield Progress(Stage.EMBED, done, total, done, None)

        # Walk the chunks in id order. The cursor is the id of the last chunk
        # seen, never a count: ids are not contiguous once chapters have been
        # added, edited or removed.
        cursor: int | None = None
        while True:
            async with self._read_uow_factory() as uow:
                page = await uow.chunks.get_all_for_book(
                    job.book_id, after_id=cursor, limit=batch_size
                )
            if not page:
                break
            last_id = page[-1].id
            assert last_id is not None
            cursor = last_id

            batch = [c for c in page if c.id not in embedded]
            if not batch:
                continue

            vectors = await embedder.embed([c.text for c in batch])
            if len(vectors) != len(batch):
                raise EmbeddingCountError(
                    f"Expected {len(batch)} vectors, got {len(vectors)}"
                )
            async with self._uow_factory() as uow:
                await uow.vectors.upsert(batch, vectors, model)
                await uow.commit()

            done += len(batch)
            yield Progress(
                Stage.EMBED,
                done,
                total,
                done,
                self._eta(started, start, done, total),
            )
        yield Progress(Stage.STORE, total, total, total, 0.0)

    def _eta(
        self, started: float, resume_at: int, done: int, total: int
    ) -> float | None:
        processed, elapsed = done - resume_at, self._clock() - started
        if processed <= 0 or elapsed <= 0:
            return None
        return (total - done) / (processed / elapsed)

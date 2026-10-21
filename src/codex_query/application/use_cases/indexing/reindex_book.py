"""Use case for re-indexing books that have already been indexed."""

from collections.abc import Sequence
from uuid import uuid4

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.use_cases.indexing.start_indexing import StartIndexing
from codex_query.domain.models.document import Book
from codex_query.domain.models.job import IndexingJob
from codex_query.domain.value_objects import QueueIndexJobRequest


class ReindexDocument:
    """Queue a fresh indexing job for books that are already in the library.

    This is the same flow as adding the book again from its file, so the parsing
    pipeline decides how much work is really needed by comparing the stored book
    with the file and the current settings:

    - embedding model or provider changed: chunks are kept, vectors are dropped
      and every chunk is embedded again;
    - chunk size changed: the book is re-chunked and re-embedded;
    - file changed: only new and edited chapters are chunked and embedded;
    - nothing changed: nothing happens, the job finishes immediately.

    Design decisions (previously open questions):

    - A model or provider change has to re-index every book, because a question
      is embedded with the *current* model and can only be compared with vectors
      from that same model. The settings screen confirms this with the user and
      then calls this use case for the stale books.
    - A chunk size change does not force a re-index; the slider is labelled "new
      books only". An explicit re-index (e.g. a button on a library card, which
      can call this use case with a single id) picks the new size up.
    - The source file is read again, so a book whose file was moved or deleted
      ends up as a failed job with the parser's error message.
    """

    def __init__(
        self,
        read_uow_factory: UnitOfWorkFactory,
        start: StartIndexing,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the ReindexDocument use case.

        Args:
            read_uow_factory: Factory to create read-only unit of work instances.
            start: Use case that submits an indexing job to the runner.
            logger_factory: Factory to create contextual logger instances.
        """
        self._read_uow_factory = read_uow_factory
        self._start = start
        self._logger = logger_factory.create(__name__)

    async def __call__(self, book_ids: Sequence[int]) -> list[tuple[IndexingJob, str]]:
        """Queue a job for each of the given books.

        Args:
            book_ids: Database ids of the books to re-index. Unknown ids are
                skipped.

        Returns:
            The queued jobs paired with their book titles, so the caller can show
            them. Jobs run one after another in the runner.
        """
        self._logger.info("Re-indexing %d book(s)", len(book_ids))

        books: list[Book] = []
        async with self._read_uow_factory() as uow:
            for book_id in book_ids:
                book = await uow.books.get_by_id(book_id)
                if book is None:
                    self._logger.warning("Book %s not found; skipping", book_id)
                    continue
                books.append(book)

        queued: list[tuple[IndexingJob, str]] = []
        for book in books:
            job = IndexingJob(id=uuid4(), book_id=-1)
            self._start(job, _request_for(book))
            queued.append((job, book.title))
            self._logger.info("Queued job %s to re-index '%s'", job.id, book.title)
        return queued


def _request_for(book: Book) -> QueueIndexJobRequest:
    """Rebuild the original request from the stored book.

    Carrying the stored metadata over keeps anything the user entered by hand
    from being replaced by what the file says.
    """
    meta = book.meta
    return QueueIndexJobRequest(
        title=book.title,
        source=book.path,
        series=book.series,
        number=meta.book_number,
        language=meta.language,
        publisher=meta.publisher,
        description=meta.description,
        isbn=meta.isbn,
        published_year=meta.published_year,
        subjects=meta.subjects,
        document_type=meta.document_type,
    )

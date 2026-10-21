"""Use case for resuming paused or interrupted indexing jobs.

This module provides the `ResumeIndexing` use case, responsible for retrieving
paused jobs, validating their resume eligibility, fetching associated book
metadata via the unit of work, constructing the indexing job request, and
re-invoking the `StartIndexing` use case.
"""

from uuid import UUID

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.use_cases.indexing.start_indexing import StartIndexing
from codex_query.domain.value_objects import QueueIndexJobRequest


class ResumeIndexing:
    """Use case handler for resuming paused or interrupted indexing jobs.

    Retrieves jobs, checks resume conditions, looks up corresponding book details,
    recreates the queue request, and restarts the execution flow.
    """

    def __init__(
        self,
        read_uow_factory: UnitOfWorkFactory,
        start: StartIndexing,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the ResumeIndexing use case.

        Args:
            read_uow_factory: Factory to create read-only unit of work instances.
            start: Use case handler for starting indexing jobs.
            logger_factory: Factory to create contextual logger instances.
        """
        self._read_uow_factory = read_uow_factory
        self._start = start
        self._logger = logger_factory.create(__name__)

    async def __call__(self, job_id: UUID) -> None:
        """Execute the resume indexing workflow for a given job ID.

        Fetches the job, verifies if it can be resumed, retrieves its associated
        book information, builds the indexing request, and dispatches it.

        Args:
            job_id: Unique identifier of the job to resume.
        """
        self._logger.info("Attempting to resume indexing job %s", job_id)

        async with self._read_uow_factory() as uow:
            job = await uow.jobs.get(job_id)

        if job is None:
            self._logger.warning("Job %s not found; cannot resume", job_id)
            return

        if not job.can_resume:
            self._logger.info(
                "Job %s is not in a resumable state (status: %s)",
                job_id,
                job.status,
            )
            return

        self._logger.debug("Fetching book record %s for job %s", job.book_id, job_id)
        async with self._read_uow_factory() as uow:
            book = await uow.books.get_by_id(job.book_id)

        if book is None:
            self._logger.error(
                "Associated book %s not found for job %s; cannot resume",
                job.book_id,
                job_id,
            )
        assert book is not None

        self._logger.info("Constructing queue request and restarting job %s", job_id)
        request = QueueIndexJobRequest(
            title=book.title,
            source=book.path,
        )
        self._start(job, request)

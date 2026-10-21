"""Application use case for recovering interrupted indexing jobs and fetching their
book titles on startup."""

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.models.job import IndexingJob, JobStatus


class RecoverInterruptedJobs:
    """Use case responsible for identifying and pausing interrupted indexing jobs.

    Typically invoked during application startup to clean up jobs left in active
    states (e.g., due to an unexpected crash or system shutdown) and retrieve
    their corresponding book titles.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the RecoverInterruptedJobs use case.

        Args:
            uow_factory: Factory to create units of work for data access.
            logger_factory: Factory used to create a contextual logger.
        """
        self._uow_factory = uow_factory
        self._logger = logger_factory.create(__name__)

    async def __call__(self) -> list[tuple[IndexingJob, str | None]]:
        """Execute the recovery process.

        Retrieves active jobs, pauses any that were left running or queued,
        fetches their associated book titles, persists the changes, commits
        the transaction, and returns the list of recovered jobs paired with
        their book titles.

        Returns:
            A list of tuples containing the IndexingJob and its associated book
            title (or None).
        """
        self._logger.info("Starting recovery of interrupted indexing jobs...")

        async with self._uow_factory() as uow:
            jobs = await uow.jobs.list_active()
            self._logger.debug("Found %d active jobs during recovery check", len(jobs))

            recovered = []
            for job in jobs:
                if job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
                    self._logger.info(
                        "Pausing interrupted job %s (previous status: %s)",
                        job.id,
                        job.status.value,
                    )
                    job.pause()
                    await uow.jobs.save(job)
                    book = await uow.books.get_by_id(job.book_id)

                    book_title = book.title if book else None
                    self._logger.debug(
                        "Retrieved book title '%s' for job %s",
                        book_title,
                        job.id,
                    )
                    recovered.append((job, book_title))

            await uow.commit()
            self._logger.info(
                "Job recovery completed successfully. Paused %d active job(s).",
                len(recovered),
            )
            return recovered

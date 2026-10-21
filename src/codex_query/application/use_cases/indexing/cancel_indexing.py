"""Application use case for canceling an indexing job and cleaning up its resources."""

from uuid import UUID

from codex_query.application.ports.indexing import JobRunnerPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.observable.job_events import JobEvents


class CancelIndexing:
    """Use case responsible for canceling an indexing job.

    Handles stopping the active runner task, updating the job domain model,
    cleaning up associated book records and vectors from the persistence layer,
    and notifying UI observers of the job update.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        runner: JobRunnerPort,
        events: JobEvents,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the CancelIndexing use case.

        Args:
            uow_factory: Factory to create units of work for data access.
            runner: Port responsible for executing or halting background job runs.
            events: Event emitter for propagating job state updates to the UI.
            logger_factory: Factory used to create a contextual logger.
        """
        self._uow_factory = uow_factory
        self._runner = runner
        self._events = events
        self._logger = logger_factory.create(__name__)

    async def __call__(self, job_id: UUID) -> None:
        """Execute the cancellation process for a given indexing job.

        Args:
            job_id: The unique identifier of the job to cancel.
        """
        self._logger.info("Attempting to cancel indexing job %s", job_id)

        async with self._uow_factory() as uow:
            job = await uow.jobs.get(job_id)

        if job is None:
            self._logger.warning(
                "Could not cancel indexing job %s: job not found",
                job_id,
            )
            return

        self._logger.debug("Stopping runner for job %s", job_id)
        await self._runner.cancel(job_id)
        job.cancel()

        self._logger.info(
            "Cleaning up book data and vectors for book %s associated with job %s",
            job.book_id,
            job_id,
        )
        async with self._uow_factory() as uow:
            await uow.books.delete(job.book_id)
            await uow.vectors.delete_book(job.book_id)
            await uow.commit()

        self._logger.info(
            "Indexing job %s successfully canceled and cleaned up", job_id
        )
        self._events.on_job_update.emit(job)

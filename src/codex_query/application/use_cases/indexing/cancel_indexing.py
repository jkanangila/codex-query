"""Application use case for canceling an indexing job and cleaning up its resources."""

from uuid import UUID

from codex_query.application.observable.job_events import JobEvents
from codex_query.application.ports.indexing import JobRunnerPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.models.job import JobStatus


class CancelIndexing:
    """Use case responsible for canceling an indexing job.

    Stops the runner task, marks the job cancelled, and removes what the job
    created. A book that was already indexed by an earlier, completed job is kept
    (cancelling an *update* must not delete the whole book); a book that only
    exists because of this job is deleted together with its vectors.
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

        # Stop the work first. This needs no database row, so it also stops a
        # job that is still parsing and has not been persisted yet.
        await self._runner.cancel(job_id)

        # Read afterwards: stopping the task lets it save its final (paused) state.
        async with self._uow_factory() as uow:
            job = await uow.jobs.get(job_id)

        if job is None:
            self._logger.info("Job %s was never persisted; nothing to clean up", job_id)
            return
        if not job.is_active:
            self._logger.info("Job %s already %s", job_id, job.status.value)
            return

        job.cancel()

        async with self._uow_factory() as uow:
            others = await uow.jobs.list_for_book(job.book_id)
            already_indexed = any(
                other.id != job.id and other.status is JobStatus.COMPLETED
                for other in others
            )
            if already_indexed:
                self._logger.info(
                    "Book %s was indexed before; keeping it and recording the "
                    "cancellation of job %s",
                    job.book_id,
                    job_id,
                )
                await uow.jobs.save(job)
            else:
                self._logger.info(
                    "Deleting book %s and its vectors (created by job %s)",
                    job.book_id,
                    job_id,
                )
                await uow.books.delete(job.book_id)  # cascades to the job row
                await uow.vectors.delete_book(job.book_id)
            await uow.commit()

        self._logger.info("Indexing job %s successfully canceled", job_id)
        self._events.on_job_update.emit(job)

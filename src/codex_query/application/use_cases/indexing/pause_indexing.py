"""Use case for pausing ongoing or queued indexing jobs.

This module provides the `PauseIndexing` use case, responsible for retrieving
job records, requesting cancellation from the job runner, updating job statuses
to paused when appropriate, persisting state changes, and emitting UI events.
"""

from uuid import UUID

from codex_query.application.ports.indexing import JobRunnerPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.models.job import JobStatus
from codex_query.application.observable.job_events import JobEvents


class PauseIndexing:
    """Use case handler for pausing indexing jobs.

    Cancels active execution via the job runner, handles persistence of the paused
    state for queued jobs, and notifies the UI layer via job update events.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        runner: JobRunnerPort,
        events: JobEvents,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the PauseIndexing use case.

        Args:
            uow_factory: Factory to create unit of work instances for persistence.
            runner: Job runner port to manage background job cancellation.
            events: Event emitter for UI job updates.
            logger_factory: Factory to create contextual logger instances.
        """
        self._uow_factory = uow_factory
        self._runner = runner
        self._events = events
        self._logger = logger_factory.create(__name__)

    async def __call__(self, job_id: UUID) -> None:
        """Execute the pause indexing workflow for a given job ID.

        Retrieves the job, cancels its execution via the runner, and updates
        its status if it was still queued.

        Args:
            job_id: Unique identifier of the job to pause.
        """
        self._logger.info("Attempting to pause indexing job %s", job_id)

        async with self._uow_factory() as uow:
            job = await uow.jobs.get(job_id)

        if job is None:
            self._logger.warning("Job %s not found; cannot pause", job_id)
            return

        self._logger.debug("Cancelling job runner execution for %s", job_id)
        await self._runner.cancel(job_id)

        if job.status is JobStatus.QUEUED:
            self._logger.info(
                "Job %s is queued; marking as paused and persisting", job_id
            )
            job.pause()
            async with self._uow_factory() as uow:
                await uow.jobs.save(job)
                await uow.commit()
            self._events.on_job_update.emit(job)
        else:
            self._logger.info(
                "Job %s cancellation requested (status: %s)", job_id, job.status
            )

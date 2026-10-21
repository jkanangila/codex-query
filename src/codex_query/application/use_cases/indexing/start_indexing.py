"""Use case for starting and orchestrating indexing and parsing jobs.

This module provides the `StartIndexing` use case, responsible for submitting
indexing jobs to a background runner, executing parsing and indexing pipelines
asynchronously, persisting job state transitions, and emitting corresponding
UI events.
"""

import asyncio

from codex_query.application.pipelines.indexing_pipeline import (
    IndexingPipeline,
)
from codex_query.application.pipelines.parsing_pipeline import (
    ParsePersistPipeline,
)
from codex_query.application.ports.indexing import JobRunnerPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.errors import JobNotFoundError
from codex_query.domain.models.job import IndexingJob
from codex_query.domain.value_objects import QueueIndexJobRequest
from codex_query.application.observable.job_events import (
    JobEvents,
)


class StartIndexing:
    """Use case handler for executing asynchronous indexing jobs.

    Coordinates parsing and indexing pipelines, manages persistence of job states
    through a unit of work factory, handles job lifecycle events, and intercepts
    errors or cancellations.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        runner: JobRunnerPort,
        events: JobEvents,
        parsing_pipeline: ParsePersistPipeline,
        indexing_pipeline: IndexingPipeline,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the StartIndexing use case.

        Args:
            uow_factory: Factory to create unit of work instances for persistence.
            runner: Job runner port to submit background jobs.
            events: Event emitter for UI job updates.
            parsing_pipeline: Pipeline for parsing and persisting source data.
            indexing_pipeline: Pipeline for building search indices.
        """
        self._uow_factory = uow_factory
        self._runner = runner
        self._events = events
        self._parsing_pipeline = parsing_pipeline
        self._indexing_pipeline = indexing_pipeline
        self._logger = logger_factory.create(__name__)

    def __call__(self, job: IndexingJob, request: QueueIndexJobRequest) -> None:
        """Submit the indexing job to the background runner.

        Args:
            job: The indexing job entity.
            request: The queued indexing job request parameters.
        """
        self._logger.info("Submitting indexing job %s to runner", job.id)
        self._runner.submit(
            job_id=job.id, work=lambda: self._run(job=job, request=request)
        )

    async def _run(self, job: IndexingJob, request: QueueIndexJobRequest) -> None:
        """Execute the parsing and indexing pipelines asynchronously.

        Args:
            job: The indexing job entity.
            request: The queued indexing job request parameters.
        """
        self._logger.info("Starting execution for indexing job %s", job.id)
        try:
            async for progress, _job in self._parsing_pipeline(job, request):
                job = _job
                job.record(
                    progress.stage,
                    progress.done,
                    progress.total,
                    progress.checkpoint,
                    progress.eta_s or 0.0,
                )
                await self._persist(job, is_update=True)

            async for progress in self._indexing_pipeline(job):
                job.record(
                    progress.stage,
                    progress.done,
                    progress.total,
                    progress.checkpoint,
                    progress.eta_s or 0.0,
                )
                await self._persist(job, is_update=True)

        except asyncio.CancelledError:
            self._logger.warning("Indexing job %s was cancelled", job.id)
            job.pause()
            await self._persist(job, is_update=True)
        except JobNotFoundError:
            self._logger.warning("Job %s not found during execution", job.id)
        except Exception as exc:
            self._logger.exception("Indexing job %s failed with error: %s", job.id, exc)
            job.fail(str(exc))
            await self._persist(job, is_update=True)
        else:
            self._logger.info("Indexing job %s completed successfully", job.id)
            job.complete()
            await self._persist(job, is_update=False)

    async def _persist(self, job: IndexingJob, is_update: bool) -> None:
        """Persist the current job state and emit corresponding UI events.

        Args:
            job: The indexing job entity.
            is_update: Flag indicating if the job is ongoing (update) or finished.
        """
        self._logger.debug("Persisting job %s state (is_update=%s)", job.id, is_update)
        async with self._uow_factory() as uow:
            await uow.jobs.save(job)
            await uow.commit()
        if is_update:
            self._events.on_job_update.emit(job)
        else:
            self._events.on_job_done.emit(job)

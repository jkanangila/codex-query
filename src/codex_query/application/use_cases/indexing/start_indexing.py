"""Use case for starting and orchestrating indexing and parsing jobs.

This module provides the `StartIndexing` use case, responsible for submitting
indexing jobs to a background runner, executing parsing and indexing pipelines
asynchronously, persisting job state transitions, and emitting corresponding
UI events.
"""

import asyncio

from codex_query.application.observable.job_events import JobEvents
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
from codex_query.domain.models.job import IndexingJob, JobStatus
from codex_query.domain.value_objects import Progress, QueueIndexJobRequest

_STARTABLE = frozenset({JobStatus.QUEUED, JobStatus.PAUSED, JobStatus.FAILED})


class StartIndexing:
    """Use case handler for executing asynchronous indexing jobs.

    Coordinates parsing and indexing pipelines, manages persistence of job states
    through a unit of work factory, handles job lifecycle events, and intercepts
    errors or cancellations.

    A job has one of two shapes:

    - **New** (``book_id < 0``): nothing is in the database yet. The parsing
      pipeline registers or updates the book and inserts the job row, then the
      indexing pipeline embeds what is missing. A ``request`` is required.
    - **Existing** (``book_id >= 0``), e.g. a paused or failed job being resumed:
      the book and its chunks are already stored, so parsing is skipped and only
      the embedding stage runs. No ``request`` is needed.
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
            logger_factory: Factory to create contextual logger instances.
        """
        self._uow_factory = uow_factory
        self._runner = runner
        self._events = events
        self._parsing_pipeline = parsing_pipeline
        self._indexing_pipeline = indexing_pipeline
        self._logger = logger_factory.create(__name__)

    def __call__(
        self, job: IndexingJob, request: QueueIndexJobRequest | None = None
    ) -> None:
        """Submit the indexing job to the background runner.

        Args:
            job: The indexing job entity.
            request: What to index. Required for a new job (``book_id < 0``),
                ignored for an existing one.

        Raises:
            ValueError: If a new job is submitted without a request.
        """
        if job.status not in _STARTABLE:
            self._logger.warning(
                "Job %s is %s and cannot be started", job.id, job.status.value
            )
            return
        if job.book_id < 0 and request is None:
            raise ValueError("A new indexing job needs a request")

        self._logger.info("Submitting indexing job %s to runner", job.id)
        self._runner.submit(
            job_id=job.id, work=lambda: self._run(job=job, request=request)
        )

    async def _run(
        self, job: IndexingJob, request: QueueIndexJobRequest | None
    ) -> None:
        """Execute the parsing (new jobs only) and indexing pipelines.

        Args:
            job: The indexing job entity.
            request: The queued indexing job request parameters.
        """
        self._logger.info("Starting execution for indexing job %s", job.id)
        try:
            job.start()

            if job.book_id < 0:
                if request is None:
                    raise ValueError("A new indexing job needs a request")
                async for progress, new_job in self._parsing_pipeline(job, request):
                    # The pipeline hands back a *new* job once the book is
                    # registered, so keep working on that one.
                    job = new_job
                    await self._record(job, progress)

            async for progress in self._indexing_pipeline(job):
                await self._record(job, progress)

        except asyncio.CancelledError:
            self._logger.warning("Indexing job %s was cancelled", job.id)
            job.pause()
            await self._persist(job, is_update=True)
            raise
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

    async def _record(self, job: IndexingJob, progress: Progress) -> None:
        """Apply a pipeline progress report to the job, then persist and publish."""
        job.record(
            progress.stage,
            progress.done,
            progress.total,
            progress.checkpoint,
            progress.eta_s or 0.0,
        )
        await self._persist(job, is_update=True)

    async def _persist(self, job: IndexingJob, is_update: bool) -> None:
        """Persist the current job state and emit corresponding UI events.

        A new job only gets a database row when the parsing pipeline registers its
        book, so until then (``book_id < 0``) there is nothing to save and the
        change is only published.

        Args:
            job: The indexing job entity.
            is_update: Flag indicating if the job is ongoing (update) or finished.
        """
        self._logger.debug("Persisting job %s state (is_update=%s)", job.id, is_update)
        if job.book_id >= 0:
            async with self._uow_factory() as uow:
                await uow.jobs.save(job)
                await uow.commit()
        if is_update:
            self._events.on_job_update.emit(job)
        else:
            self._events.on_job_done.emit(job)

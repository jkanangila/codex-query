"""Use case for resuming paused or interrupted indexing jobs.

This module provides the `ResumeIndexing` use case, responsible for retrieving
paused jobs, validating their resume eligibility, and re-invoking the
`StartIndexing` use case.
"""

from uuid import UUID

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.use_cases.indexing.start_indexing import StartIndexing


class ResumeIndexing:
    """Use case handler for resuming paused or interrupted indexing jobs.

    A persisted job already has its book and chunks in the database, so resuming
    only has to run the embedding stage again; that stage works out for itself
    which chunks still lack a vector.
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
        """Resume the job with the given ID if it is in a resumable state.

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

        self._logger.info("Restarting job %s", job_id)
        self._start(job)

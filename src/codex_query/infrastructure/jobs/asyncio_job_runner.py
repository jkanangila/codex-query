"""Asynchronous job runner implementation using asyncio.

This module provides an asynchronous job execution engine implementing the
JobRunnerPort interface, managing concurrency constraints via semaphores and
tracking active background tasks.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import override
from uuid import UUID

from codex_query.application.ports.indexing import JobRunnerPort
from codex_query.infrastructure.logging.factory import create_logger

Work = Callable[[], Awaitable[None]]

logger = create_logger(__name__)


class AsyncioJobRunner(JobRunnerPort):
    """Asynchronous job runner enforcing concurrency limits via semaphores.

    Handles background task submission, tracking, cancellation, and execution
    guards for indexing and background operations.
    """

    def __init__(self, max_concurrent: int = 1) -> None:
        """Initialize the asynchronous job runner.

        Args:
            max_concurrent: The maximum number of jobs allowed to run
                concurrently. Defaults to 1.
        """
        self._slots = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        logger.debug(
            "Initialized AsyncioJobRunner with max_concurrent=%d",
            max_concurrent,
        )

    @override
    def submit(self, job_id: UUID, work: Work) -> None:
        """Submit a new job for asynchronous execution.

        If the job ID is already active, the submission is ignored.

        Args:
            job_id: Unique identifier for the job.
            work: An async callable representing the job workload.
        """
        if job_id in self._tasks:
            logger.warning("Job ID %d is already running; submission ignored.", job_id)
            return

        logger.info("Submitting job ID %d", job_id)
        task = asyncio.create_task(self._guarded(work))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._cleanup_task(job_id))

    def _cleanup_task(self, job_id: UUID) -> None:
        """Clean up completed or failed task from tracking dictionary.

        Args:
            job_id: Unique identifier for the job to clean up.
        """
        removed = self._tasks.pop(job_id, None)
        if removed is not None:
            logger.debug("Cleaned up tracking for job ID %d", job_id)

    @override
    async def cancel(self, job_id: UUID) -> None:
        """Cancel a running job by its ID.

        Args:
            job_id: Unique identifier for the job to cancel.
        """
        if task := self._tasks.get(job_id):
            logger.info("Cancelling job ID %d", job_id)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            logger.info("Job ID %d successfully cancelled", job_id)
        else:
            logger.debug(
                "Requested cancellation for non-existent or inactive job ID %d",
                job_id,
            )

    @override
    def is_running(self, job_id: UUID) -> bool:
        """Check whether a job is currently running or queued.

        Args:
            job_id: Unique identifier for the job.

        Returns:
            True if the job is active, False otherwise.
        """
        running = job_id in self._tasks
        logger.debug("Checked if job ID %d is running: %s", job_id, running)
        return running

    async def _guarded(self, work: Work) -> None:
        """Execute the workload under the concurrency semaphore guard.

        Args:
            work: The async callable workload to execute.
        """
        logger.debug("Waiting for concurrency slot to execute work")
        async with self._slots:
            logger.debug("Acquired concurrency slot; starting work execution")
            try:
                await work()
                logger.debug("Work execution completed successfully")
            except Exception:
                logger.exception("An error occurred during work execution")
                raise

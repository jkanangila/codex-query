from collections.abc import Sequence
from typing import override
from uuid import UUID

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.indexing import IndexingJobPort
from codex_query.domain.errors import JobNotFoundError
from codex_query.domain.models.job import (
    TERMINAL_STATUSES,
    IndexingJob,
    JobStatus,
    Stage,
)
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import (
    IndexingJob as IndexingJobRecord,
)

logger = create_logger(__name__)


class SqlModelIndexingJobRepository(IndexingJobPort):
    """SQLModel-backed repository for managing indexing job lifecycle states.

    Performs session flushes and executions only; transaction commits are managed
    by the UnitOfWork.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an active asynchronous SQLModel session.

        Args:
            session: Active AsyncSession bound to the current unit of work.
        """
        self._session = session

    @override
    async def add(self, job: IndexingJob) -> IndexingJob:
        """Persist a new indexing job entity to storage.

        Args:
            job: New domain IndexingJob model to persist.

        Returns:
            IndexingJob: Domain job instance with populated database primary key.
        """
        logger.info(
            "Creating new indexing job for book ID %d (status=%s, stage=%s)",
            job.book_id,
            job.status.value,
            job.stage.value,
        )
        record = _to_record(job)
        self._session.add(record)
        await self._session.flush()

        logger.info(
            "Successfully created indexing job ID %d for book ID %d",
            record.id,
            job.book_id,
        )
        return _to_domain(record)

    @override
    async def save(self, job: IndexingJob) -> None:
        """Update an existing indexing job record in storage.

        Args:
            job: Domain IndexingJob model with updated fields.

        Raises:
            JobNotFoundError: If no matching job record exists in storage.
        """
        logger.debug(
            "Updating indexing job ID %d (status=%s, stage=%s)",
            job.id,
            job.status.value,
            job.stage.value,
        )
        record = await self._session.get(IndexingJobRecord, job.id)
        if record is None:
            logger.warning("Failed to save job ID %d: record not found", job.id)
            raise JobNotFoundError(job.id)

        _apply(record, job)
        await self._session.flush()
        logger.info(
            "Successfully updated indexing job ID %d (status=%s)",
            job.id,
            job.status.value,
        )

    @override
    async def update_progress(
        self, job_id: int, *, stage: Stage, done: int, total: int, checkpoint: int
    ) -> None:
        """Update progress-specific attributes for a currently running job.

        Atomic field update targeting only progress columns prevents race conditions
        from overwriting concurrent job cancellation requests.

        Args:
            job_id: Primary key ID of the target job.
            stage: Current execution stage.
            done: Items completed in current stage.
            total: Total items expected in current stage.
            checkpoint: Persistent offset/checkpoint indicator.

        Raises:
            JobNotFoundError: If the job is missing or no longer in RUNNING status.
        """
        logger.debug(
            "Updating progress for running job ID %d "
            "(stage=%s, progress=%d/%d, checkpoint=%d)",
            job_id,
            stage.value,
            done,
            total,
            checkpoint,
        )
        result = await self._session.exec(
            update(IndexingJobRecord)
            .where(
                col(IndexingJobRecord.id) == job_id,
                col(IndexingJobRecord.status) == JobStatus.RUNNING,
            )
            .values(stage=stage, done=done, total=total, checkpoint=checkpoint)
        )
        if result.rowcount == 0:
            logger.warning(
                "Failed to update progress for job ID %d: "
                "record missing or not RUNNING",
                job_id,
            )
            raise JobNotFoundError(job_id)

        logger.debug("Successfully updated progress metrics for job ID %d", job_id)

    @override
    async def get(self, job_id: UUID) -> IndexingJob | None:
        """Fetch an indexing job by its database primary key.

        Args:
            job_id: Database ID of the target job.

        Returns:
            IndexingJob | None: Mapped domain indexing job if found, None otherwise.
        """
        logger.debug("Querying indexing job by ID: %d", job_id)
        record = await self._session.get(IndexingJobRecord, job_id)
        if record is None:
            logger.debug("No indexing job found matching ID: %d", job_id)
            return None
        logger.debug("Retrieved indexing job ID %d (status=%s)", job_id, record.status)
        return _to_domain(record)

    @override
    async def get_next_queued(self) -> IndexingJob | None:
        """Retrieve the oldest queued indexing job ready for execution.

        Returns:
            IndexingJob | None: Oldest queued domain job model,
                or None if queue is empty.
        """
        logger.debug("Querying for next queued indexing job")
        stmt = (
            select(IndexingJobRecord)
            .where(col(IndexingJobRecord.status) == JobStatus.QUEUED)
            .order_by(col(IndexingJobRecord.id))
            .limit(1)
        )
        result = await self._session.exec(stmt)
        record = result.first()
        if record is None:
            logger.debug("No queued indexing jobs found")
            return None
        logger.info("Found next queued indexing job ID %d", record.id)
        return _to_domain(record)

    @override
    async def list_active(self) -> list[IndexingJob]:
        """Fetch all non-terminal active indexing jobs.

        Returns:
            list[IndexingJob]: List of active non-terminal domain job instances.
        """
        logger.debug("Fetching all active non-terminal indexing jobs")
        stmt = (
            select(IndexingJobRecord)
            .where(col(IndexingJobRecord.status).not_in(tuple(TERMINAL_STATUSES)))
            .order_by(col(IndexingJobRecord.id))
        )
        result = await self._session.exec(stmt)
        active_jobs = result.all()
        logger.debug("Retrieved %d active indexing job(s)", len(active_jobs))
        return [_to_domain(r) for r in active_jobs]

    @override
    async def list_for_book(self, book_id: int) -> Sequence[IndexingJob]:
        """Fetch all indexing jobs associated with a specific book ID.

        Args:
            book_id: Database ID of the target book.

        Returns:
            Sequence[IndexingJob]: Sequence of domain indexing job models.
        """
        logger.debug("Fetching indexing jobs for book ID %d", book_id)
        stmt = (
            select(IndexingJobRecord)
            .where(col(IndexingJobRecord.book_id) == book_id)
            .order_by(col(IndexingJobRecord.id))
        )
        result = await self._session.exec(stmt)
        jobs = result.all()
        logger.debug("Retrieved %d indexing job(s) for book ID %d", len(jobs), book_id)
        return [_to_domain(r) for r in jobs]

    @override
    async def reset_running_to_queued(self) -> int:
        """Reset interrupted RUNNING jobs to QUEUED status during startup initialization

        Allows jobs interrupted by sudden process crash or shutdown to resume execution.

        Returns:
            int: Total number of interrupted jobs successfully reset to QUEUED.
        """
        logger.info("Resetting orphaned RUNNING jobs to QUEUED status")
        result = await self._session.exec(
            update(IndexingJobRecord)
            .where(col(IndexingJobRecord.status) == JobStatus.RUNNING)
            .values(status=JobStatus.QUEUED)
        )
        reset_count = result.rowcount
        if reset_count > 0:
            logger.info("Successfully reset %d RUNNING job(s) to QUEUED", reset_count)
        else:
            logger.debug("No orphaned RUNNING jobs found to reset")
        return reset_count

    @override
    async def delete(self, job_id: UUID) -> bool:
        """Delete an indexing job record from storage by its primary key ID.

        Args:
            job_id: Database ID of the job to delete.

        Returns:
            bool: True if the record was found and deleted, False otherwise.
        """
        logger.info("Attempting to delete indexing job ID %d", job_id)
        result = await self._session.exec(
            delete(IndexingJobRecord).where(col(IndexingJobRecord.id) == job_id)
        )
        deleted = result.rowcount > 0
        if deleted:
            logger.info("Successfully deleted indexing job ID %d", job_id)
        else:
            logger.warning("Cannot delete indexing job ID %d: record not found", job_id)
        return deleted


def _to_record(job: IndexingJob) -> IndexingJobRecord:
    """Map a domain IndexingJob entity to an ORM database record.

    Args:
        job: Source domain IndexingJob entity.

    Returns:
        IndexingJobRecord: SQLModel database ORM entity.
    """
    logger.debug("Mapping domain IndexingJob to ORM record")
    return IndexingJobRecord(
        id=job.id,
        book_id=job.book_id,
        status=job.status,
        stage=job.stage,
        done=job.done,
        total=job.total,
        checkpoint=job.checkpoint,
        eta=job.eta,
        error=job.error,
        # map created_at / started_at / finished_at here once the domain has them
    )


def _apply(record: IndexingJobRecord, job: IndexingJob) -> None:
    """Apply updated domain job fields onto an existing ORM database record.

    Note that `book_id` is deliberately omitted because a job cannot change books.

    Args:
        record: Target SQLModel ORM record to mutate.
        job: Source domain IndexingJob entity providing updated values.
    """
    logger.debug("Applying updated fields to ORM record for job ID %d", record.id)
    record.status = job.status
    record.stage = job.stage
    record.done = job.done
    record.total = job.total
    record.checkpoint = job.checkpoint
    record.eta = job.eta
    record.error = job.error


def _to_domain(record: IndexingJobRecord) -> IndexingJob:
    """Map an ORM database record into a domain IndexingJob entity.

    Args:
        record: Source SQLModel ORM record.

    Returns:
        IndexingJob: Mapped domain IndexingJob model.
    """
    logger.debug("Mapping ORM record ID %d to domain IndexingJob", record.id)
    return IndexingJob(
        id=record.id,
        book_id=record.book_id,
        status=record.status,
        stage=record.stage,
        done=record.done,
        total=record.total,
        checkpoint=record.checkpoint,
        eta=record.eta,
        error=record.error,
    )

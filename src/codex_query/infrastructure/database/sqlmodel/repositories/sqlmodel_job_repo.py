"""SQLModel persistence implementation for indexing jobs."""

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
from codex_query.infrastructure.database.sqlmodel.models import (
    IndexingJob as IndexingJobRecord,
)
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class SqlModelIndexingJobRepository(IndexingJobPort):
    """SQLModel-backed repository for indexing job lifecycle state.

    Performs session flushes and statement executions only; transaction commits
    are managed by the `UnitOfWork`.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an asynchronous SQLModel session.

        Args:
            session: Active session bound to the current unit of work.
        """
        self._session = session

    @override
    async def add(self, job: IndexingJob) -> IndexingJob:
        """Persist a new indexing job and flush the session.

        Args:
            job: Domain indexing job to insert.

        Returns:
            Persisted domain indexing job with database-assigned fields populated.
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
            "Successfully created indexing job ID %s for book ID %d",
            record.id,
            job.book_id,
        )
        return _to_domain(record)

    @override
    async def save(self, job: IndexingJob) -> None:
        """Update an existing indexing job record and flush the session.

        Args:
            job: Domain indexing job containing updated state fields.

        Raises:
            JobNotFoundError: If no matching job record exists in storage.
        """
        logger.debug(
            "Updating indexing job ID %s (status=%s, stage=%s)",
            job.id,
            job.status.value,
            job.stage.value,
        )
        record = await self._session.get(IndexingJobRecord, job.id)
        if record is None:
            logger.warning("Failed to save job ID %s: record not found", job.id)
            raise JobNotFoundError(job.id)

        _apply(record, job)
        await self._session.flush()
        logger.info(
            "Successfully updated indexing job ID %s (status=%s)",
            job.id,
            job.status.value,
        )

    @override
    async def update_progress(
        self, job_id: int, *, stage: Stage, done: int, total: int, checkpoint: int
    ) -> None:
        """Update progress fields for a currently running job.

        Targets only progress columns so concurrent cancellation requests are not
        overwritten.

        Args:
            job_id: Identifier of the target job.
            stage: Current execution stage.
            done: Completed item count in the current stage.
            total: Total expected item count in the current stage.
            checkpoint: Persistent progress offset or checkpoint value.

        Raises:
            JobNotFoundError: If the job does not exist or is not in `RUNNING`
                status.
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
        """Fetch an indexing job by its identifier.

        Args:
            job_id: Unique identifier of the target job.

        Returns:
            Mapped domain indexing job when found, otherwise `None`.
        """
        logger.debug("Querying indexing job by ID: %s", job_id)
        record = await self._session.get(IndexingJobRecord, job_id)
        if record is None:
            logger.debug("No indexing job found matching ID: %s", job_id)
            return None
        logger.debug("Retrieved indexing job ID %s (status=%s)", job_id, record.status)
        return _to_domain(record)

    @override
    async def get_next_queued(self) -> IndexingJob | None:
        """Fetch the oldest queued indexing job ready for execution.

        Returns:
            Earliest queued domain indexing job by ID, or `None` if none are
            queued.
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
        logger.info("Found next queued indexing job ID %s", record.id)
        return _to_domain(record)

    @override
    async def list_active(self) -> list[IndexingJob]:
        """Fetch all non-terminal active indexing jobs ordered by ID.

        Returns:
            Active indexing jobs whose status is outside `TERMINAL_STATUSES`.
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
        """Fetch all indexing jobs for a book ordered by ID.

        Args:
            book_id: Primary key of the target book.

        Returns:
            Indexing jobs associated with `book_id`.
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
        """Reset interrupted `RUNNING` jobs to `QUEUED` during startup recovery.

        Allows jobs interrupted by a sudden process stop or crash to resume.

        Returns:
            Number of jobs updated from `RUNNING` to `QUEUED`.
        """
        logger.info("Resetting orphaned RUNNING jobs to QUEUED status")
        result = await self._session.exec(
            update(IndexingJobRecord)
            .where(col(IndexingJobRecord.status) == JobStatus.RUNNING)
            .values(status=JobStatus.QUEUED)
        )
        reset_count = result.rowcount or 0
        if reset_count > 0:
            logger.info("Successfully reset %d RUNNING job(s) to QUEUED", reset_count)
        else:
            logger.debug("No orphaned RUNNING jobs found to reset")
        return reset_count

    @override
    async def delete(self, job_id: UUID) -> bool:
        """Delete an indexing job record by its identifier.

        Args:
            job_id: Unique identifier of the job to delete.

        Returns:
            `True` if a matching job record was deleted, `False` otherwise.
        """
        logger.info("Attempting to delete indexing job ID %s", job_id)
        result = await self._session.exec(
            delete(IndexingJobRecord).where(col(IndexingJobRecord.id) == job_id)
        )
        deleted = (result.rowcount or 0) > 0
        if deleted:
            logger.info("Successfully deleted indexing job ID %s", job_id)
        else:
            logger.warning("Cannot delete indexing job ID %s: record not found", job_id)
        return deleted


def _to_record(job: IndexingJob) -> IndexingJobRecord:
    """Convert a domain `IndexingJob` into a SQLModel `IndexingJobRecord`.

    Args:
        job: Source domain indexing job.

    Returns:
        SQLModel `IndexingJobRecord` populated with current domain fields.
    """
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
    """Copy mutable domain job fields onto an existing ORM record.

    Leaves `book_id` unchanged because a job cannot move to another book.

    Args:
        record: Existing ORM record mutated in place.
        job: Source domain indexing job providing updated values.
    """
    record.status = job.status
    record.stage = job.stage
    record.done = job.done
    record.total = job.total
    record.checkpoint = job.checkpoint
    record.eta = job.eta
    record.error = job.error


def _to_domain(record: IndexingJobRecord) -> IndexingJob:
    """Convert a SQLModel `IndexingJobRecord` into a domain `IndexingJob`.

    Args:
        record: Source ORM indexing job record.

    Returns:
        Domain `IndexingJob` populated from the ORM record.
    """
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

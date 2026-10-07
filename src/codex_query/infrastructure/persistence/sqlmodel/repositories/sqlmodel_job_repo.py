from collections.abc import Sequence
from typing import override

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.indexing import IJobRepository
from codex_query.domain.errors import JobNotFoundError  # add to your domain
from codex_query.domain.models.job import IndexingJob, JobStatus, Stage
from codex_query.infrastructure.persistence.sqlmodel.models import (
    IndexingJob as IndexingJobRecord,
)

# Prefer JobStatus.TERMINAL in the domain; kept local so this compiles as-is.
_TERMINAL = (JobStatus.COMPLETED, JobStatus.CANCELLED)  # add FAILED if not retryable


class SQLModelIndexingJobRepository(IJobRepository):
    """SQLModel-backed job repository. Flushes only; the UnitOfWork commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, job: IndexingJob) -> IndexingJob:
        record = _to_record(job)
        record.id = None  # let the DB assign the PK
        self._session.add(record)
        await self._session.flush()
        return _to_domain(record)

    @override
    async def save(self, job: IndexingJob) -> None:
        if job.id is None:
            raise ValueError("Use add() for jobs without an id")
        record = await self._session.get(IndexingJobRecord, job.id)
        if record is None:
            raise JobNotFoundError(job.id)
        _apply(record, job)
        await self._session.flush()

    @override
    async def update_progress(
        self, job_id: int, *, stage: Stage, done: int, total: int, checkpoint: int
    ) -> None:
        """Touch only progress columns, so a concurrent cancel is not overwritten."""
        result = await self._session.exec(
            update(IndexingJobRecord)
            .where(
                col(IndexingJobRecord.id) == job_id,
                col(IndexingJobRecord.status) == JobStatus.RUNNING,
            )
            .values(stage=stage, done=done, total=total, checkpoint=checkpoint)
        )
        if result.rowcount == 0:
            raise JobNotFoundError(job_id)  # missing, or no longer running

    @override
    async def get(self, job_id: int) -> IndexingJob | None:
        record = await self._session.get(IndexingJobRecord, job_id)
        return _to_domain(record) if record else None

    @override
    async def get_next_queued(self) -> IndexingJob | None:
        stmt = (
            select(IndexingJobRecord)
            .where(col(IndexingJobRecord.status) == JobStatus.QUEUED)
            .order_by(col(IndexingJobRecord.id))
            .limit(1)
        )
        result = await self._session.exec(stmt)
        record = result.first()
        return _to_domain(record) if record else None

    @override
    async def list_active(self) -> list[IndexingJob]:
        stmt = (
            select(IndexingJobRecord)
            .where(col(IndexingJobRecord.status).not_in(_TERMINAL))
            .order_by(col(IndexingJobRecord.id))
        )
        result = await self._session.exec(stmt)
        return [_to_domain(r) for r in result.all()]

    @override
    async def list_for_book(self, book_id: int) -> Sequence[IndexingJob]:
        stmt = (
            select(IndexingJobRecord)
            .where(col(IndexingJobRecord.book_id) == book_id)
            .order_by(col(IndexingJobRecord.id))
        )
        result = await self._session.exec(stmt)
        return [_to_domain(r) for r in result.all()]

    @override
    async def reset_running_to_queued(self) -> int:
        """Call once at startup: jobs interrupted by a crash resume from checkpoint."""
        result = await self._session.exec(
            update(IndexingJobRecord)
            .where(col(IndexingJobRecord.status) == JobStatus.RUNNING)
            .values(status=JobStatus.QUEUED)
        )
        return result.rowcount

    @override
    async def delete(self, job_id: int) -> bool:
        result = await self._session.exec(
            delete(IndexingJobRecord).where(col(IndexingJobRecord.id) == job_id)
        )
        return result.rowcount > 0


def _to_record(job: IndexingJob) -> IndexingJobRecord:
    return IndexingJobRecord(
        id=job.id,
        book_id=job.book_id,
        status=job.status,
        stage=job.stage,
        done=job.done,
        total=job.total,
        checkpoint=job.checkpoint,
        error=job.error,
        # map created_at / started_at / finished_at here once the domain has them
    )


def _apply(record: IndexingJobRecord, job: IndexingJob) -> None:
    record.status = job.status
    record.stage = job.stage
    record.done = job.done
    record.total = job.total
    record.checkpoint = job.checkpoint
    record.error = job.error
    # book_id is deliberately not reassigned: a job never moves between books


def _to_domain(record: IndexingJobRecord) -> IndexingJob:
    return IndexingJob(
        id=record.id,
        book_id=record.book_id,
        status=record.status,
        stage=record.stage,
        done=record.done,
        total=record.total,
        checkpoint=record.checkpoint,
        error=record.error,
    )

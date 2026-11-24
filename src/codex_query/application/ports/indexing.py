from collections.abc import Awaitable, Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from codex_query.domain.dtos.parsed_epub import ParsedDocumentDTO
from codex_query.domain.models.document import Chapter, TextChunk
from codex_query.domain.models.job import IndexingJob, Stage
from codex_query.domain.models.settings import Settings
from codex_query.domain.value_objects import QueueIndexJobRequest


class IndexingJobPort(Protocol):
    """Persistence contract for indexing job state and queue management."""

    async def add(self, job: IndexingJob) -> IndexingJob:
        """Persist a new indexing job.

        Args:
            job: Domain indexing job to store.

        Returns:
            Persisted domain indexing job with storage-assigned fields populated.
        """
        ...

    async def save(self, job: IndexingJob) -> None:
        """Persist state changes for an existing indexing job.

        Args:
            job: Domain indexing job with updated fields.

        Raises:
            JobNotFoundError: If no matching job exists in storage.
        """
        ...

    async def update_progress(
        self, job_id: int, *, stage: Stage, done: int, total: int, checkpoint: int
    ) -> None:
        """Update progress metrics for a running job.

        Args:
            job_id: Identifier of the target job.
            stage: Current execution stage.
            done: Completed item count in the current stage.
            total: Total expected item count in the current stage.
            checkpoint: Persistent progress offset or checkpoint value.

        Raises:
            JobNotFoundError: If the job is missing or not currently running.
        """
        ...

    async def get(self, job_id: UUID) -> IndexingJob | None:
        """Fetch an indexing job by its unique identifier.

        Args:
            job_id: Unique identifier of the target job.

        Returns:
            Matching indexing job when found, otherwise `None`.
        """
        ...

    async def get_next_queued(self) -> IndexingJob | None:
        """Fetch the next queued indexing job eligible for execution.

        Returns:
            Next queued indexing job, or `None` if no jobs are queued.
        """
        ...

    async def list_for_book(self, book_id: int) -> Sequence[IndexingJob]:
        """Fetch all indexing jobs associated with a book.

        Args:
            book_id: Identifier of the target book.

        Returns:
            Indexing jobs belonging to the book.
        """
        ...

    async def list_active(self) -> list[IndexingJob]:
        """Fetch all active indexing jobs outside terminal states.

        Returns:
            Jobs that are neither completed nor cancelled.
        """
        ...

    async def reset_running_to_queued(self) -> int:
        """Reset interrupted running jobs back to queued state.

        Returns:
            Number of jobs transitioned from running to queued.
        """
        ...

    async def delete(self, job_id: UUID) -> bool:
        """Delete an indexing job by its unique identifier.

        Args:
            job_id: Unique identifier of the job to delete.

        Returns:
            `True` if a matching job was deleted, `False` otherwise.
        """
        ...


class SettingsRepositoryPort(Protocol):
    def load(self) -> Settings | None: ...
    def save(self, settings: Settings) -> None: ...


class TextChunksPort(Protocol):
    def split(
        self,
        chapter: Chapter,
        series: str | None,
        book_title: str,
        max_chars: int = 1800,
        overlap: int = 250,
    ) -> Iterator[TextChunk]: ...

    def combine(self, chunks: Iterator[TextChunk], overlap: int = 250) -> str: ...


class JobRunnerPort(Protocol):
    def submit(self, job_id: UUID, work: Callable[[], Awaitable[None]]) -> None: ...
    async def cancel(
        self, job_id: UUID
    ) -> None: ...  # returns once the work has stopped
    async def cancel_all(self) -> None: ...
    def is_running(self, job_id: UUID) -> bool: ...


class DocumentParserPort(Protocol):
    async def read(
        self,
        path: Path,
        title: str | None = None,
        series: str | None = None,
        number: int | None = None,
        request: QueueIndexJobRequest | None = None,
    ) -> ParsedDocumentDTO: ...

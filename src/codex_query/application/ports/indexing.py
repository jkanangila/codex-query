from collections.abc import Awaitable, Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol

from codex_query.domain.dtos.parsed_epub import ParsedDocumentDTO
from codex_query.domain.models.document import Chapter, TextChunk
from codex_query.domain.models.job import IndexingJob, Stage
from codex_query.domain.models.settings import Settings


class IndexingJobPort(Protocol):
    async def add(self, job: IndexingJob) -> IndexingJob: ...
    async def save(self, job: IndexingJob) -> None: ...
    async def update_progress(
        self, job_id: int, *, stage: Stage, done: int, total: int, checkpoint: int
    ) -> None: ...
    async def get(self, job_id: int) -> IndexingJob | None: ...
    async def get_next_queued(self) -> IndexingJob | None: ...
    async def list_for_book(self, book_id: int) -> Sequence[IndexingJob]: ...
    async def list_active(
        self,
    ) -> list[IndexingJob]: ...  # everything not completed or cancelled
    async def reset_running_to_queued(self) -> int: ...
    async def delete(self, job_id: int) -> bool: ...


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
    def submit(self, job_id: int, work: Callable[[], Awaitable[None]]) -> None: ...
    async def cancel(
        self, job_id: int
    ) -> None: ...  # returns once the work has stopped
    def is_running(self, job_id: int) -> bool: ...


class IndexingJobEventsPort(Protocol):
    def publish(self, job: IndexingJob) -> None: ...
    def subscribe(
        self, listener: Callable[[IndexingJob], None]
    ) -> Callable[[], None]: ...


class DocumentParserPort(Protocol):
    async def read(self, path: Path) -> ParsedDocumentDTO: ...

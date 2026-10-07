from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from codex_query.domain.dtos.parsed_epub import ParsedDocumentDTO
from codex_query.domain.models.document import Answer, SearchHit, TextChunk
from codex_query.domain.models.job import IndexingJob
from codex_query.domain.models.settings import Settings


class IJobRepository(Protocol):
    async def add(self, job: IndexingJob) -> None: ...
    async def save(self, job: IndexingJob) -> None: ...
    async def get(self, job_id: int) -> IndexingJob | None: ...
    async def list_active(
        self,
    ) -> list[IndexingJob]: ...  # everything not completed or cancelled
    async def delete(self, job_id: int) -> None: ...


class ISettingsRepository(Protocol):
    def load(self) -> Settings | None: ...
    def save(self, settings: Settings) -> None: ...


class IVectorStore(Protocol):
    def upsert(
        self,
        series: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...
    def delete_chapter(self, series: str, book_id: str, chapter_href: str) -> None: ...
    def search(
        self, series: str, embedding: Sequence[float], limit: int
    ) -> list[SearchHit]: ...


class IEmbedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ILLMClient(Protocol):
    def answer(self, question: str, context: Sequence[SearchHit]) -> str: ...
    def ask(self, series: str, question: str, limit: int = 6) -> Answer: ...


class IChunker(Protocol): ...


class IJobRunner(Protocol):
    def submit(self, job_id: int, work: Callable[[], Awaitable[None]]) -> None: ...
    async def cancel(
        self, job_id: int
    ) -> None: ...  # returns once the work has stopped
    def is_running(self, job_id: int) -> bool: ...


class IJobEvents(Protocol):
    def publish(self, job: IndexingJob) -> None: ...
    def subscribe(
        self, listener: Callable[[IndexingJob], None]
    ) -> Callable[[], None]: ...


class IDocumentParser(Protocol):
    async def read(self, path: Path) -> ParsedDocumentDTO: ...

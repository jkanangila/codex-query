from dataclasses import dataclass
from pathlib import Path

from codex_query.domain.models.document import DocumentType
from codex_query.domain.models.job import Stage


@dataclass(frozen=True, slots=True)
class Source:
    """A passage retrieved from a book to ground an answer (a RAG "citation")."""

    chapter: str
    page: int | None
    score: float  # similarity score reported by the retriever (higher = closer)
    text: str

    @property
    def label(self) -> str:
        """Short human label, e.g. ``"Ch. 9 · p.118"`` (page omitted if unknown)."""
        return f"{self.chapter} · p.{self.page}" if self.page else self.chapter


@dataclass(frozen=True, slots=True)
class Progress:
    stage: Stage
    done: int
    total: int
    checkpoint: int  # chunks durably stored so far
    eta_s: float | None


@dataclass(frozen=True, slots=True)
class QueueIndexJobRequest:
    """What the "Add a book" form collects (already parsed by the UI).

    Attributes:
        title: Name to show in the library.
        source: Chosen ebook file, or ``None`` if the user hasn't picked one.
        series: Optional series name.
        number: Optional position in the series.
    """

    title: str
    source: Path
    series: str | None = None
    number: int | None = None
    language: str | None = None
    publisher: str | None = None
    description: str | None = None
    isbn: str | None = None
    published_year: int | None = None
    subjects: tuple[str, ...] = ()
    document_type: DocumentType = DocumentType.UNKNOWN

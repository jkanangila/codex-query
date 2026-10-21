from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path

CHUNK_OVERLAP = 250


class _Unset(Enum):
    UNSET = "unset"


UNSET = _Unset.UNSET
"""Sentinel for "leave this field alone" in partial updates.
 
Needed because ``None`` is a legitimate new value (e.g. clearing ``series``).
"""

type Maybe[T] = T | _Unset


class DocumentType(StrEnum):
    BOOK = "book"
    ARTICLE = "article"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Chapter:
    href: str
    title: str
    order: int
    content: str | None
    content_hash: str
    id: int | None = None
    book_id: int | None = None


@dataclass
class TextChunkMetadata:
    series: str | None
    book_id: int
    book_title: str
    chapter_href: str
    chapter_title: str
    chapter_order: int
    chunk_index: int


@dataclass(frozen=True, slots=True)
class TextChunk:
    id: int | None
    chapter_id: int
    series: str | None
    book_title: str
    chapter_title: str
    chunk_index: int
    text: str
    meta: TextChunkMetadata


@dataclass(frozen=True, slots=True)
class BookMetadata:
    """Descriptive, structural and indexing-state metadata of a book.

    Absent values are ``None`` / empty tuples, never placeholder strings.
    Decide how to render "unknown" in the UI layer, not here.

    Instances are immutable: when indexing progresses, use
    ``dataclasses.replace(meta, chunks=..., embedding_model=...)``.
    """

    # Structural
    file_type: str
    chapter_count: int

    # Descriptive
    language: str | None = None
    publisher: str | None = None
    description: str | None = None
    isbn: str | None = None
    published_year: int | None = None
    subjects: tuple[str, ...] = ()
    book_number: int | None = None
    document_type: DocumentType = DocumentType.UNKNOWN

    # Indexing state
    embedding_model: str | None = None
    embedding_provider: str | None = None
    chunks: int = 0
    chunk_size: int = 0
    chunk_overlap: int = CHUNK_OVERLAP


@dataclass(frozen=True, slots=True)
class Book:
    path: Path
    title: str
    authors: tuple[str, ...]
    file_hash: str
    size: int
    modified_ns: int
    meta: BookMetadata
    id: int | None = None
    series: str | None = None

    @property
    def author(self) -> str:
        return ", ".join(self.authors)


@dataclass(frozen=True, slots=True)
class BookUpdate:
    """Partial update of a book. Fields left as ``UNSET`` are not touched;
    ``None`` is a real value and clears nullable fields such as ``series``."""

    title: Maybe[str] = UNSET
    authors: Maybe[tuple[str, ...]] = UNSET
    series: Maybe[str | None] = UNSET
    path: Maybe[Path] = UNSET
    file_hash: Maybe[str] = UNSET
    size: Maybe[int] = UNSET
    modified_ns: Maybe[int] = UNSET
    meta: Maybe[BookMetadata] = UNSET

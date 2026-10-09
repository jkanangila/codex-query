from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass
class BookMetaData:
    file_type: str | None = None
    genre: str | None = None
    year: str | None = None
    chapter_count: int = 0


@dataclass(frozen=True, slots=True)
class Book:
    path: Path
    title: str
    author: str
    file_hash: str
    size: int
    modified_ns: int
    meta: BookMetaData
    id: int | None = None
    series: str | None = None


@dataclass
class BookUpdate:
    path: Path | None = None
    title: str | None = None
    author: str | None = None
    file_hash: str | None = None
    size: int | None = None
    modified_ns: int | None = None
    meta: dict[str, str | int] = field(default_factory=dict)

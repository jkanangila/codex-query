from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Chapter:
    href: str
    title: str
    order: int
    content: str
    content_hash: str
    id: int | None = None
    book_id: int | None = None


@dataclass
class TextChunkMetadata:
    series: str | None = None
    book_id: int | None = None
    book_title: str | None = None
    chapter_href: str | None = None
    chapter_title: str | None = None
    chapter_order: int | None = None
    chunk_index: int | None = None


@dataclass(frozen=True, slots=True)
class TextChunk:
    id: int | None
    chunk_hash: str
    chapter_id: int
    series: str | None
    book_title: str
    chapter_title: str
    chunk_index: int
    text: str
    meta: TextChunkMetadata


@dataclass
class BookMetaData:
    chapter_count: int | None = None
    file_type: str | None = None
    genre: str | None = None
    year: str | None = None


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


@dataclass(frozen=True, slots=True)
class SearchHit:
    text: str
    distance: float
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Answer:
    question: str
    answer: str
    sources: tuple[SearchHit, ...]

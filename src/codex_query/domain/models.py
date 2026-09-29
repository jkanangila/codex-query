from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

IndexStatus = Literal["pending", "indexing", "indexed", "failed"]


@dataclass(frozen=True, slots=True)
class Chapter:
    book_id: str
    href: str
    title: str
    order: int
    text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_id: str
    book_id: str
    chapter_href: str
    series: str
    book_title: str
    chapter_title: str
    chunk_index: int
    text: str
    metadata: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class Book:
    book_id: str
    path: Path
    title: str
    author: str
    file_hash: str
    size: int
    modified_ns: int
    chapters: tuple[Chapter, ...] = field(default_factory=tuple)


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

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.mutable import MutableDict
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from codex_query.domain.models.job import JobStatus, Stage

# Named constraints: required for Alembic batch migrations on SQLite
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enum[E: Enum](enum_cls: type[E]) -> SAEnum:
    def values(members: type[E]) -> list[str]:
        return [str(m.value) for m in members]

    return SAEnum(
        enum_cls,
        native_enum=False,
        values_callable=values,  # store values, not names
    )


_CASCADE = {"cascade": "all, delete-orphan", "passive_deletes": True}


class Book(SQLModel, table=True):
    __tablename__ = "book"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    series: str | None = Field(default=None, index=True)
    path: str = Field(unique=True)  # unique=True if one file == one book
    title: str
    author: str
    file_hash: str = Field(index=True)
    size: int
    modified_ns: int
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=MutableDict.as_mutable(JSON),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": utcnow},  # Python-side: no expired attribute
        nullable=False,
    )

    chapters: list["Chapter"] = Relationship(
        back_populates="book", sa_relationship_kwargs=dict(_CASCADE)
    )
    jobs: list["IndexingJob"] = Relationship(
        back_populates="book", sa_relationship_kwargs=dict(_CASCADE)
    )


class Chapter(SQLModel, table=True):
    __tablename__ = "chapter"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # also serves lookups by book_id (leftmost prefix)
        UniqueConstraint("book_id", "chapter_order", name="uq_chapter_book_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(foreign_key="book.id", ondelete="CASCADE")
    href: str
    title: str
    chapter_order: int
    content: str  # use defer(Chapter.content) in queries that don't need it
    content_hash: str

    book: Book = Relationship(back_populates="chapters")
    chunks: list["TextChunk"] = Relationship(
        back_populates="chapter", sa_relationship_kwargs=dict(_CASCADE)
    )


class TextChunk(SQLModel, table=True):
    __tablename__ = "text_chunk"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("chapter_id", "chunk_index", name="uq_chunk_chapter_index"),
    )

    id: int | None = Field(default=None, primary_key=True)
    chunk_hash: str = Field(index=True)
    chapter_id: int = Field(foreign_key="chapter.id", ondelete="CASCADE")
    chunk_index: int
    text: str
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=MutableDict.as_mutable(JSON),
    )

    chapter: Chapter | None = Relationship(back_populates="chunks")


class IndexingJob(SQLModel, table=True):
    __tablename__ = "indexing_job"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(
        foreign_key="book.id", ondelete="CASCADE", index=True
    )  # was str

    status: JobStatus = Field(
        default=JobStatus.QUEUED, sa_type=_enum(JobStatus), index=True, nullable=False
    )
    stage: Stage = Field(default=Stage.PARSE, sa_type=_enum(Stage), nullable=False)

    done: int = Field(default=0)
    total: int = Field(default=0)
    checkpoint: int = Field(default=0)

    error: str | None = Field(default=None, sa_type=Text)

    created_at: datetime = Field(
        default_factory=utcnow, sa_type=DateTime(timezone=True), nullable=False
    )
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    book: Book = Relationship(back_populates="jobs")

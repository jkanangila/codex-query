from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlmodel import Field, SQLModel


class BookRecord(SQLModel, table=True):
    __tablename__: ClassVar[Any] = "books"

    book_id: str = Field(primary_key=True)
    series: str = Field(index=True)
    path: str
    title: str
    author: str
    file_hash: str
    size: int
    modified_ns: int
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
    )


class ChapterRecord(SQLModel, table=True):
    __tablename__: ClassVar[Any] = "chapters"

    book_id: str = Field(
        foreign_key="books.book_id",
        primary_key=True,
    )
    href: str = Field(primary_key=True)
    title: str
    chapter_order: int
    content_hash: str
    status: str = Field(default="pending", index=True)
    error: str | None = Field(default=None)

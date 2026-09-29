from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from sqlite3.dbapi2 import Connection
from typing import override

from sqlalchemy import delete, event
from sqlalchemy.orm import configure_mappers
from sqlalchemy.pool import ConnectionPoolEntry
from sqlmodel import Session, SQLModel, col, create_engine, func, select

from codex_query.domain.models import Book as DomainBook
from codex_query.domain.models import Chapter as DomainChapter
from codex_query.domain.ports import IndexLedger
from codex_query.infrastructure.persistence.sqlmodel.models import (
    BookRecord,
    ChapterRecord,
)

logger = logging.getLogger(__name__)


class SQLModelIndexLedger(IndexLedger):
    """SQLModel-backed implementation of IndexLedger to track indexing status."""

    def __init__(self, path: Path) -> None:
        """Initialize SQLModel database engine and create required tables.

        Args:
            path: Path to the SQLite database file on disk.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{path}"
        self.engine = create_engine(db_url, echo=False)

        # Enable WAL mode, NORMAL synchronous setting, and Foreign Keys on
        # new connections
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: Connection, connection_record: ConnectionPoolEntry
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        # Create tables and indexes defined in SQLModel metadata
        SQLModel.metadata.create_all(self.engine)
        configure_mappers()

    @override
    def register_book(self, book: DomainBook, series: str) -> None:
        """Upsert book metadata and register chapters into the database.

        Args:
            book: Domain Book instance containing metadata and chapters.
            series: Unique identifier of the book series.
        """
        with Session(self.engine) as session:
            # Upsert book record
            existing_book = session.get(BookRecord, book.book_id)
            if existing_book:
                existing_book.series = series
                existing_book.path = str(book.path)
                existing_book.title = book.title
                existing_book.author = book.author
                existing_book.file_hash = book.file_hash
                existing_book.size = book.size
                existing_book.modified_ns = book.modified_ns
                existing_book.updated_at = datetime.now(UTC)
            else:
                existing_book = BookRecord(
                    book_id=book.book_id,
                    series=series,
                    path=str(book.path),
                    title=book.title,
                    author=book.author,
                    file_hash=book.file_hash,
                    size=book.size,
                    modified_ns=book.modified_ns,
                )
                session.add(existing_book)

            # Upsert chapter records
            for chapter in book.chapters:
                existing_chapter = session.get(
                    ChapterRecord, (chapter.book_id, chapter.href)
                )
                if existing_chapter:
                    existing_chapter.title = chapter.title
                    existing_chapter.chapter_order = chapter.order
                    # Reset status to pending only if content hash changed
                    if existing_chapter.content_hash != chapter.content_hash:
                        existing_chapter.content_hash = chapter.content_hash
                        existing_chapter.status = "pending"
                        existing_chapter.error = None
                else:
                    new_chapter = ChapterRecord(
                        book_id=chapter.book_id,
                        href=chapter.href,
                        title=chapter.title,
                        chapter_order=chapter.order,
                        content_hash=chapter.content_hash,
                        status="pending",
                    )
                    session.add(new_chapter)

            session.commit()
            logger.debug(
                "Ledger book registered: %s chapters=%d",
                book.book_id,
                len(book.chapters),
            )

    @override
    def chapters_to_index(
        self, book_id: str, chapters: Sequence[DomainChapter]
    ) -> list[DomainChapter]:
        """Filter and return chapters that require indexing or re-indexing.

        Args:
            book_id: Unique identifier for the target book.
            chapters: List of chapter instances to check.

        Returns:
            list[DomainChapter]: Chapters that are missing, changed, or not indexed.
        """
        result: list[DomainChapter] = []
        with Session(self.engine) as session:
            # Fetch all existing chapter records for this book in a single query
            statement = select(ChapterRecord).where(ChapterRecord.book_id == book_id)
            existing_records = {rec.href: rec for rec in session.exec(statement).all()}

            for chapter in chapters:
                rec = existing_records.get(chapter.href)
                if (
                    rec is None
                    or rec.content_hash != chapter.content_hash
                    or rec.status != "indexed"
                ):
                    result.append(chapter)

        logger.debug("Ledger pending chapters: book=%s count=%d", book_id, len(result))
        return result

    @override
    def mark_chapter_indexed(self, book_id: str, href: str, content_hash: str) -> None:
        """Mark a chapter as successfully indexed in the ledger.

        Args:
            book_id: Unique identifier for the target book.
            href: Relative path or resource identifier of the chapter.
            content_hash: SHA256 checksum of the indexed chapter content.
        """
        with Session(self.engine) as session:
            chapter = session.get(ChapterRecord, (book_id, href))
            if chapter:
                chapter.content_hash = content_hash
                chapter.status = "indexed"
                chapter.error = None
                session.add(chapter)
                session.commit()
                logger.debug("Ledger marked indexed: book=%s chapter=%s", book_id, href)

    @override
    def mark_chapter_failed(self, book_id: str, href: str, error: str) -> None:
        """Record an indexing failure error message for a chapter.

        Args:
            book_id: Unique identifier for the target book.
            href: Relative path or resource identifier of the chapter.
            error: Description of the failure or stack trace.
        """
        with Session(self.engine) as session:
            chapter = session.get(ChapterRecord, (book_id, href))
            if chapter:
                chapter.status = "failed"
                chapter.error = error[:2000]
                session.add(chapter)
                session.commit()
                logger.warning(
                    "Ledger marked failed: book=%s chapter=%s error=%s",
                    book_id,
                    href,
                    error,
                )

    @override
    def remove_stale_chapters(self, book_id: str, active_hrefs: set[str]) -> list[str]:
        """Delete records for chapters no longer present in the source book.

        Args:
            book_id: Unique identifier for the target book.
            active_hrefs: Set of valid chapter href identifiers currently in book.

        Returns:
            list[str]: Identifiers of deleted stale chapters.
        """
        with Session(self.engine) as session:
            statement = select(ChapterRecord.href).where(
                ChapterRecord.book_id == book_id
            )
            existing_hrefs = set(session.exec(statement).all())

            stale_hrefs = list(existing_hrefs - active_hrefs)
            if stale_hrefs:
                delete_stmt = (
                    delete(ChapterRecord)
                    .where(col(ChapterRecord.book_id) == book_id)
                    .where(col(ChapterRecord.href).in_(stale_hrefs))
                )
                session.exec(delete_stmt)
                session.commit()
                logger.info(
                    "Ledger removed stale chapters: book=%s count=%d",
                    book_id,
                    len(stale_hrefs),
                )

        return stale_hrefs

    @override
    def indexed_count(self, series: str) -> int:
        """Count the total number of successfully indexed chapters in a series.

        Args:
            series: Name or ID of the book series.

        Returns:
            int: Number of chapters with status 'indexed'.
        """
        with Session(self.engine) as session:
            statement = (
                select(func.count())
                .select_from(ChapterRecord)
                .join(BookRecord)
                .where(BookRecord.series == series)
                .where(ChapterRecord.status == "indexed")
            )
            return session.exec(statement).one()

    @override
    def close(self) -> None:
        """Dispose of the database engine and close pooled connections."""
        self.engine.dispose()

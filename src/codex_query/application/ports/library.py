from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Protocol

from codex_query.domain.models.document import Book, BookUpdate, Chapter, TextChunk


class IBookRepository(Protocol):
    """Persistence contract for book records."""

    async def get_all(self) -> list[Book]:
        """Fetch all books from storage.

        Returns:
            All stored books.
        """
        ...

    async def get_by_id(self, book_id: int) -> Book | None:
        """Fetch a single book by its primary identifier.

        Args:
            book_id: Primary identifier of the book.

        Returns:
            Matching book when found, otherwise `None`.
        """
        ...

    async def get_by_path(self, path: Path) -> Book | None:
        """Fetch a single book by its file path.

        Args:
            path: File system path of the book.

        Returns:
            First matching book when found, otherwise `None`.
        """
        ...

    async def register_book(self, book: Book) -> int:
        """Persist a new book record.

        Args:
            book: Book instance to register.

        Returns:
            Identifier assigned to the registered book.

        Raises:
            BookAlreadyExistsError: If a book with a conflicting identity or
                path already exists.
        """
        ...

    async def update(self, book_id: int, payload: BookUpdate) -> bool | None:
        """Apply a partial update to an existing book record.

        Args:
            book_id: Primary identifier of the book to update.
            payload: Partial update containing fields to apply.

        Returns:
            `True` if the book exists and the update was applied, or `None` if
            no book with `book_id` was found.
        """
        ...

    async def delete(self, book_id: int) -> bool:
        """Delete a book record by its primary identifier.

        Args:
            book_id: Primary identifier of the book to delete.

        Returns:
            `True` if a book was deleted, `False` otherwise.
        """
        ...


class IChapterRepository(Protocol):
    """Persistence contract for book chapter records."""

    async def register(self, book_id: int, chapter: Chapter) -> int:
        """Persist a new chapter under a book.

        Args:
            book_id: Primary key of the parent book.
            chapter: Domain chapter to insert.

        Returns:
            Primary key assigned to the persisted chapter.

        Raises:
            ChapterAlreadyExistsError: If a chapter with the same order already
                exists for the book.
        """
        ...

    async def upsert_bulk(
        self, book_id: int, chapters: Sequence[Chapter]
    ) -> Sequence[int]:
        """Insert or update chapters for a book in bulk.

        Args:
            book_id: Primary key of the target parent book.
            chapters: Domain chapters to insert or update.

        Returns:
            Chapter primary keys aligned with `chapters`.
        """
        ...

    async def get_by_id(self, chapter_id: int) -> Chapter | None:
        """Fetch a single chapter by its primary key.

        Args:
            chapter_id: Primary key of the chapter.

        Returns:
            Matching chapter when found, otherwise `None`.
        """
        ...

    async def get_all_for_book(
        self, book_id: int, after_order: int | None, limit: int
    ) -> Sequence[Chapter]:
        """Fetch chapters for a book ordered by chapter order.

        Args:
            book_id: Primary key of the parent book.
            after_order: Exclusive lower bound on chapter order for pagination.
            limit: Maximum number of chapters to return.

        Returns:
            Matching chapters in ascending order.
        """
        ...

    async def get_hashes_for_book(self, book_id: int) -> dict[int, str]:
        """Fetch content hashes keyed by chapter order for a book.

        Args:
            book_id: Primary key of the parent book.

        Returns:
            Mapping of chapter order to content hash.
        """
        ...

    async def delete_by_order(self, book_id: int, orders: Collection[int]) -> int:
        """Delete chapters matching the given order numbers for a book.

        Args:
            book_id: Primary key of the parent book.
            orders: Chapter order numbers to delete.

        Returns:
            Number of deleted chapter rows.
        """
        ...


class IChunkRepository(Protocol):
    """Persistence contract for chapter text chunks."""

    async def get_all_for_book(
        self, book_id: int, after_id: int | None, limit: int
    ) -> Sequence[TextChunk]:
        """Fetch text chunks for a book using keyset pagination on chunk ID.

        Args:
            book_id: Primary key of the target book.
            after_id: Exclusive lower bound on chunk ID for pagination.
            limit: Maximum number of text chunks to return.

        Returns:
            Matching text chunks ordered by chunk ID.
        """
        ...

    async def upsert_for_chapter(
        self, chapter_id: int, chunks: Sequence[TextChunk]
    ) -> Sequence[int]:
        """Insert or update text chunks for a chapter in bulk.

        Args:
            chapter_id: Primary key of the parent chapter.
            chunks: Text chunks to insert or update.

        Returns:
            Chunk primary keys aligned with `chunks`.
        """
        ...

    async def get_ids_for_chapter(self, chapter_id: int) -> Sequence[int]:
        """Fetch primary key IDs for all text chunks in a chapter.

        Args:
            chapter_id: Primary key of the target chapter.

        Returns:
            Chunk primary keys belonging to the chapter.
        """
        ...

    async def get_chunks_for_chapter(self, chapter_id: int) -> Sequence[TextChunk]:
        """Fetch all text chunks for a chapter ordered by chunk index.

        Args:
            chapter_id: Primary key of the target chapter.

        Returns:
            Text chunks for the chapter ordered by chunk index.
        """
        ...

    async def count_for_book(self, book_id: int) -> int:
        """Count total text chunks belonging to a book.

        Args:
            book_id: Primary key of the target book.

        Returns:
            Total number of text chunks for the book.
        """
        ...

    async def get_ids_for_orders(
        self, book_id: int, orders: Collection[int]
    ) -> Sequence[int]:
        """Fetch chunk IDs for chapters matching the given order numbers in a book.

        Args:
            book_id: Primary key of the parent book.
            orders: Chapter order numbers to match.

        Returns:
            Matching chunk primary keys across the specified chapters.
        """
        ...

    async def delete_for_chapter(self, chapter_id: int) -> int:
        """Delete all text chunks belonging to a chapter.

        Args:
            chapter_id: Primary key of the target chapter.

        Returns:
            Number of deleted chunk rows.
        """
        ...

"""Book search and library listing domain models and services.

This module provides data structures for grouping books into series and standalone
categories, as well as the SearchBooks service for filtering and organizing books
based on a query string.
"""

from dataclasses import dataclass

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.document import Book


@dataclass(frozen=True, slots=True)
class SeriesGroup:
    """Represents a group of books belonging to the same series."""

    name: str
    books: list[Book]

    @property
    def book_ids(self) -> list[int]:
        """Get a list of valid book IDs in this series.

        Returns:
            list[int]: A list of book IDs excluding None values.
        """
        return [b.id for b in self.books if b.id is not None]


@dataclass(frozen=True, slots=True)
class LibraryListing:
    """Represents an organized library view containing series groups and

    standalone books.
    """

    series: list[SeriesGroup]
    standalone: list[Book]

    @property
    def is_empty(self) -> bool:
        """Check whether the library listing contains no series and no standalone books.

        Returns:
            bool: True if both series and standalone lists are empty, False otherwise.
        """
        return not self.series and not self.standalone


class SearchBooks:
    """Service for searching and organizing books into series and standalone lists."""

    def __init__(self, logger_factory: LoggerFactoryPort) -> None:
        """Initialize the SearchBooks service.

        Args:
            logger_factory (LoggerFactoryPort): Factory for creating loggers.
        """
        self._logger = logger_factory.create(__name__)

    def __call__(self, books: list[Book], query: str = "") -> LibraryListing:
        """Filter and organize a collection of books based on a search query.

        Args:
            books (list[Book]): The collection of books to search and group.
            query (str, optional): The search string to filter books by title
                or series name. Defaults to "".

        Returns:
            LibraryListing: An organized listing containing matching series groups
                and standalone books.
        """
        self._logger.info(
            "Searching and grouping %d books with query: %r", len(books), query
        )

        needle = query.lower()
        matching = [
            b
            for b in books
            if needle in b.title.lower() or needle in (b.series or "").lower()
        ]
        self._logger.debug(
            "Found %d matching books for query: %r", len(matching), query
        )

        by_series: dict[str, list[Book]] = {}
        for book in matching:
            if book.series:
                by_series.setdefault(book.series, []).append(book)

        groups = [
            # Books without a number sort first (key 0); ``sort`` is stable so ties
            # keep their original relative order.
            SeriesGroup(name, sorted(items, key=lambda b: b.meta.book_number or 0))
            for name, items in sorted(by_series.items())
        ]
        standalone = [b for b in matching if not b.series]

        self._logger.info(
            "Created library listing with %d series groups and %d standalone books.",
            len(groups),
            len(standalone),
        )
        return LibraryListing(groups, standalone)

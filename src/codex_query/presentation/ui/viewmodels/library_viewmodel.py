"""Library view model module for managing UI state and user interactions.

Provides data structures and the view model implementation for displaying
books, series sections, and handling selections and additions within the
library UI component.
"""

from collections.abc import Callable
from dataclasses import dataclass

from codex_query.application.facade import UseCases
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.document import Book
from codex_query.presentation.ui.utils.formatting import book_subtitle
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject


@dataclass(frozen=True, slots=True)
class BookItem:
    """Represents a single row item in the book list.

    Attributes:
        id: The unique identifier of the book.
        title: The title of the book.
        subtitle: The formatted subtitle or description of the book.
        selected: Whether the book item is currently selected.
    """

    id: int
    title: str
    subtitle: str
    selected: bool


@dataclass(frozen=True, slots=True)
class SeriesSection:
    """Represents a series section grouping books under a series header.

    Attributes:
        name: The name of the book series.
        book_ids: A list of unique identifiers for books in this series.
        items: A list of BookItem instances belonging to this series.
    """

    name: str
    book_ids: list[int]
    items: list[BookItem]


@dataclass(frozen=True, slots=True)
class LibraryContent:
    """Contains all data needed by the view to render the library.

    Attributes:
        series: A list of series sections containing grouped books.
        standalone: A list of standalone book items not part of any series.
        is_empty: A flag indicating whether the library content is empty.
    """

    series: list[SeriesSection]
    standalone: list[BookItem]
    is_empty: bool


class LibraryViewModel(ObservableObject):
    """View model for managing library state, book filtering, and user actions.

    Attributes:
        _use_cases: Application use cases facade.
        _logger: Logger instance for recording events and actions.
        _books: Internal list of all available books.
        _on_add_book: Callback triggered when adding a new book.
        _on_select: Callback triggered when selecting books.
        _query: Current search query filter string.
        _selected_ids: List of currently selected book identifiers.
    """

    def __init__(
        self,
        use_cases: UseCases,
        on_select: Callable[[list[int]], None],
        on_add_book: Callable[[], None],
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initializes the LibraryViewModel.

        Args:
            use_cases: Application use cases facade.
            on_select: Callback function invoked with selected book IDs.
            on_add_book: Callback function invoked to add a new book.
            logger_factory: Factory to create the module logger.
        """
        super().__init__()
        self._use_cases = use_cases
        self._logger = logger_factory.create(__name__)

        self._books: list[Book] = []
        self._on_add_book = on_add_book
        self._on_select = on_select
        self._query = ""
        self._selected_ids: list[int] = []
        self._logger.debug("LibraryViewModel initialized.")

    # ── state ─────────────────────────────────────────────────────────────
    @property
    def books(self) -> list[Book]:
        """list[Book]: Gets a copy of all available books."""
        return list(self._books)

    @property
    def query(self) -> str:
        """str: Gets or sets the current search query filter."""
        return self._query

    @query.setter
    def query(self, value: str) -> None:
        if value != self._query:
            self._logger.debug(
                "Updating search query from %r to %r",
                self._query,
                value,
            )
            self._query = value
            self.notify_changed()  # the list must be filtered

    @property
    def selected_ids(self) -> list[int]:
        """list[int]: Gets a copy of currently selected book IDs."""
        return list(self._selected_ids)

    @property
    def content(self) -> LibraryContent:
        """LibraryContent: Computes and returns the structured library content."""
        self._logger.debug(
            "Computing library content for query=%r with %d books",
            self._query,
            len(self._books),
        )
        listing = self._use_cases.library.search_books(self.books, self.query)

        def item(book: Book) -> BookItem:
            assert book.id is not None
            return BookItem(
                book.id,
                book.title,
                book_subtitle(book),
                book.id in self._selected_ids,
            )

        series = [
            SeriesSection(g.name, g.book_ids, [item(b) for b in g.books])
            for g in listing.series
        ]
        content = LibraryContent(
            series, [item(b) for b in listing.standalone], listing.is_empty
        )
        self._logger.debug(
            "Library content computed: empty=%s, series_count=%d, standalone_count=%d",
            content.is_empty,
            len(content.series),
            len(content.standalone),
        )
        return content

    # ── commands (called by the view) ─────────────────────────────────────
    def select_book(self, book_id: int) -> None:
        """Selects a specific book by its identifier.

        Args:
            book_id: The unique identifier of the book to select.
        """
        self._logger.info("Selecting book with id=%d", book_id)
        self._on_select([book_id])

    def select_series(self, book_ids: list[int]) -> None:
        """Performs an 'Ask all' action for an entire book series.

        Args:
            book_ids: A list of book identifiers belonging to the series.
        """
        self._logger.info("Selecting series with book_ids=%s", book_ids)
        self._on_select(list(book_ids))

    def add_book(self) -> None:
        """Triggers the action to add a new book to the library."""
        self._logger.info("Triggering add book action.")
        self._on_add_book()

    # ── updates (called by the parent ViewModel) ──────────────────────────
    def set_books(self, books: list[Book]) -> None:
        """Updates the internal list of books and notifies observers.

        Args:
            books: The new list of books to set.
        """
        self._logger.debug("Setting books collection with %d items", len(books))
        self._books = list(books)
        self.notify_changed()

    def set_selection(self, ids: list[int]) -> None:
        """Updates the currently selected book identifiers and notifies observers.

        Args:
            ids: A list of selected book identifiers.
        """
        self._logger.debug("Setting selection ids=%s", ids)
        self._selected_ids = list(ids)
        self.notify_changed()

"""Application view model managing navigation, coordination, and sub-view models.

This module provides the core `AppViewModel` class, which acts as a central hub
coordinating the library, chat, indexing, and settings view models, as well as
managing application-wide state and event subscriptions.
"""

from __future__ import annotations

from codex_query.di.bootstrap import CompositionRoot
from codex_query.domain.models.job import IndexingJob
from codex_query.presentation.ui.viewmodels.chat_viewmodel import ChatViewModel
from codex_query.presentation.ui.viewmodels.events.observable import (
    ObservableObject,
)
from codex_query.presentation.ui.viewmodels.events.ui_events import UiEvents
from codex_query.presentation.ui.viewmodels.indexing_viewmodel import (
    IndexingViewModel,
)
from codex_query.presentation.ui.viewmodels.library_viewmodel import (
    LibraryViewModel,
)
from codex_query.presentation.ui.viewmodels.navigation import Tab
from codex_query.presentation.ui.viewmodels.settings_viewmodel import (
    SettingsViewModel,
)


class AppViewModel(ObservableObject):
    """Central application view model coordinating sub-views and navigation.

    Attributes:
        composition: The application composition root.
        events: Global UI event emitter.
        library: View model for managing books and library state.
        chat: View model for interacting with the chat interface.
        indexing: View model for managing indexing jobs.
        settings: View model for managing application settings.
        _logger: Contextual component logger instance.
        _tab: Currently active navigation tab.
    """

    def __init__(self, composition: CompositionRoot) -> None:
        """Initialize the AppViewModel with dependencies and sub-view models.

        Args:
            composition: The dependency injection root.
        """
        super().__init__()
        self._logger = composition.logger_factory.create(__name__)
        self.composition = composition
        self.events = UiEvents()
        self._tab = Tab.LIBRARY

        self._logger.info("Initializing AppViewModel sub-view models...")
        self.library = LibraryViewModel(
            composition.use_cases,
            events=self.events,
            on_select=self.select_book,
            logger_factory=composition.logger_factory,
        )
        self.chat = ChatViewModel(
            composition.use_cases, self.events, composition.logger_factory
        )
        self.indexing = IndexingViewModel(
            composition.use_cases,
            composition.job_events,
            self.events,
            composition.logger_factory,
        )
        self.settings = SettingsViewModel(
            self.composition.use_cases.settings,
            self.events,
            composition.logger_factory,
            on_reindex=self.indexing.reindex,
        )

        self.indexing.job_completed.subscribe(self._on_job_completed)
        self.events.tab_navigation_requested.subscribe(self.navigate_to_tab)
        self._logger.debug("AppViewModel initialization completed successfully.")

    @classmethod
    async def create(cls, composition: CompositionRoot) -> AppViewModel:
        """Create and asynchronously initialize an AppViewModel instance.

        Restores interrupted indexing jobs and loads the initial book list from
        persistence.

        Args:
            composition: The dependency injection root.

        Returns:
            An initialized instance of AppViewModel.
        """
        vm = cls(composition)
        vm._logger.info("Restoring indexing jobs and loading books from database...")

        # Restore and display interrupted indexing jobs from persistence.
        await vm.indexing.restore()
        books = await vm.composition.use_cases.library.list_books()

        vm.library.set_books(list(books))
        vm._logger.info(
            f"AppViewModel successfully created with {len(list(books))} books."
        )

        return vm

    @property
    def tab(self) -> Tab:
        """Get the currently active navigation tab.

        Returns:
            The active `Tab` enum value.
        """
        return self._tab

    # ── Navigation ────────────────────────────────────────────────────────
    def navigate(self, tab: Tab) -> None:
        """Navigate to a specified application tab and notify listeners.

        Args:
            tab: The target tab to switch to.
        """
        self._logger.debug(f"Navigating from tab {self._tab} to tab {tab}")
        self._tab = tab
        self.notify_changed()

    def navigate_to_tab(self, tab: Tab) -> None:
        """Switch the current view to the specified tab.

        Args:
            tab: The target tab to switch to.
        """
        self.navigate(tab)

    # ── coordination ──────────────────────────────────────────────────────
    def select_book(self, book_id: int) -> None:
        """Make the specified book ID the question scope.

        Highlights the book, resets the chat scope, and prepares for querying.

        Args:
            book_id: The unique identifier of the selected book.
        """
        self._logger.debug(f"Selecting book with ID: {book_id}")
        self.library.set_selection(book_id)
        selected = next((b for b in self.library.books if b.id == book_id), None)
        if selected is None:
            self._logger.warning(
                f"Failed to find book with ID {book_id} during selection."
            )
            self.events.toast.emit(
                "Error! Cannot find data corresponding to the requested book. "
                "Delete then re-index the book"
            )
            return

        self._logger.info(f"Setting chat scope to book: '{selected.title}'")
        self.chat.set_scope(selected)

    async def _on_job_completed(self, job: IndexingJob) -> None:
        """Handle completion of an indexing job by refreshing books and notifying user.

        Args:
            job: The completed indexing job.
        """
        self._logger.info(f"Indexing job completed for job ID: {job.id}")
        books = await self.composition.use_cases.library.list_books()
        self.library.set_books(list(books))

        book = next((b for b in books if b.id == job.id), None)
        if book is not None:
            self._logger.info(f"Book '{book.title}' is ready for queries.")
            self.events.toast.emit(f"“{book.title}” is ready to ask")
        else:
            self._logger.error(
                f"Job ({job.id}) completed but no matching "
                "book was found in the database."
            )
            self.events.toast.emit(
                f"Error! Job ({job.id}) completed but no book was added to the database"
            )

"""Cross-cutting UI requests that ViewModels make but only a view can fulfil."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from codex_query.application.events.signal import Signal
from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    StaleBook,
)
from codex_query.domain.models.rag import SourceRef
from codex_query.presentation.ui.viewmodels.navigation import Tab


@dataclass(frozen=True, slots=True)
class EmbeddingChangeRequest:
    """Everything the re-index confirmation dialog needs, and nothing else.

    The callbacks belong to the presentation layer (they are ViewModel commands), so
    they travel with this request rather than with a domain object.
    """

    stale_books: list[StaleBook]
    """Books that must be re-indexed if the user confirms."""
    confirm: Callable[[], Awaitable[None]]
    """Apply the staged change."""
    cancel: Callable[[], None]
    """Discard the staged change and revert the form."""


class UiEvents:
    """Signals shared by all ViewModels and consumed by the application shell view.

    A ViewModel must not show a snack bar or a dialog itself (that needs Flet), so
    it *asks* by emitting a signal; ``FolioApp`` subscribes and does the drawing.
    """

    def __init__(self) -> None:
        # Show a transient message.
        self.toast: Signal[str] = Signal()

        # Show the full text of a retrieved passage.
        self.source_requested: Signal[SourceRef] = Signal()

        # Ask the user to confirm an embedding model or provider change.
        # Such a change requires re-indexing the affected books.
        self.embedding_reindex_requested: Signal[EmbeddingChangeRequest] = Signal()

        # navigate to specified tab
        self.tab_navigation_requested: Signal[Tab] = Signal()

"""Cross-cutting UI requests that ViewModels make but only a view can fulfil."""

from codex_query.domain.value_objects import PendingEmbeddingChange, Source
from codex_query.presentation.ui.viewmodels.observable import Signal


class UiEvents:
    """Signals shared by all ViewModels and consumed by the application shell view.

    A ViewModel must not show a snack bar or a dialog itself (that needs Flet), so
    it *asks* by emitting a signal; ``FolioApp`` subscribes and does the drawing.
    """

    def __init__(self) -> None:
        self.toast: Signal[str] = Signal()
        """Show a transient message."""
        self.source_requested: Signal[Source] = Signal()
        """Show the full text of a retrieved passage."""
        self.embedding_reindex_requested: Signal[PendingEmbeddingChange | None] = (
            Signal()
        )

        """Show a dialog asking to confirm the change of either the embedding
        model or provider, since that wil required reindexing of affected books."""

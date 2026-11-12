"""ViewModel for the 'Sources for last answer' panel."""

from dataclasses import dataclass

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.rag import SourceRef
from codex_query.presentation.ui.utils.formatting import source_heading
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject


@dataclass(frozen=True, slots=True)
class SourceCard:
    """Represents a formatted passage displayed in the sources panel.

    Attributes:
        heading: The formatted heading of the source reference.
        text: The excerpt text of the source reference.
    """

    heading: str
    text: str


class SourcesViewModel(ObservableObject):
    """ViewModel responsible for holding and managing passages that grounded
    the most recent answer.

    Attributes:
        _logger: Logger instance for recording view model events.
        _cards: Internal list of currently displayed source cards.
    """

    def __init__(self, logger_factory: LoggerFactoryPort) -> None:
        """Initializes the SourcesViewModel.

        Args:
            logger_factory: Factory used to create a logger for this view model.
        """
        super().__init__()
        self._logger = logger_factory.create(__name__)
        self._cards: list[SourceCard] = []

    @property
    def cards(self) -> list[SourceCard]:
        """Get a copy of the current source cards.

        Returns:
            A new list containing the active `SourceCard` instances.
        """
        return list(self._cards)

    def show(self, items: list[SourceRef]) -> None:
        """Replace the panel contents with new source references.

        Args:
            items: A list of source references to be displayed.
        """
        self._cards = [SourceCard(source_heading(s), s.excerpt) for s in items]
        self._logger.info("Updated sources panel with %d card(s).", len(self._cards))
        self.notify_changed()

    def clear(self) -> None:
        """Clear all source cards from the panel."""
        self._cards = []
        self._logger.debug("Cleared all source cards from sources panel.")
        self.notify_changed()

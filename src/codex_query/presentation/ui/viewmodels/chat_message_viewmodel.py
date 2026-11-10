"""Chat message view model for managing message state, streaming, and sources."""

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.chat import Role
from codex_query.domain.models.rag import SourceRef
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject
from codex_query.presentation.ui.viewmodels.events.ui_events import UiEvents


class ChatMessageViewModel(ObservableObject):
    """One message. Assistant messages change while the answer streams in.

    Each message is its own observable so a token only redraws *its* bubble, not
    the whole conversation.
    """

    def __init__(
        self,
        role: Role,
        logger_factory: LoggerFactoryPort,
        events: UiEvents,
        text: str = "",
    ) -> None:
        """Initialize the chat message view model.

        Args:
            role: The role of the message author (e.g., user, assistant).
            logger_factory: Factory port for instantiating class loggers.
            events: UI event dispatcher for handling shell interactions.
            text: Initial text content of the message. Defaults to "".
        """
        super().__init__()
        self.role = role
        self._logger = logger_factory.create(__name__)
        self._events = events
        self._text = text
        self._sources: list[SourceRef] = []
        self._error: str | None = None
        self._logger.debug(
            "Initialized ChatMessageViewModel with role=%s",
            role.value if hasattr(role, "value") else role,
        )

    @property
    def text(self) -> str:
        """Markdown to display (error text already applied).

        Returns:
            str: The message text, appended with error formatting if present.
        """
        if self._error is not None:
            return f"{self._text}\n\n*Error: {self._error}*"
        return self._text

    def set_text(self, value: str) -> None:
        """Set the message text directly and notify observers.

        Args:
            value: The new complete text content.
        """
        self._text = value
        self._logger.debug("Updated message text content")
        self.notify_changed()

    @property
    def raw_text(self) -> str:
        """The raw underlying message text without appended error markers.

        Returns:
            str: The unformatted raw text.
        """
        return self._text

    @property
    def sources(self) -> list[SourceRef]:
        """Passages cited by this answer (empty for user messages).

        Returns:
            list[SourceRef]: Cited source references.
        """
        return self._sources

    @property
    def is_waiting(self) -> bool:
        """Check if assistant message has nothing to show yet (no token, no error).

        Returns:
            bool: True if waiting for the first response token, False otherwise.
        """
        return self.role is Role.ASSISTANT and not self._text and self._error is None

    # ── commands (vm -> view) ─────────────────────────────────────────────
    def append_token(self, token: str) -> None:
        """Append a newly streamed token to the message text and notify observers.

        Args:
            token: The text chunk received from the language model.
        """
        self._text += token
        self._logger.debug("Appended token of length %d", len(token))
        self.notify_changed()

    def finish(self, text: str, sources: list[SourceRef]) -> None:
        """Mark the answer as complete and attach final text and sources.

        Args:
            text: The final assembled response text.
            sources: The collection of sources cited by the response.
        """
        self._text = text
        self._sources = sources
        self._logger.info(
            "Completed message generation with %d source(s)", len(sources)
        )
        self.notify_changed()

    def set_error(self, error: Exception | str) -> None:
        """Keep the partial answer and append the error below it.

        Args:
            error: The error message or exception that occurred during streaming.
        """
        self._error = str(error)
        self._logger.error("Set error state on message: %s", self._error)
        self.notify_changed()

    def open_source(self, source: SourceRef) -> None:
        """Request the shell to show the passage when a source chip is tapped.

        Args:
            source: The source reference selected by the user.
        """
        self._logger.debug("Source requested for opening: %s", source)
        self._events.source_requested.emit(source)

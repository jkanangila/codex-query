"""Chat view model for managing conversation history, book scope, and streaming Q&A."""

from contextlib import aclosing

from codex_query.application.facade import UseCases
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.chat import ChatMessage, Role
from codex_query.domain.models.document import Book
from codex_query.domain.models.rag import (
    Completed,
    Failed,
    SourceRef,
    SourcesFound,
    TextDelta,
)
from codex_query.presentation.ui.utils.formatting import scope_title
from codex_query.presentation.ui.viewmodels.chat_message_viewmodel import (
    ChatMessageViewModel,
)
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject
from codex_query.presentation.ui.viewmodels.events.ui_events import UiEvents
from codex_query.presentation.ui.viewmodels.sources_viewmodel import SourcesViewModel

NO_BOOK_MESSAGE = "Pick a book first"


class ChatViewModel(ObservableObject):
    """A conversation about the currently selected book(s).

    ``notify_changed`` fires when the *list* of messages, the title or the input
    text is reset; token-by-token changes are announced by the individual
    :class:`ChatMessageViewModel`.

    Attributes:
        _use_cases: Application use cases facade.
        ui_events: UI event dispatcher for handling shell interactions.
        _logger_factory: Factory port for instantiating class loggers.
        _logger: Contextual logger instance.
        _book_id: Unique identifier of the currently scoped book, if any.
        _messages: List of chat message view models in the conversation.
        _busy: Flag indicating whether a question is currently being processed.
        _title: Formatted scope title representing the active book or context.
        question: Text of the input box, written by the view as the user types.
        sources: Child ViewModel for the side panel, filled from each answer's sources.
    """

    def __init__(
        self,
        use_cases: UseCases,
        ui_events: UiEvents,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initializes the ChatViewModel.

        Args:
            use_cases: Application use cases facade.
            ui_events: UI event dispatcher for handling shell interactions.
            logger_factory: Factory port for instantiating class loggers.
        """
        super().__init__()
        self._use_cases = use_cases
        self.ui_events = ui_events
        self._logger_factory = logger_factory
        self._logger = logger_factory.create(__name__)

        self._book_id: int | None = None
        self._messages: list[ChatMessageViewModel] = []
        self._busy = False
        self._title = scope_title([])
        self.question = ""
        """Text of the input box. Written by the view as the user types (no redraw)."""
        self.sources = SourcesViewModel(logger_factory)
        """Child ViewModel for side panel; filled from each answer's Sources event."""
        self._logger.debug("Initialized ChatViewModel")

    @property
    def title(self) -> str:
        """The scope title representing active books or context.

        Returns:
            The formatted scope title string.
        """
        return self._title

    @property
    def messages(self) -> list[ChatMessageViewModel]:
        """The list of chat message view models in the conversation.

        Returns:
            Active message view models.
        """
        return self._messages

    @property
    def is_busy(self) -> bool:
        """Whether a question is currently being processed and streamed.

        Returns:
            True if busy, False otherwise.
        """
        return self._busy

    @property
    def has_scope(self) -> bool:
        """Whether at least one book is selected.

        Returns:
            True if a book scope is active, False otherwise.
        """
        return bool(self._book_id)

    # ── commands (vm -> view) ─────────────────────────────────────────────
    def set_scope(self, book: Book) -> None:
        """Ask about ``book`` from now on, and start a fresh conversation.

        Args:
            book: The book instance to scope the conversation to.
        """
        self._book_id = book.id
        self._title = book.title
        self._messages = []
        self.sources.clear()
        self._logger.info("Set chat scope to book ID %s (%s)", book.id, book.title)
        self.notify_changed()

    def reset(self) -> None:
        """Start a fresh conversation about the same book."""
        if self._busy:
            self._logger.warning("Attempted to reset chat while busy; ignored")
            return
        self._messages = []
        self.question = ""
        self.sources.clear()
        self._logger.info("Reset conversation history for current scope")
        self.notify_changed()

    async def send(self) -> None:
        """Send :attr:`question` and stream the answer into a new assistant message."""
        question = self.question.strip()
        if not question or self._busy:
            return
        if not self.has_scope:
            self._logger.warning("Attempted to send question without active book scope")
            self.ui_events.toast.emit(NO_BOOK_MESSAGE)
            return

        self._busy = True
        self.question = ""
        self._logger.info("Sending question (length: %d)", len(question))

        user = ChatMessageViewModel(
            role=Role.USER,
            logger_factory=self._logger_factory,
            events=self.ui_events,
            text=question,
        )
        answer = ChatMessageViewModel(
            role=Role.ASSISTANT,
            logger_factory=self._logger_factory,
            events=self.ui_events,
        )
        history = [
            ChatMessage(role=m.role, content=m.raw_text)
            for m in self._messages
            if m.role == Role.USER
        ]
        self._messages = [*self._messages, user, answer]
        self.sources.clear()  # don't leave previous answer's sources up
        self.notify_changed()

        pending_sources: list[SourceRef] = []
        try:
            assert self._book_id is not None
            async with aclosing(
                self._use_cases.chat.ask_question(self._book_id, question, history)
            ) as events:
                async for event in events:
                    match event:
                        case SourcesFound(sources):
                            pending_sources = sources
                            self._logger.debug(
                                "Received %d source(s) for answer", len(sources)
                            )
                        case TextDelta(token):
                            answer.append_token(token)
                        case Completed(full):
                            answer.finish(full, pending_sources)
                            self.sources.show(pending_sources)
                            self._logger.info("Answer stream completed successfully")
                        case Failed():
                            error_msg = f"[{event.kind}] {event.message}"
                            answer.set_error(error_msg)
                            self._logger.error(
                                "Answer generation failed: %s", error_msg
                            )
        except Exception as e:
            answer.set_error(e)
            self._logger.exception("Exception occurred during chat streaming")
        finally:
            self._busy = False
            self.notify_changed()

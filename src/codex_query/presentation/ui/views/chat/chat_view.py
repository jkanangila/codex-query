"""Chat screen view module for asking questions and watching answers stream in."""

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.viewmodels.chat_message_viewmodel import (
    ChatMessageViewModel,
)
from codex_query.presentation.ui.viewmodels.chat_viewmodel import ChatViewModel
from codex_query.presentation.ui.views.chat.message_bubble import MessageBubble
from codex_query.presentation.ui.views.chat.sources_panel import SourcesPanel


class ChatView:
    """Chat screen view for asking questions and watching the answer stream in.

    Attributes:
        _vm: The chat view model instance.
        _logger: Contextual component logger instance.
        _logger_factory: Factory port for creating sub-component loggers.
        _shown: List of message view models that currently have rendered bubbles.
        sources: Sources panel UI component (mounted by the shell).
        header: Flet text control displaying the active scope title.
        log: ListView control displaying conversation message bubbles.
        input: TextField control for typing questions.
        reset_button: IconButton to clear/reset the current conversation.
        root: Root container Flet control holding the complete chat screen layout.
    """

    def __init__(self, vm: ChatViewModel, logger_factory: LoggerFactoryPort) -> None:
        """Initializes the ChatView.

        Args:
            vm: The chat view model instance.
            logger_factory: Factory port for creating loggers.
        """
        self._vm = vm
        self._logger = logger_factory.create(__name__)
        self._logger_factory = logger_factory

        # messages that already have a bubble
        self._shown: list[ChatMessageViewModel] = []
        # mounted by the shell (AppShell), not by this view
        self.sources = SourcesPanel(vm.sources, logger_factory)
        self.header = ft.Text(vm.title, size=16, weight=ft.FontWeight.BOLD, expand=True)
        self.log = ft.ListView(expand=True, spacing=8, auto_scroll=True, padding=12)
        self.input = ft.TextField(
            hint_text="Ask about this book...",
            expand=True,
            on_change=self._on_input,
            on_submit=self._on_send,
        )
        self.reset_button = ft.IconButton(
            icon=ft.Icons.DELETE_SWEEP,
            tooltip="Clear chat",
            on_click=self._on_reset,
        )
        self.root = ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    content=ft.Row([self.header, self.reset_button]), padding=12
                ),
                ft.Divider(height=1),
                self.log,
                ft.Container(
                    padding=8,
                    content=ft.Row(
                        [
                            self.input,
                            ft.IconButton(
                                icon=ft.Icons.ARROW_UPWARD, on_click=self._on_send
                            ),
                        ]
                    ),
                ),
            ],
        )
        vm.subscribe(self.render)
        self.render()
        self._logger.debug("ChatView initialized successfully.")

    # ── view -> viewModel ─────────────────────────────────────────────────
    def _on_input(self, _e: ft.Event[ft.TextField]) -> None:
        """Handles input text changes by updating the view model question string.

        Args:
            _e: The Flet text field change event payload.
        """
        self._vm.question = self.input.value or ""

    def _on_reset(self, _e: ft.Event[ft.IconButton]) -> None:
        """Triggers conversation reset on the view model.

        Args:
            _e: The Flet button click event payload.
        """
        self._logger.debug("Reset button clicked; clearing chat.")
        self._vm.reset()

    async def _on_send(
        self, _e: ft.Event[ft.TextField] | ft.Event[ft.IconButton]
    ) -> None:
        """Submits the current question to the view model for streaming response.

        Args:
            _e: The Flet event payload from the text field submit or send button.
        """
        # Make sure the ViewModel has the latest text even if no on_change fired yet
        # (e.g. the user pressed Enter right after a paste).
        self._vm.question = self.input.value or ""
        self._logger.debug("Send action triggered.")
        await self._vm.send()

    # ── viewmodel -> view ────────────────────────────────_________________
    def render(self) -> None:
        """Synchronizes title, message list, and input box with the ViewModel."""
        self._logger.debug("Rendering ChatView from ViewModel state.")
        self.header.value = self._vm.title
        if self.input.value != self._vm.question:
            self.input.value = self._vm.question
        self.reset_button.disabled = self._vm.is_busy or not self._vm.messages
        self._sync_bubbles()
        safe_update(self.root)

    def _sync_bubbles(self) -> None:
        """Makes the log show exactly the ViewModel's messages.

        Messages are append-only within a conversation, so normally only the new tail
        needs bubbles; if the list was replaced (new book scope) start over.
        """
        messages = self._vm.messages
        still_valid = len(messages) >= len(self._shown) and all(
            a is b for a, b in zip(self._shown, messages, strict=False)
        )
        if not still_valid:
            self._logger.debug(
                "Message list replaced or reset; rebuilding all bubbles."
            )
            self.log.controls = []
            self._shown = []
        for message in messages[len(self._shown) :]:
            self.log.controls.append(MessageBubble(message, self._logger_factory).root)
            self._shown.append(message)
        self._logger.debug(
            "Synchronized message bubbles, total shown: %d", len(self._shown)
        )

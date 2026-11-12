"""One chat message bubble UI component."""

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.chat import Role
from codex_query.domain.models.rag import SourceRef
from codex_query.presentation.ui.utils.flet_helpers import bind, safe_update
from codex_query.presentation.ui.viewmodels.chat_message_viewmodel import (
    ChatMessageViewModel,
)


class MessageBubble:
    """A chat message bubble bound to a :class:`ChatMessageViewModel`.

    User bubbles are static. Assistant bubbles redraw their Markdown on every token and
    their source chips when the answer's sources arrive.

    Attributes:
        _vm: The chat message view model providing state and content.
        _logger: Logger instance for recording message bubble events.
        _answer: Flet Markdown control for displaying assistant response text.
        _waiting: Flet Row showing loading status when waiting for tokens.
        _chips: Flet Row containing source citation action buttons.
        _chips_for: Cached reference to check if sources need updating.
        root: Root Flet Row representing the complete bubble layout container.
    """

    def __init__(
        self, vm: ChatMessageViewModel, logger_factory: LoggerFactoryPort
    ) -> None:
        """Initializes the MessageBubble.

        Args:
            vm: The chat message view model instance to bind to.
            logger_factory: Factory used to create a logger for this component.
        """
        self._vm = vm
        self._logger = logger_factory.create(__name__)

        user = vm.role is Role.USER
        self._answer = ft.Markdown(vm.text, selectable=True, visible=not vm.is_waiting)
        self._waiting = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                ft.Text("Thinking…", italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=8,
            visible=vm.is_waiting,
        )
        self._chips = ft.Row(wrap=True, spacing=4)
        self._chips_for: list[SourceRef] | None = None
        content: ft.Control = (
            ft.Text(vm.text, selectable=True, color=ft.Colors.ON_PRIMARY)
            if user
            else ft.Column([self._waiting, self._answer, self._chips], tight=True)
        )
        bubble = ft.Container(
            content=content,
            padding=10,
            border_radius=14,
            expand=True,
            bgcolor=(
                ft.Colors.PRIMARY if user else ft.Colors.SURFACE_CONTAINER_HIGHEST
            ),
        )
        gap = ft.Container(width=40)  # keeps bubbles off the opposite edge
        self.root = ft.Row([gap, bubble] if user else [bubble, gap])
        if not user:
            vm.subscribe(self.render)
            self._logger.debug("Subscribed MessageBubble to assistant view model.")

    def render(self) -> None:
        """Renders the assistant message bubble updates based on view model changes.

        Updates the waiting status, streamed markdown text, and source reference chips
        safely whenever the underlying view model changes.
        """
        waiting = self._vm.is_waiting
        if self._waiting.visible != waiting:
            self._waiting.visible = waiting
            self._answer.visible = not waiting
            safe_update(self._waiting)
            self._logger.debug("Toggled waiting state visibility to %s", waiting)

        if not waiting:
            self._answer.value = self._vm.text
            safe_update(self._answer)

        # Chips only change when the answer completes, not on every token.
        if self._vm.sources is not self._chips_for:
            self._chips_for = self._vm.sources
            self._chips.controls = [
                ft.TextButton(content=s.label, on_click=bind(self._vm.open_source, s))
                for s in self._vm.sources
            ]
            safe_update(self._chips)
            self._logger.debug(
                "Updated source chips with %d reference(s)", len(self._vm.sources)
            )

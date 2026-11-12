"""Flet UI component for the 'Sources for last answer' panel."""

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.viewmodels.sources_viewmodel import SourcesViewModel


class SourcesPanel:
    """Right-hand panel (desktop only) displaying source passages for the last answer.

    Bound to a :class:`SourcesViewModel`. The shell decides whether to mount it
    (expanded layout only) and toggles ``root.visible`` so it only shows on the chat
    screen.

    Attributes:
        _vm: The sources view model providing state and card data.
        _logger: Logger instance for recording UI panel events.
        col: Flet Column containing the rendered source cards.
        root: Root Flet Container encapsulating the entire sources panel.
    """

    def __init__(self, vm: SourcesViewModel, logger_factory: LoggerFactoryPort) -> None:
        """Initializes the SourcesPanel.

        Args:
            vm: The view model instance to bind to.
            logger_factory: Factory used to create a logger for this UI component.
        """
        self._vm = vm
        self._logger = logger_factory.create(__name__)

        self.col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self.root = ft.Container(
            width=280,
            padding=12,
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.Text(
                        "Sources for last answer",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                    ),
                    self.col,
                ],
            ),
        )
        vm.subscribe(self.render)
        self._logger.debug("Initialized SourcesPanel and subscribed to view model.")

    def render(self) -> None:
        """Renders source cards into the column based on the view model's state.

        Updates the UI controls list with a formatted container card for each
        retrieved passage and safely updates the column UI.
        """
        self._logger.debug(
            "Rendering sources panel with %d card(s).", len(self._vm.cards)
        )
        self.col.controls = [
            ft.Container(
                padding=10,
                border_radius=10,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                content=ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(card.heading, weight=ft.FontWeight.BOLD, size=12),
                        ft.Text(
                            card.text,
                            selectable=True,
                            size=12,
                            max_lines=6,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                ),
            )
            for card in self._vm.cards
        ]
        safe_update(self.col)

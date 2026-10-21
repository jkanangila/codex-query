"""Job card view module for rendering interactive job progress cards in Flet.

This module defines the `JobCardView` class, which bridges the `JobCardViewModel`
and the Flet UI framework. It manages UI components for monitoring and controlling
background or asynchronous jobs, including progress bars, stage indicators, and
control buttons.
"""

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.viewmodels.job_card_viewmodel import (
    JobCardViewModel,
)

TEXT_SMALL = 11
PADDING = 12
BORDER_RADIUS = 12


class JobCardView:
    """UI component representing an individual job card with status and controls.

    Observes a `JobCardViewModel` to dynamically update its view components,
    including stage progress, progress bar, counters, and action buttons.
    """

    def __init__(self, vm: JobCardViewModel, logger_factory: LoggerFactoryPort) -> None:
        """Initialize the job card view and subscribe to view model updates.

        Args:
            vm: The `JobCardViewModel` instance containing the job's state.
            logger_factory: Factory to produce a contextual logger for this view.
        """
        self._logger = logger_factory.create(__name__)

        self._logger.debug("Initializing JobCardView with title: %s", vm.title)
        self._vm = vm
        self.title = ft.Text(vm.title, weight=ft.FontWeight.BOLD)
        self.sub = ft.Text(size=TEXT_SMALL)
        self.stages = ft.Row(
            [ft.Text(s.label, size=TEXT_SMALL, expand=True) for s in vm.stages]
        )
        self.bar = ft.ProgressBar(value=0)
        self.counter = ft.Text(size=TEXT_SMALL)
        self.toggle = ft.OutlinedButton(content="Pause", on_click=self._on_toggle)
        self.root = ft.Container(
            padding=PADDING,
            border_radius=BORDER_RADIUS,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            content=ft.Column(
                spacing=6,
                controls=[
                    self.title,
                    self.sub,
                    self.stages,
                    self.bar,
                    self.counter,
                    ft.Row(
                        [
                            self.toggle,
                            ft.IconButton(
                                icon=ft.Icons.CLOSE, on_click=self._on_cancel
                            ),
                        ]
                    ),
                ],
            ),
        )
        self._apply()  # initial state; the card isn't mounted yet, so no update()
        vm.subscribe(self.render)
        self._logger.info("JobCardView initialized successfully for job: %s", vm.title)

    # ── ViewModel -> View ─────────────────────────────────────────────────
    def _apply(self) -> None:
        """Copy the ViewModel's state onto the controls."""
        self._logger.debug("Applying ViewModel state to JobCardView controls.")
        vm = self._vm
        for label, stage in zip(self.stages.controls, vm.stages, strict=True):
            assert isinstance(label, ft.Text)
            label.color = (
                ft.Colors.PRIMARY if stage.reached else ft.Colors.ON_SURFACE_VARIANT
            )
            label.weight = ft.FontWeight.BOLD if stage.emphasized else None
        self.bar.value = vm.progress  # None = indeterminate
        self.sub.value = vm.status_text
        self.counter.value = vm.counter_text
        self.toggle.content = vm.toggle_label
        self.toggle.icon = ft.Icons.PAUSE if vm.is_running else ft.Icons.PLAY_ARROW

    def render(self) -> None:
        """Render the view by updating controls and triggering safe UI updates."""
        self._logger.debug("Rendering JobCardView updates.")
        self._apply()
        safe_update(self.root)

    # ── View -> ViewModel ─────────────────────────────────────────────────
    async def _on_toggle(self, _e: ft.Event[ft.OutlinedButton]) -> None:
        """Handle toggle button click to pause or resume the job."""
        self._logger.info("Toggle button clicked for job: %s", self._vm.title)
        await self._vm.toggle()

    async def _on_cancel(self, _e: ft.Event[ft.IconButton]) -> None:
        """Handle cancel button click to abort the job."""
        self._logger.warning("Cancel button clicked for job: %s", self._vm.title)
        await self._vm.cancel()

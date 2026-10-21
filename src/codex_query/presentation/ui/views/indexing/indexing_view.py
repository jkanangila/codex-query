"""Indexing view module for managing book imports and indexing jobs in Flet.

This module defines the `IndexingView` class, which serves as the user interface
for selecting book files, inputting metadata (name, series, book number), starting
indexing jobs, and tracking active background jobs using dynamic job cards.
"""

from pathlib import Path

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.viewmodels.app_viewmodel import IndexingViewModel
from codex_query.presentation.ui.viewmodels.job_card_viewmodel import (
    JobCardViewModel,
)
from codex_query.presentation.ui.views.indexing.job_card import JobCardView

# TODO: add support for ["pdf", "mobi", "txt"]
BOOK_EXTENSIONS = ["epub"]


class IndexingView:
    """UI component for handling the book indexing workflow.

    Observes an `IndexingViewModel` to sync input forms, handle file picking,
    initiate indexing jobs, and synchronize dynamic job progress cards.
    """

    def __init__(
        self, vm: IndexingViewModel, logger_factory: LoggerFactoryPort
    ) -> None:
        """Initialize the indexing view, build UI controls, and subscribe to view model.

        Args:
            vm: The `IndexingViewModel` tracking form inputs and background jobs.
            logger_factory: Factory to produce a contextual logger for this view.
        """
        self._vm = vm
        self._logger_factory = logger_factory
        self._logger = logger_factory.create(__name__)
        self._logger.debug("Initializing IndexingView components.")

        self._cards: dict[JobCardViewModel, JobCardView] = {}

        self.file_label = ft.Text(vm.file_label, expand=True, max_lines=1)
        self.name = ft.TextField(label="Name in library", on_change=self._on_name)
        self.series = ft.TextField(
            label="Series (optional)",
            expand=True,
            on_change=self._on_series,
        )
        self.number = ft.TextField(
            label="Book #",
            width=90,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_number,
        )
        self.jobs_col = ft.Column(spacing=8)

        form = ft.Container(
            padding=12,
            border_radius=12,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Text("Add a book", weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                content="Choose file...",
                                icon=ft.Icons.FOLDER_OPEN,
                                on_click=self._on_pick,
                            ),
                            self.file_label,
                        ]
                    ),
                    self.name,
                    ft.Row([self.series, self.number]),
                    ft.Button(
                        content="Start indexing",
                        icon=ft.Icons.PLAY_ARROW,
                        on_click=self._on_start,
                    ),
                ],
            ),
        )

        self.root = ft.Container(
            padding=12,
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Text("Indexing", size=20, weight=ft.FontWeight.BOLD),
                    self.jobs_col,
                    form,
                ],
            ),
        )

        vm.subscribe(self.render)
        self.render()
        self._logger.info("IndexingView initialized successfully.")

    # ── View -> ViewModel ─────────────────────────────────────────────────
    def _on_name(self, _e: ft.Event[ft.TextField]) -> None:
        """Handle changes to the book name text field."""
        new_val = self.name.value or ""
        self._logger.debug("Book name changed to: '%s'", new_val)
        self._vm.title = new_val

    def _on_series(self, _e: ft.Event[ft.TextField]) -> None:
        """Handle changes to the series text field."""
        new_val = self.series.value or ""
        self._logger.debug("Series changed to: '%s'", new_val)
        self._vm.series = new_val

    def _on_number(self, _e: ft.Event[ft.TextField]) -> None:
        """Handle changes to the book number text field."""
        new_val = self.number.value or ""
        self._logger.debug("Book number changed to: '%s'", new_val)
        self._vm.number_text = new_val

    async def _on_pick(self, _e: ft.Event[ft.OutlinedButton]) -> None:
        """Open a file picker dialog to choose a book file for indexing."""
        self._logger.info("Opening file picker for book selection.")
        files = await ft.FilePicker().pick_files(
            dialog_title="Choose a book",
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=BOOK_EXTENSIONS,
        )
        if not files or files[0].path:
            self._logger.debug("File selection canceled or invalid.")
            return

        picked = files[0]
        self._logger.info("File selected: %s (Path: %s)", picked.name, picked.path)
        self._vm.choose_file(Path(str(picked.path)), picked.name)

    async def _on_start(self, _e: ft.Event[ft.Button]) -> None:
        """Handle click on start indexing button."""
        self._logger.info("Start indexing button clicked.")
        # async: starting a job creates an asyncio task (needs the running loop).
        self._vm.start()

    # ── ViewModel -> View ─────────────────────────────────────────────────
    def render(self) -> None:
        """Synchronize ViewModel state with UI controls and trigger safe updates."""
        self._logger.debug("Rendering IndexingView state updates.")
        vm = self._vm
        self.file_label.value = vm.file_label
        for field, value in (
            (self.name, vm.title),
            (self.series, vm.series),
            (self.number, vm.number_text),
        ):
            if field.value != value:  # don't fight the user's cursor while typing
                field.value = value
        self._sync_cards()
        safe_update(self.root)

    def _sync_cards(self) -> None:
        """Synchronize active job view model cards with UI job card components."""
        self._logger.debug("Synchronizing job cards collection.")
        jobs = self._vm.jobs
        for card_vm in jobs:
            if card_vm not in self._cards:
                self._logger.debug("Creating new JobCardView for job.")
                self._cards[card_vm] = JobCardView(card_vm, self._logger_factory)
                self.jobs_col.controls.append(self._cards[card_vm].root)

        for card_vm in list(self._cards):
            if card_vm not in jobs:
                self._logger.debug("Removing completed/cancelled JobCardView.")
                self.jobs_col.controls.remove(self._cards.pop(card_vm).root)

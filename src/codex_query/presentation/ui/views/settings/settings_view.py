"""Settings view presentation layer module.

This module provides the `SettingsView` class, responsible for building and managing
the user interface components for application settings, including chat and
embedding service configurations, presets, and tuning parameters using Flet.
"""

from collections.abc import Awaitable, Callable

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.utils.formatting import build_test_result_text
from codex_query.presentation.ui.viewmodels.settings_viewmodel import (
    Endpoint,
    SettingsViewModel,
    TuningSlider,
)
from codex_query.presentation.ui.views.settings.components.choice import Choice
from codex_query.presentation.ui.views.settings.components.connection_test_row import (
    ConnectionTestRow,
)
from codex_query.presentation.ui.views.settings.components.settings_tile import (
    TEXT_MUTED,
    DropdownTile,
    SectionHeader,
    SettingTile,
    SliderTile,
    TextFieldTile,
)
from codex_query.presentation.ui.views.settings.settings_text import TEXT

# Width of the settings column, in 12-column grid units, per window width. On wide
# windows it stays a comfortable reading width instead of stretching edge to edge.
_CONTENT_COLUMNS: dict[str | ft.ResponsiveRowBreakpoint, ft.Number] = {
    "xs": 12,
    "md": 10,
    "lg": 9,
    "xl": 8,
}


class SettingsView:
    """View implementation for configuring application settings.

    Manages UI tiles, layouts, and data binding for chat endpoints, embedding
    endpoints, presets, and model tuning parameters.
    """

    def __init__(
        self, vm: SettingsViewModel, logger_factory: LoggerFactoryPort
    ) -> None:
        """Initializes the SettingsView.

        Args:
            vm: The settings view model containing application state and logic.
            logger_factory: Factory used to create a structured component logger.
        """
        self._vm = vm
        self._logger = logger_factory.create(__name__)
        self._logger.debug("Initializing SettingsView UI layout and controls.")

        # ── Chat Service ──────────────────────────────────────────────────
        self.chat_provider = DropdownTile(
            text=TEXT.chat_provider,
            value=vm.chat_provider,
            options=vm.chat_provider_options,
            on_change=vm.select_chat_provider,
        )
        self.chat_base_url = TextFieldTile(
            text=TEXT.chat_base_url,
            value=vm.chat_base_url,
            on_change=vm.set_chat_base_url,
        )
        self.chat_model = TextFieldTile(
            text=TEXT.chat_model,
            value=vm.chat_model,
            on_change=vm.set_chat_model,
        )
        self.chat_api_key = TextFieldTile(
            text=TEXT.chat_api_key,
            value=vm.chat_api_key,
            on_change=vm.set_chat_api_key,
            password=True,
        )

        # ── Embedding Service ─────────────────────────────────────────────
        self.embedding_provider = DropdownTile(
            text=TEXT.embedding_provider,
            value=vm.embedding_provider,
            options=vm.embedding_provider_options,
            on_change=vm.select_embedding_provider,
        )
        self.embedding_base_url = TextFieldTile(
            text=TEXT.embedding_base_url,
            value=vm.embedding_base_url,
            on_change=vm.set_embedding_base_url,
        )
        # Changing the model may open the re-index dialog, so it is committed only
        # on blur / Enter, never while the user is still typing the name.
        self.embedding_model = TextFieldTile(
            text=TEXT.embedding_model,
            value=vm.embedding_model,
            on_change=vm.set_embedding_model,
            commit_delay=None,
        )
        self.embedding_api_key = TextFieldTile(
            text=TEXT.embedding_api_key,
            value=vm.embedding_api_key,
            on_change=vm.set_embedding_api_key,
            password=True,
        )

        self._text_tiles: dict[Endpoint, list[TextFieldTile]] = {
            "chat": [self.chat_base_url, self.chat_model, self.chat_api_key],
            "embedding": [
                self.embedding_base_url,
                self.embedding_model,
                self.embedding_api_key,
            ],
        }
        self._test_rows: dict[Endpoint, ConnectionTestRow] = {
            "chat": ConnectionTestRow(self._tester("chat")),
            "embedding": ConnectionTestRow(self._tester("embedding")),
        }

        # ── Preset & Tuning ───────────────────────────────────────────────
        self.preset = Choice(
            options=vm.preset_options,
            value=vm.preset_key,
            on_change=vm.select_preset,
        )
        self.preset_tile = SettingTile(TEXT.preset, below=self.preset.root)
        self._slider_tiles: dict[str, SliderTile] = {
            spec.key: self._build_slider(spec) for spec in vm.tuning
        }
        self.estimate = ft.Text(
            vm.estimate_text,
            theme_style=ft.TextThemeStyle.BODY_SMALL,
            color=TEXT_MUTED,
        )

        # Every tile, so the layout can be re-flowed for narrow windows.
        self._tiles: list[SettingTile] = [
            self.chat_provider,
            *self._text_tiles["chat"],
            self.embedding_provider,
            *self._text_tiles["embedding"],
            self.preset_tile,
            *self._slider_tiles.values(),
        ]

        # ── Root Layout ───────────────────────────────────────────────────
        content = ft.Column(
            spacing=0,  # vertical rhythm comes from the tiles' own padding
            controls=[
                ft.Container(
                    content=ft.Text(
                        "Settings",
                        theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM,
                    ),
                    padding=ft.Padding.only(left=16, right=16, bottom=8),
                ),
                SectionHeader(TEXT.sections.chat),
                self.chat_provider,
                self.chat_model,
                self.chat_base_url,
                self.chat_api_key,
                self._inset_row("chat"),
                ft.Divider(),
                SectionHeader(TEXT.sections.embedding),
                self.embedding_provider,
                self.embedding_model,
                self.embedding_base_url,
                self.embedding_api_key,
                self._inset_row("embedding"),
                ft.Divider(),
                SectionHeader(TEXT.sections.tuning),
                self.preset_tile,
                *self._slider_tiles.values(),
                ft.Container(
                    content=self.estimate,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                ),
            ],
        )
        self.root = ft.Container(
            padding=12,
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.ResponsiveRow(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[ft.Container(col=_CONTENT_COLUMNS, content=content)],
                    )
                ],
            ),
        )

        vm.subscribe(self.render)
        self._logger.debug("SettingsView initialized successfully.")

    # ── Builders ──────────────────────────────────────────────────────────
    def _build_slider(self, spec: TuningSlider) -> SliderTile:
        """Builds and returns a slider tile for a given tuning specification.

        Args:
            spec: The tuning slider configuration specification.

        Returns:
            A configured `SliderTile` instance.
        """
        key = spec.key

        async def on_change(value: float) -> None:
            self._logger.debug(
                "Tuning slider '%s' changed to new value: %s", key, value
            )
            await self._vm.set_tuning(key, value)

        return SliderTile(
            text=TEXT.tuning_text(key),
            value=spec.value,
            min_value=spec.minimum,
            max_value=spec.maximum,
            step=spec.step,
            on_change=on_change,
        )

    def _tester(self, endpoint: Endpoint) -> Callable[[], Awaitable[None]]:
        """Builds the handler for an endpoint's 'Test connection' button.

        Args:
            endpoint: The target endpoint identifier (e.g., 'chat' or 'embedding').

        Returns:
            An asynchronous callback function executing the connection test.
        """

        async def run() -> None:
            self._logger.info("Starting connection test for endpoint: %s", endpoint)
            # On mobile a focused field may not have lost focus yet, so save any
            # pending edit first: the test must run against what the user sees.
            for tile in self._text_tiles[endpoint]:
                await tile.commit()
            await self._vm.test_connection(endpoint)
            self._logger.debug("Connection test flow completed for: %s", endpoint)

        return run

    def _inset_row(self, endpoint: Endpoint) -> ft.Control:
        """Builds the endpoint's test row container aligned with text tiles.

        Args:
            endpoint: The target endpoint identifier.

        Returns:
            A configured Flet control containing the connection test row.
        """
        return ft.Container(
            content=self._test_rows[endpoint],
            padding=ft.Padding.only(left=16, right=16, top=4, bottom=8),
        )

    # ── Layout ────────────────────────────────────────────────────────────
    def set_compact(self, compact: bool) -> None:
        """Re-flows every tile for a compact/narrow or wide window.

        Args:
            compact: Boolean indicating if compact mode should be active.
        """
        self._logger.debug("Setting view compact mode to: %s", compact)
        for tile in self._tiles:
            tile.set_compact(compact)

    # ── ViewModel -> View ─────────────────────────────────────────────────
    def render(self) -> None:
        """Synchronizes UI controls with the current ViewModel state.

        Each tile ignores a value it already shows, and keeps the user's
        in-progress edit or drag, so this is cheap and safe to call often.
        """
        self._logger.debug("Rendering SettingsView from ViewModel state.")
        vm = self._vm

        for field, value in (
            (self.chat_provider, vm.chat_provider),
            (self.chat_base_url, vm.chat_base_url),
            (self.chat_model, vm.chat_model),
            (self.chat_api_key, vm.chat_api_key),
            (self.embedding_provider, vm.embedding_provider),
            (self.embedding_base_url, vm.embedding_base_url),
            (self.embedding_model, vm.embedding_model),
            (self.embedding_api_key, vm.embedding_api_key),
        ):
            field.sync(value)

        self.preset.set(vm.preset_key)
        for state in vm.tuning:
            self._slider_tiles[state.key].sync(state.value)

        self.estimate.value = vm.estimate_text
        safe_update(self.estimate)

        for endpoint, row in self._test_rows.items():
            result = vm.test_result(endpoint)
            row.show(
                testing=vm.is_testing(endpoint),
                text=build_test_result_text(result),
                ok=None if result is None else result.ok,
            )

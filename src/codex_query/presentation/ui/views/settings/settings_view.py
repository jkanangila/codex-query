from collections.abc import Awaitable, Callable

import flet as ft

from codex_query.presentation.ui.formatting import build_test_result_text
from codex_query.presentation.ui.utils.flet_helpers import safe_update
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
    def __init__(self, vm: SettingsViewModel) -> None:
        self._vm = vm

        # ── Chat Service ──────────────────────────────────────────────────────
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
            text=TEXT.chat_model, value=vm.chat_model, on_change=vm.set_chat_model
        )
        self.chat_api_key = TextFieldTile(
            text=TEXT.chat_api_key,
            value=vm.chat_api_key,
            on_change=vm.set_chat_api_key,
            password=True,
        )

        # ── Embedding Service ─────────────────────────────────────────────────
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

        # ── Preset & Tuning ───────────────────────────────────────────────────
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

        # ── Root Layout ───────────────────────────────────────────────────────
        content = ft.Column(
            spacing=12,
            controls=[
                ft.Text("Settings", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
                SectionHeader(TEXT.sections.chat),
                self.chat_provider,
                self.chat_model,
                self.chat_base_url,
                self.chat_api_key,
                self._test_rows["chat"],
                ft.Divider(),
                SectionHeader(TEXT.sections.embedding),
                self.embedding_provider,
                self.embedding_model,
                self.embedding_base_url,
                self.embedding_api_key,
                self._test_rows["embedding"],
                ft.Divider(),
                SectionHeader(TEXT.sections.tuning),
                self.preset_tile,
                *self._slider_tiles.values(),
                self.estimate,
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

    # ── Builders ──────────────────────────────────────────────────────────
    def _build_slider(self, spec: TuningSlider) -> SliderTile:
        key = spec.key

        async def on_change(value: float) -> None:
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
        """Build the handler for an endpoint's "Test connection" button."""

        async def run() -> None:
            # On mobile a focused field may not have lost focus yet, so save any
            # pending edit first: the test must run against what the user sees.
            for tile in self._text_tiles[endpoint]:
                await tile.commit()
            await self._vm.test_connection(endpoint)

        return run

    # ── Layout ────────────────────────────────────────────────────────────
    def set_compact(self, compact: bool) -> None:
        """Re-flow every tile for a narrow (``True``) or wide window."""
        for tile in self._tiles:
            tile.set_compact(compact)

    # ── ViewModel -> View ─────────────────────────────────────────────────
    def render(self) -> None:
        """Bring every control in line with the ViewModel.

        Each tile ignores a value it already shows, and keeps the user's
        in-progress edit or drag, so this is cheap and safe to call often.
        """
        vm = self._vm
        self.chat_provider.sync(vm.chat_provider)
        self.chat_base_url.sync(vm.chat_base_url)
        self.chat_model.sync(vm.chat_model)
        self.chat_api_key.sync(vm.chat_api_key)

        self.embedding_provider.sync(vm.embedding_provider)
        self.embedding_base_url.sync(vm.embedding_base_url)
        self.embedding_model.sync(vm.embedding_model)
        self.embedding_api_key.sync(vm.embedding_api_key)

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

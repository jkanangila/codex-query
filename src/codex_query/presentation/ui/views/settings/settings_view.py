from typing import Literal

import flet as ft

from codex_query.domain.models.settings import PresetMode
from codex_query.presentation.ui.formatting import build_test_result_text
from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.viewmodels.settings_viewmodel import (
    CHAT_PROVIDER_OPTIONS,
    EMBEDDING_PROVIDER_OPTIONS,
    SettingsViewModel,
)
from codex_query.presentation.ui.views.settings.components.choice import Choice
from codex_query.presentation.ui.views.settings.components.settings_tile import (
    DropdownTile,
    SectionHeader,
    SliderTile,
    TextFieldTile,
)
from codex_query.presentation.ui.views.settings.settings_text import TEXT

_SLIDER_TOLERANCE = 1e-9  # float noise (0.15000000000000002) must not count as a change


class SettingsView:
    def __init__(self, vm: SettingsViewModel) -> None:
        self._vm = vm

        # ── Chat Service ──────────────────────────────────────────────────────
        self.chat_provider = DropdownTile(
            text=TEXT.chat_provider,
            value=vm.chat_provider,
            options=list(CHAT_PROVIDER_OPTIONS.keys()),
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
            text=TEXT.chat_api_key, value=vm.chat_api_key, on_change=vm.set_chat_api_key
        )

        # ── Embedding Service ─────────────────────────────────────────────────
        self.embedding_provider = DropdownTile(
            text=TEXT.embedding_provider,
            value=vm.embedding_provider,
            options=list(EMBEDDING_PROVIDER_OPTIONS),
            on_change=vm.select_chat_provider,
        )
        self.embedding_base_url = TextFieldTile(
            text=TEXT.embedding_base_url,
            value=vm.embedding_base_url,
            on_change=vm.set_embedding_base_url,
        )
        self.embedding_model = TextFieldTile(
            text=TEXT.embedding_model,
            value=vm.embedding_model,
            on_change=vm.set_embedding_model,
        )
        self.embedding_api_key = TextFieldTile(
            text=TEXT.embedding_api_key,
            value=vm.embedding_api_key,
            on_change=vm.set_embedding_api_key,
        )

        # ── Preset ────────────────────────────────────────────────────────────
        self.preset = Choice(
            options=[(p.name, p.value) for p in PresetMode],
            value=vm.preset,
            on_change=vm.select_preset,
        )

        # ── Tuning ────────────────────────────────────────────────────────────
        self._slider_tiles: dict[str, SliderTile] = {}
        self.tuning = ft.Column(
            spacing=0, controls=[self._build_tuning(s.key) for s in vm.tuning]
        )

        # ── Text ──────────────────────────────────────────────────────────────
        self.estimate = ft.Text(size=12)
        self.test_result_chat = ft.Text(size=12)
        self.test_result_embedding = ft.Text(size=12)

        # ── Root Layout ───────────────────────────────────────────────────────
        self.root = ft.Container(
            padding=12,
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Text("Settings", theme_style=ft.TextThemeStyle.DISPLAY_SMALL),
                    SectionHeader(TEXT.sections.chat),
                    self.chat_provider,
                    self.chat_model,
                    self.chat_base_url,
                    self.chat_api_key,
                    self._build_test_control("chat"),
                    ft.Divider(),
                    SectionHeader(TEXT.sections.embedding),
                    self.embedding_provider,
                    self.embedding_model,
                    self.embedding_base_url,
                    self.embedding_api_key,
                    self._build_test_control("embedding"),
                    ft.Divider(),
                    SectionHeader(TEXT.sections.preset),
                    self.preset.root,
                    self.tuning,
                ],
            ),
        )

    # ── Add tuning tiles ──────────────────────────────────────────────────
    def _build_tuning(self, key: str) -> SliderTile:

        spec = next(s for s in self._vm.tuning if s.key == key)
        slider_tile = SliderTile(
            text=TEXT.tuning_text(spec.key),
            value=spec.value,
            min_value=spec.minimum,
            max_value=spec.maximum,
            on_change=lambda value: self._vm.set_tuning(key, value),
        )

        self._slider_tiles[key] = slider_tile
        return slider_tile

    # ── Test Controls ─────────────────────────────────────────────────────
    def _build_test_control(self, endpoint: Literal["chat", "embedding"]) -> ft.Row:
        testing = (
            self._vm.is_testing_chat
            if endpoint == "chat"
            else self._vm.is_testing_embedding
        )

        button_content = (
            ft.ProgressRing(height=12, width=12)
            if testing
            else ft.Text("Test connection")
        )
        outlined_button = ft.OutlinedButton(
            content=button_content,
            on_click=lambda e: self._vm.test_connection(endpoint),
            disabled=testing,
        )
        test_result = (
            self.test_result_chat if endpoint == "chat" else self.test_result_embedding
        )

        return ft.Row([outlined_button, test_result])

    # ── ViewModel -> View ─────────────────────────────────────────────────
    def render(self) -> None:
        """Bring every control in line with the ViewModel
        (only touching real differences)."""
        vm = self._vm
        # chat
        if self.chat_provider.current_value != vm.chat_provider:
            self.chat_provider.current_value = vm.chat_provider
        if self.chat_base_url.current_value != vm.chat_base_url:
            self.chat_base_url.current_value = vm.chat_base_url
        if self.chat_model.current_value != vm.chat_model:
            self.chat_model.current_value = vm.chat_model
        if self.chat_api_key.current_value != vm.chat_api_key:
            self.chat_api_key.current_value = vm.chat_api_key

        # embedding
        if self.embedding_provider.current_value != vm.embedding_provider:
            self.embedding_provider.current_value = vm.embedding_provider
        if self.embedding_base_url.current_value != vm.embedding_base_url:
            self.embedding_base_url.current_value = vm.embedding_base_url
        if self.embedding_model.current_value != vm.embedding_model:
            self.embedding_model.current_value = vm.embedding_model
        if self.embedding_api_key.current_value != vm.embedding_api_key:
            self.embedding_api_key.current_value = vm.embedding_api_key

        if self.preset.value != vm.preset:
            self.preset.set(vm.preset)

        for state in vm.tuning:
            slider = self._slider_tiles[state.key]
            if abs(slider.current_value - state.value) > _SLIDER_TOLERANCE:
                slider.current_value = state.value

        self.estimate.value = vm.estimate_text

        self.test_result_chat.value = build_test_result_text(vm.test_result_chat)
        self.test_result_embedding.value = build_test_result_text(
            vm.test_result_embedding
        )
        safe_update(self.root)

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import flet as ft

from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.views.settings.settings_text import SettingText

# Semantic color tokens: resolved from the active Material 3 scheme,
# so they follow the seed color and the system light/dark mode.
ACCENT = ft.Colors.PRIMARY
TEXT_MUTED = ft.Colors.ON_SURFACE_VARIANT
DIVIDER = ft.Colors.OUTLINE_VARIANT
CONTROL_BORDER = ft.Colors.OUTLINE


@dataclass(frozen=True)
class TypeScale:
    title_large: int = 22  # app bar title
    title_medium: int = 18  # tile titles
    body_large: int = 17  # tile trailing values, dialog items
    body_medium: int = 14  # tile subtitles
    label_large: int = 15  # section headers
    field: int = 17  # text inside dropdowns / text fields


SCALE = TypeScale()


# ──────────────────────────────────────────────────────────────────────
class SectionHeader(ft.Container):
    """Blue section label (e.g. "Text & layout")."""

    def __init__(self, label: str) -> None:
        super().__init__(
            content=ft.Text(
                label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=ACCENT
            ),
            padding=ft.Padding.only(left=16, right=16, top=28, bottom=8),
        )


# ──────────────────────────────────────────────────────────────────────
class SettingTile(ft.Container):
    """Base row: title + subtitle on the left, optional trailing control."""

    def __init__(
        self,
        text: SettingText,
        trailing: ft.Control | None = None,
        on_click: Callable[[ft.Event[ft.Container]], None] | None = None,
        divider: bool = False,
        below: ft.Control | None = None,
    ) -> None:
        text_col = ft.Column(
            [
                ft.Text(text.title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.Text(
                    text.subtitle,
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM,
                    color=TEXT_MUTED,
                ),
                *([below] if below else []),
            ],
            spacing=4,
            expand=True,
        )
        row = ft.Row(
            [text_col, *([trailing] if trailing else [])],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
        )
        super().__init__(
            content=row,
            padding=ft.Padding.symmetric(horizontal=16, vertical=16),
            border=(
                ft.Border.only(bottom=ft.BorderSide(1, DIVIDER)) if divider else None
            ),
            on_click=on_click,
            ink=on_click is not None,
        )


# ──────────────────────────────────────────────────────────────────────
class DropdownTile(SettingTile):
    """Tile with a compact outlined dropdown on the right."""

    def __init__(
        self,
        text: SettingText,
        value: str,
        options: Sequence[str],
        on_change: Callable[[str], Awaitable[None]],
        width: int = 160,
        divider: bool = False,
    ) -> None:
        self._on_change_cb = on_change
        self._dropdown = ft.Dropdown(
            value=value,
            options=[ft.dropdown.Option(o) for o in options],
            width=width,
            dense=True,
            text_size=SCALE.field,
            border_radius=8,
            border_color=CONTROL_BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_select=self._handle_change,
        )
        super().__init__(text, trailing=self._dropdown, divider=divider)

    async def _handle_change(self, _: ft.Event[ft.Dropdown]) -> None:
        await self._on_change_cb(str(self._dropdown.value).strip())

    #
    @property
    def current_value(self) -> str:
        return self._dropdown.value or ""

    @current_value.setter
    def current_value(self, value: str) -> None:
        self._dropdown.value = value
        safe_update(self)


# ──────────────────────────────────────────────────────────────────────
class TextFieldTile(SettingTile):
    """Tile with a compact outlined text field on the right."""

    def __init__(
        self,
        text: SettingText,
        value: str,
        on_change: Callable[[str], Awaitable[None]],
        hint_text: str | None = None,
        width: int = 160,
        divider: bool = False,
    ) -> None:
        self._on_change_cb = on_change
        self._field = ft.TextField(
            value=value,
            hint_text=hint_text,
            width=width,
            dense=True,
            text_size=SCALE.field,
            border_radius=8,
            border_color=CONTROL_BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_change=self._handle_change,
        )
        super().__init__(text, trailing=self._field, divider=divider)

    async def _handle_change(self, _: ft.Event[ft.TextField]) -> None:
        await self._on_change_cb(self._field.value.strip() or "")

    @property
    def current_value(self) -> str:
        return self._field.value

    @current_value.setter
    def current_value(self, value: str) -> None:
        self._field.value = value
        safe_update(self)


# ──────────────────────────────────────────────────────────────────────
class SliderTile(SettingTile):
    """Tile with a single-value slider under the text and a live value readout.

    The readout updates while dragging; `on_change` fires once on release, so
    expensive handlers (e.g. saving settings) don't run on every tick.
    """

    def __init__(
        self,
        text: SettingText,
        value: float,
        min_value: float,
        max_value: float,
        on_change: Callable[[float], Awaitable[None]],
        step: float = 1,
        format_value: Callable[[float], str] = lambda v: f"{v:g}",
        divider: bool = False,
    ) -> None:
        self._on_change_cb = on_change
        self._format = format_value
        self._readout = ft.Text(
            format_value(value),
            theme_style=ft.TextThemeStyle.BODY_LARGE,
            color=TEXT_MUTED,
        )
        self._slider = ft.Slider(
            value=value,
            min=min_value,
            max=max_value,
            divisions=round((max_value - min_value) / step),
            label="{value}",
            on_change=self._handle_drag,
            on_change_end=self._handle_release,
        )
        super().__init__(
            text,
            trailing=self._readout,
            below=self._slider,
            divider=divider,
        )

    @property
    def current_value(self) -> float:
        return self._slider.value or 0

    @current_value.setter
    def current_value(self, value: float) -> None:
        self._slider.value = value
        safe_update(self)

    def _handle_drag(self, _: ft.Event[ft.Slider]) -> None:
        self._readout.value = self._format(float(self._slider.value or 0))
        self._readout.update()

    async def _handle_release(self, _: ft.Event[ft.Slider]) -> None:
        await self._on_change_cb(float(self._slider.value or 0))

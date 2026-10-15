import asyncio
from collections.abc import Awaitable, Callable, Sequence

import flet as ft

from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.views.settings.settings_text import SettingText

# Semantic color tokens: resolved from the active Material 3 scheme,
# so they follow the seed color and the system light/dark mode.
ACCENT = ft.Colors.PRIMARY
TEXT_MUTED = ft.Colors.ON_SURFACE_VARIANT
DIVIDER = ft.Colors.OUTLINE_VARIANT
CONTROL_BORDER = ft.Colors.OUTLINE

COMMIT_DELAY_S = 0.8
"""Pause in typing after which a text field saves itself."""

_SLIDER_TOLERANCE = 1e-9  # float noise (0.15000000000000002) must not count as a change


# ──────────────────────────────────────────────────────────────────────
class SectionHeader(ft.Container):
    """Accent-colored section label (e.g. "Chat service")."""

    def __init__(self, label: str) -> None:
        super().__init__(
            content=ft.Text(
                label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=ACCENT
            ),
            padding=ft.Padding.only(left=16, right=16, top=28, bottom=8),
        )


# ──────────────────────────────────────────────────────────────────────
class SettingTile(ft.Container):
    """Base row: title + subtitle on the left, optional trailing control.

    With ``stack_when_compact`` the trailing control moves *under* the text on
    narrow windows (see :meth:`set_compact`) instead of squeezing the text into a
    sliver beside it.
    """

    def __init__(
        self,
        text: SettingText,
        trailing: ft.Control | None = None,
        on_click: Callable[[ft.Event[ft.Container]], None] | None = None,
        divider: bool = False,
        below: ft.Control | None = None,
        stack_when_compact: bool = False,
    ) -> None:
        self._trailing = trailing
        self._wide_width = (
            trailing.width if isinstance(trailing, ft.TextField | ft.Dropdown) else None
        )
        self._stack_when_compact = stack_when_compact
        self._compact = False
        self._text_col = ft.Column(
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
        super().__init__(
            content=self._layout(),
            padding=ft.Padding.symmetric(horizontal=16, vertical=16),
            border=(
                ft.Border.only(bottom=ft.BorderSide(1, DIVIDER)) if divider else None
            ),
            on_click=on_click,
            ink=on_click is not None,
        )

    def _layout(self) -> ft.Control:
        trailing = self._trailing
        if trailing is None:
            return ft.Row([self._text_col])

        stacked = self._compact and self._stack_when_compact
        # A stacked field fills the row; a side-by-side one keeps its fixed width.
        if isinstance(trailing, ft.TextField | ft.Dropdown):
            trailing.width = None if stacked else self._wide_width
            trailing.expand = stacked
        # In a Row the text column takes the spare width; in a Column it must not.
        self._text_col.expand = not stacked

        if stacked:
            return ft.Column([self._text_col, ft.Row([trailing])], spacing=12)
        return ft.Row(
            [self._text_col, trailing],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
        )

    def set_compact(self, compact: bool) -> None:
        """Re-flow the tile for a narrow (``True``) or wide (``False``) window."""
        if compact == self._compact:
            return
        self._compact = compact
        if self._stack_when_compact:
            self.content = self._layout()
            safe_update(self)


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
            options=[ft.dropdown.Option(key=o, text=o) for o in options],
            width=width,
            dense=True,
            border_radius=8,
            border_color=CONTROL_BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_select=self._handle_change,
        )
        super().__init__(
            text, trailing=self._dropdown, divider=divider, stack_when_compact=True
        )

    async def _handle_change(self, _: ft.Event[ft.Dropdown]) -> None:
        value = (self._dropdown.value or "").strip()
        if value:
            await self._on_change_cb(value)

    @property
    def current_value(self) -> str:
        return self._dropdown.value or ""

    def sync(self, value: str) -> None:
        """Show ``value`` (the ViewModel's state) unless it is already shown."""
        if self.current_value == value:
            return
        self._dropdown.value = value
        safe_update(self)


# ──────────────────────────────────────────────────────────────────────
class TextFieldTile(SettingTile):
    """Tile with a compact outlined text field on the right.

    Edits are *committed* (``on_change`` is awaited) when the field loses focus,
    on Enter, and, unless ``commit_delay`` is ``None``, after the user pauses
    typing. Nothing is saved per keystroke.
    """

    def __init__(
        self,
        text: SettingText,
        value: str,
        on_change: Callable[[str], Awaitable[None]],
        hint_text: str | None = None,
        width: int = 160,
        divider: bool = False,
        password: bool = False,
        commit_delay: float | None = COMMIT_DELAY_S,
    ) -> None:
        self._on_change_cb = on_change
        self._commit_delay = commit_delay
        self._committed = value.strip()
        self._edit_generation = 0
        self._field = ft.TextField(
            value=value,
            hint_text=hint_text,
            width=width,
            dense=True,
            password=password,
            can_reveal_password=password,
            border_radius=8,
            border_color=CONTROL_BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_change=self._handle_change,
            on_blur=self._handle_blur,
            on_submit=self._handle_blur,
        )
        super().__init__(
            text, trailing=self._field, divider=divider, stack_when_compact=True
        )

    @property
    def current_value(self) -> str:
        return self._field.value or ""

    @property
    def is_dirty(self) -> bool:
        """Whether the field holds an edit that has not been committed yet."""
        return self.current_value.strip() != self._committed

    async def _handle_change(self, _: ft.Event[ft.TextField]) -> None:
        if self._commit_delay is None:
            return
        self._edit_generation += 1
        generation = self._edit_generation
        await asyncio.sleep(self._commit_delay)
        if generation == self._edit_generation:  # no newer keystroke arrived
            await self.commit()

    async def _handle_blur(self, _: ft.Event[ft.TextField]) -> None:
        await self.commit()

    async def commit(self) -> None:
        """Save a pending edit now (no-op if there is none)."""
        self._edit_generation += 1  # cancels any scheduled commit
        value = self.current_value.strip()
        if value == self._committed:
            return
        previous, self._committed = self._committed, value
        try:
            await self._on_change_cb(value)
        except Exception:
            self._committed = previous
            raise

    def sync(self, value: str) -> None:
        """Show ``value`` (the ViewModel's state), unless the user is mid-edit."""
        if self.is_dirty:
            return
        self._committed = value.strip()
        if self.current_value == value:
            return
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
        self._dragging = False
        self._readout = ft.Text(
            format_value(value),
            theme_style=ft.TextThemeStyle.BODY_LARGE,
            color=TEXT_MUTED,
        )
        self._slider = ft.Slider(
            value=value,
            min=min_value,
            max=max_value,
            divisions=max(1, round((max_value - min_value) / step)),
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

    def sync(self, value: float) -> None:
        """Move the slider and its readout to ``value`` (the ViewModel's state).

        Ignored while the user is dragging, so a redraw cannot snap the thumb back.
        """
        if self._dragging or abs(self.current_value - value) <= _SLIDER_TOLERANCE:
            return
        self._slider.value = value
        self._readout.value = self._format(value)
        safe_update(self)

    def _handle_drag(self, _: ft.Event[ft.Slider]) -> None:
        self._dragging = True
        self._readout.value = self._format(float(self._slider.value or 0))
        safe_update(self._readout)

    async def _handle_release(self, _: ft.Event[ft.Slider]) -> None:
        try:
            await self._on_change_cb(float(self._slider.value or 0))
        finally:
            self._dragging = False

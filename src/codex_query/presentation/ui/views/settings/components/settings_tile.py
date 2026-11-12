"""Settings UI components module containing section headers, tiles, dropdowns,
text fields, and sliders.

Provides reusable Flet UI components for building settings screens, including
configurable tiles with flexible layouts, dropdown selectors, text input fields
with auto-commit and API key management, and interactive sliders.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

import flet as ft

from codex_query.presentation.ui.utils.flet_helpers import safe_update
from codex_query.presentation.ui.views.settings.settings_text import SettingText

# Semantic color tokens: resolved from the active Material 3 scheme,
# so they follow the seed color and the system light/dark mode.
ACCENT = ft.Colors.PRIMARY
TEXT_MUTED = ft.Colors.ON_SURFACE_VARIANT
DIVIDER = ft.Colors.OUTLINE_VARIANT
CONTROL_BORDER = ft.Colors.OUTLINE

# One size for every input control, so a dropdown, a text field and a password
# field (whose reveal icon would otherwise force extra height) line up.
CONTROL_HEIGHT = 44
CONTROL_TEXT_SIZE = 14
CONTROL_PADDING = ft.Padding.symmetric(horizontal=12, vertical=8)
DROPDOWN_WIDTH = 200

# Where a tile puts its trailing control: beside the text ("never" stacked), under
# it only on narrow windows ("compact"), or always under it ("always", for values
# such as URLs and keys that need the full width).
type Stacking = Literal["never", "compact", "always"]

COMMIT_DELAY_S = 0.8
"""Pause in typing after which a text field saves itself."""

_SLIDER_TOLERANCE = 1e-9  # float noise must not count as a change


class SectionHeader(ft.Container):
    """Accent-colored section label (e.g. "Chat service")."""

    def __init__(self, label: str) -> None:
        """Initializes the SectionHeader component.

        Args:
            label: The text content for the section header.
        """
        super().__init__(
            content=ft.Text(
                label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=ACCENT
            ),
            padding=ft.Padding.only(left=16, right=16, top=28, bottom=8),
        )


class SettingTile(ft.Container):
    """Base row: title + subtitle on the left, optional trailing control.

    ``stack`` decides whether the trailing control sits beside the text or under it
    (see :data:`Stacking` and :meth:`set_compact`), so long values are not squeezed
    into a sliver next to the label.

    Attributes:
        _trailing: Optional trailing Flet control.
        _wide_width: Fixed width maintained for side-by-side controls.
        _stack: Stacking mode governing responsive layout behavior.
        _compact: Whether compact mode is currently active.
        _text_col: Flet column holding title, subtitle, and optional sub-content.
    """

    def __init__(
        self,
        text: SettingText,
        trailing: ft.Control | None = None,
        on_click: Callable[[ft.Event[ft.Container]], None] | None = None,
        divider: bool = False,
        below: ft.Control | None = None,
        stack: Stacking = "never",
    ) -> None:
        """Initializes the SettingTile component.

        Args:
            text: SettingText instance containing title and subtitle.
            trailing: Optional trailing control positioned beside or below text.
            on_click: Optional click event handler.
            divider: Whether to render a bottom border divider.
            below: Optional control rendered beneath the subtitle.
            stack: Stacking behavior ("never", "compact", or "always").
        """
        self._trailing = trailing
        self._wide_width = self._width_of(trailing)
        self._stack = stack
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

    @staticmethod
    def _width_of(control: ft.Control | None) -> ft.Number | None:
        """Fixed width a side-by-side field keeps (``None`` for other controls)."""
        if isinstance(control, ft.TextField | ft.Dropdown):
            return control.width
        return None

    def _layout(self) -> ft.Control:
        """Constructs and returns the appropriate Row or Column layout."""
        trailing = self._trailing
        if trailing is None:
            return ft.Row([self._text_col])

        stacked = self._stack == "always" or (
            self._stack == "compact" and self._compact
        )
        # A stacked field fills the row; a side-by-side one keeps its fixed width.
        if isinstance(trailing, ft.TextField | ft.Dropdown):
            trailing.width = None if stacked else self._wide_width
            trailing.expand = stacked
        elif stacked:
            trailing.expand = True
        # In a Row the text column takes the spare width; in a Column it must not.
        self._text_col.expand = not stacked

        if stacked:
            return ft.Column([self._text_col, ft.Row([trailing])], spacing=12)
        return ft.Row(
            [self._text_col, trailing],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
        )

    def set_trailing(self, trailing: ft.Control | None, stack: Stacking) -> None:
        """Swap the trailing control (and how it is stacked) and redraw the tile.

        Args:
            trailing: New trailing control to display.
            stack: Updated stacking behavior.
        """
        self._trailing = trailing
        self._stack = stack
        self._wide_width = self._width_of(trailing)
        self.content = self._layout()
        safe_update(self)

    def set_compact(self, compact: bool) -> None:
        """Re-flow the tile for a narrow (``True``) or wide (``False``) window.

        Args:
            compact: Boolean indicating if compact mode should be active.
        """
        if compact == self._compact:
            return
        self._compact = compact
        if self._stack == "compact":
            self.content = self._layout()
            safe_update(self)


class DropdownTile(SettingTile):
    """Tile with a compact outlined dropdown on the right.

    Attributes:
        _on_change_cb: Asynchronous callback invoked when selection changes.
        _dropdown: Flet Dropdown control instance.
    """

    def __init__(
        self,
        text: SettingText,
        value: str,
        options: Sequence[str],
        on_change: Callable[[str], Awaitable[None]],
        width: int = DROPDOWN_WIDTH,
        divider: bool = False,
    ) -> None:
        """Initializes the DropdownTile component.

        Args:
            text: SettingText containing title and subtitle.
            value: Currently selected option value.
            options: Sequence of selectable option strings.
            on_change: Async callback executed upon value selection.
            width: Width of the dropdown control.
            divider: Whether to render a bottom border divider.
        """
        self._on_change_cb = on_change
        self._dropdown = ft.Dropdown(
            value=value,
            options=[ft.dropdown.Option(key=o, text=o) for o in options],
            width=width,
            height=CONTROL_HEIGHT,
            text_size=CONTROL_TEXT_SIZE,
            border_radius=8,
            border_color=CONTROL_BORDER,
            focused_border_color=ACCENT,
            content_padding=CONTROL_PADDING,
            on_select=self._handle_change,
        )
        super().__init__(
            text, trailing=self._dropdown, divider=divider, stack="compact"
        )

    async def _handle_change(self, _: ft.Event[ft.Dropdown]) -> None:
        value = (self._dropdown.value or "").strip()
        if value:
            await self._on_change_cb(value)

    @property
    def current_value(self) -> str:
        """Get the current dropdown selection value.

        Returns:
            The selected option string.
        """
        return self._dropdown.value or ""

    def sync(self, value: str) -> None:
        """Show ``value`` (the ViewModel's state) unless it is already shown.

        Args:
            value: The target option value from the view model.
        """
        if self.current_value == value:
            return
        self._dropdown.value = value
        safe_update(self)


class TextFieldTile(SettingTile):
    """Tile with an outlined text field under the text, at the full tile width.

    Edits are *committed* (``on_change`` is awaited) when the field loses focus,
    on Enter, and, unless ``commit_delay`` is ``None``, after the user pauses
    typing. Nothing is saved per keystroke.

    With ``is_api_key_field`` the tile is a write-only secret input: it never shows
    the stored key. While a key is configured (and the user is not replacing it) it
    shows "● Configured (<hash>)" with an edit button instead of the field; see
    :meth:`set_key_state`.
    """

    def __init__(
        self,
        text: SettingText,
        value: str,
        on_change: Callable[[str], Awaitable[None]],
        hint_text: str | None = None,
        divider: bool = False,
        password: bool = False,
        commit_delay: float | None = COMMIT_DELAY_S,
        is_api_key_field: bool = False,
        field_visible: bool = True,
        has_key: bool = False,
        api_key_hash: str = "",
        on_edit_key: Callable[[], None] | None = None,
        on_cancel_edit: Callable[[], None] | None = None,
    ) -> None:
        """Initializes the TextFieldTile component.

        Args:
            text: SettingText containing title and subtitle.
            value: Initial text value.
            on_change: Async callback executed upon committing edits.
            hint_text: Optional placeholder text for the text field.
            divider: Whether to render a bottom border divider.
            password: Whether input text should be masked.
            commit_delay: Delay in seconds for auto-committing typing pauses.
            is_api_key_field: Whether this tile manages an API key secret.
            field_visible: Whether the input field is currently visible.
            has_key: Whether an API key is currently configured.
            api_key_hash: Fingerprint hash of the configured API key.
            on_edit_key: Callback triggered when requesting key replacement.
            on_cancel_edit: Callback triggered when canceling key replacement.
        """
        self._on_change_cb = on_change
        self._is_api_key_field = is_api_key_field
        self._on_edit_key = on_edit_key
        self._on_cancel_edit = on_cancel_edit
        # (field visible, key configured, key fingerprint) as last rendered.
        self._key_state = (field_visible, has_key, api_key_hash)
        self._commit_delay = commit_delay
        self._committed = value.strip()
        self._edit_generation = 0
        self._field = ft.TextField(
            value=value,
            hint_text=hint_text,
            height=CONTROL_HEIGHT,
            text_size=CONTROL_TEXT_SIZE,
            password=password,
            can_reveal_password=password,
            border_radius=8,
            border_color=CONTROL_BORDER,
            focused_border_color=ACCENT,
            content_padding=CONTROL_PADDING,
            on_change=self._handle_change,
            on_blur=self._handle_blur,
            on_submit=self._handle_blur,
        )
        trailing, stack = self._build_trailing()
        super().__init__(text, trailing=trailing, divider=divider, stack=stack)

    # ── API key display ───────────────────────────────────────────────────
    def _build_trailing(self) -> tuple[ft.Control, Stacking]:
        """Pick the trailing control and stacking for the current key state."""
        if not self._is_api_key_field:
            return self._field, "always"

        field_visible, has_key, key_hash = self._key_state
        if field_visible:
            if not has_key or self._on_cancel_edit is None:
                return self._field, "always"
            # Replacing an existing key: offer a way back to the "Configured" row.
            self._field.expand = True
            return (
                ft.Row(
                    [
                        self._field,
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            tooltip="Cancel",
                            on_click=self._handle_cancel_edit,
                        ),
                    ],
                    spacing=4,
                ),
                "always",
            )

        controls: list[ft.Control] = [
            ft.Text(f"● Configured ({key_hash})", color=TEXT_MUTED)
        ]
        if self._on_edit_key is not None:
            controls.append(
                ft.IconButton(
                    icon=ft.Icons.EDIT,
                    tooltip="Replace key",
                    on_click=self._handle_edit_key,
                )
            )
        return ft.Row(controls, spacing=4), "never"

    def set_key_state(
        self, *, field_visible: bool, has_key: bool, key_hash: str
    ) -> None:
        """Show the key input or the "Configured" row (the ViewModel's state).

        No-op when the state is unchanged, so a redraw never disturbs a key the
        user is typing. Whenever the input is hidden, what was typed is discarded
        so the secret does not linger in the control.

        Args:
            field_visible: Whether the key input should be shown.
            has_key: Whether a key is stored (enables the cancel button).
            key_hash: Fingerprint of the stored key, shown when configured.
        """
        state = (field_visible, has_key, key_hash)
        if state == self._key_state:
            return
        self._key_state = state
        if not field_visible:
            self._edit_generation += 1  # cancels any scheduled commit
            self._field.value = ""
            self._committed = ""
        trailing, stack = self._build_trailing()
        self.set_trailing(trailing, stack)

    def _handle_edit_key(self, _: ft.Event[ft.IconButton]) -> None:
        if self._on_edit_key is not None:
            self._on_edit_key()

    def _handle_cancel_edit(self, _: ft.Event[ft.IconButton]) -> None:
        if self._on_cancel_edit is not None:
            self._on_cancel_edit()

    # ── Editing ───────────────────────────────────────────────────────────
    @property
    def current_value(self) -> str:
        """Get the current text field value.

        Returns:
            The raw text string in the field.
        """
        return self._field.value or ""

    @property
    def is_dirty(self) -> bool:
        """Whether the field holds an edit that has not been committed yet.

        Returns:
            True if uncommitted edits exist, False otherwise.
        """
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
        """Show ``value`` (the ViewModel's state), unless the user is mid-edit.

        Args:
            value: The target text value from the view model.
        """
        if self.is_dirty:
            return
        self._committed = value.strip()
        if self.current_value == value:
            return
        self._field.value = value
        safe_update(self)


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
        """Initializes the SliderTile component.

        Args:
            text: SettingText containing title and subtitle.
            value: Current numerical slider value.
            min_value: Minimum allowable slider value.
            max_value: Maximum allowable slider value.
            on_change: Async callback executed upon releasing the slider thumb.
            step: Incremental step size.
            format_value: Formatting function converting float value to string.
            divider: Whether to render a bottom border divider.
        """
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
        """Get the current slider numerical value.

        Returns:
            The float value of the slider.
        """
        return self._slider.value or 0

    def sync(self, value: float) -> None:
        """Move the slider and its readout to ``value`` (the ViewModel's state).

        Ignored while the user is dragging, so a redraw cannot snap the thumb back.

        Args:
            value: The target float value from the view model.
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

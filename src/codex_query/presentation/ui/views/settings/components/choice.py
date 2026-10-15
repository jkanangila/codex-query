"""Single-choice selector built from buttons."""

from collections.abc import Awaitable, Callable

import flet as ft

from codex_query.presentation.ui.utils.flet_helpers import safe_update


class Choice:
    """Segmented single-choice selector built from buttons (chips in the design).

    The selected option is drawn as a filled ``Button``, the others as
    ``OutlinedButton``. Add :attr:`root` to a layout; read or change the selection
    with :attr:`value` / :meth:`set`.
    """

    def __init__(
        self,
        options: list[tuple[str, str]],
        value: str,
        on_change: Callable[[str], Awaitable[None]],
    ) -> None:
        """
        Args:
            options: ``(key, label)`` pairs in display order.
            value: Key of the initially selected option.
            on_change: Called with the new key when the *user* picks an option
                (not when :meth:`set` is called programmatically).
        """
        self._options = options
        self.value = value
        self._on_change = on_change
        self.root = ft.Row(wrap=True, spacing=6, run_spacing=6)
        self._build()

    def _build(self) -> None:
        self.root.controls = [
            self._make_button(key, label) for key, label in self._options
        ]

    def _make_button(self, key: str, label: str) -> ft.Control:
        # Flet picks "sync or async" by inspecting the handler itself, so the
        # handler must be a real ``async def`` (not a lambda returning a coroutine).
        async def on_click(
            _e: ft.Event[ft.Button] | ft.Event[ft.OutlinedButton],
        ) -> None:
            self.set(key)
            await self._on_change(key)

        button_type = ft.Button if key == self.value else ft.OutlinedButton
        return button_type(content=label, on_click=on_click)

    def set(self, key: str) -> None:
        """Select ``key`` and redraw, without invoking ``on_change``."""
        if key == self.value:
            return
        self.value = key
        self._build()
        safe_update(self.root)

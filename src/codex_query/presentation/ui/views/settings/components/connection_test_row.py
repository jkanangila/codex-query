"""The "Test connection" button with its status text."""

from collections.abc import Awaitable, Callable

import flet as ft

from codex_query.presentation.ui.utils.flet_helpers import safe_update


class ConnectionTestRow(ft.Row):
    """A button that runs a connection test, and the outcome shown beside it."""

    def __init__(self, on_test: Callable[[], Awaitable[None]]) -> None:
        self._on_test = on_test
        self._button = ft.OutlinedButton(
            content=ft.Text("Test connection"), on_click=self._handle_click
        )
        self._status = ft.Text(theme_style=ft.TextThemeStyle.BODY_SMALL)
        super().__init__(
            [self._button, self._status],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            wrap=True,
        )

    async def _handle_click(self, _: ft.Event[ft.OutlinedButton]) -> None:
        await self._on_test()

    def show(self, *, testing: bool, text: str, ok: bool | None) -> None:
        """Draw the state: a spinner while testing, else the result text.

        Args:
            testing: A test is running (button disabled, spinner shown).
            text: Result text; empty when there is no result.
            ok: Whether the last test succeeded; ``None`` when there is no result.
        """
        self._button.disabled = testing
        self._button.content = (
            ft.ProgressRing(width=12, height=12)
            if testing
            else ft.Text("Test connection")
        )
        self._status.value = "" if testing else text
        self._status.color = (
            None if ok is None else (ft.Colors.PRIMARY if ok else ft.Colors.ERROR)
        )
        safe_update(self)

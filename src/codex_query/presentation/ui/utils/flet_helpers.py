"""Small Flet utilities."""

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft


def safe_update(control: ft.Control) -> None:
    """Update a control, ignoring it if its view isn't currently mounted.

    ViewModels notify from background work (streaming answers, indexing progress)
    that can finish after the user has navigated away; updating an unmounted control
    raises ``RuntimeError`` and we don't want that to crash the task.
    """
    with contextlib.suppress(RuntimeError):
        control.update()


def bind(
    command: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> Callable[[ft.Event[Any]], None]:
    """Adapt a ViewModel command to a Flet event handler.

    Flet calls handlers with the event as the only argument; ViewModel commands don't
    take one. ``bind(vm.select_book, "dune1")`` returns a handler that ignores the
    event and calls ``vm.select_book("dune1")``.

    Use it only for commands that don't need the event loop. Commands that start asyncio
    tasks (``IndexViewModel.start``, ``JobCardViewModel.toggle``) must be called from an
    ``async def`` handler, because Flet runs plain functions in a worker thread.
    """

    def handler(e: ft.Event[Any]) -> None:
        command(*args, **kwargs)

    return handler


def bind_async(
    command: Callable[..., Awaitable[object]],
    *args: object,
    **kwargs: object,
) -> Callable[[ft.Event[Any]], Awaitable[None]]:
    """Adapt an async ViewModel command to a Flet event handler.

    Flet calls handlers with the event as the only argument.
    This adapter ignores the event and awaits the ViewModel command.

    Use for commands that interact with asyncio tasks or perform
    asynchronous operations.
    """

    async def handler(e: ft.Event[Any]) -> None:
        await command(*args, **kwargs)

    return handler

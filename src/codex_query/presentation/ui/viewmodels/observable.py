"""Minimal observer primitives: the data-binding mechanism of the presentation layer.

Flet has no built-in binding, so Folio uses two tiny classes:

* :class:`ObservableObject` - "something on this object changed, redraw yourself".
  Used by every ViewModel. Views call ``vm.subscribe(self.render)`` once and
  re-read the ViewModel's properties inside ``render``.
* :class:`Signal` - a one-shot *event* that carries a value ("show this toast").
  Used for things that are not state, so they must not replay when a view redraws.

Both are synchronous: handlers run inside ``notify_changed()`` / ``emit()`` on the
caller's thread. Everything in Folio runs on the asyncio loop or a Flet handler
thread, and Flet's own ``update()`` is thread-safe, so no extra locking is needed.
"""

from collections.abc import Callable

type Unsubscribe = Callable[[], None]


class ObservableObject:
    """Base class for ViewModels (and any object a view binds to)."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[], None]] = []

    def subscribe(self, handler: Callable[[], None]) -> Unsubscribe:
        """Call ``handler()`` after every change. Returns a function that undoes it."""
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    def notify_changed(self) -> None:
        """Tell subscribers to re-read this object's state.

        Iterates over a copy so a handler may unsubscribe (or subscribe) safely.
        """
        for handler in list(self._handlers):
            handler()


class Signal[T]:
    """A typed, fire-and-forget event."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[T], None]] = []

    def subscribe(self, handler: Callable[[T], None]) -> Unsubscribe:
        """Call ``handler(value)`` for every :meth:`emit`.
        Returns an unsubscribe function."""
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    def emit(self, value: T) -> None:
        for handler in list(self._handlers):
            handler(value)

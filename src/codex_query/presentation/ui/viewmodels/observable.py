"""Minimal observer primitives: the data-binding mechanism of the presentation layer.

Flet has no built-in binding, so Folio uses two tiny classes:

* :class:`Signal` - a typed, one-shot *event* that carries a value ("show this
  toast"). Used for things that are not state, so they must not replay when a view
  redraws.
* :class:`ObservableObject` - "something on this object changed, redraw yourself".
  Used by every ViewModel. Views call ``vm.subscribe(self.render)`` once and re-read
  the ViewModel's properties inside ``render``. It is a thin wrapper around a
  ``Signal[None]``.

Both are synchronous: handlers run inside ``notify_changed()`` / ``emit()`` on the
caller's thread. That is either the asyncio loop or a Flet worker thread (Flet runs
plain, non-async handlers in a worker thread), and Flet's own ``update()`` is
thread-safe, so no extra locking is needed for notification itself.
"""

from collections.abc import Callable

type Unsubscribe = Callable[[], None]


class Signal[T]:
    """A typed, fire-and-forget event."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[T], None]] = []

    def subscribe(self, handler: Callable[[T], None]) -> Unsubscribe:
        """Call ``handler(value)`` for every :meth:`emit`.

        Returns a function that undoes the subscription.
        """
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    def emit(self, value: T) -> None:
        """Deliver ``value`` to every subscriber.

        Iterates over a copy so a handler may unsubscribe (or subscribe) safely.
        """
        for handler in list(self._handlers):
            handler(value)


class ObservableObject:
    """Base class for ViewModels (and any object a view binds to)."""

    def __init__(self) -> None:
        self._changed: Signal[None] = Signal()

    def subscribe(self, handler: Callable[[], None]) -> Unsubscribe:
        """Call ``handler()`` after every change. Returns a function that undoes it."""
        return self._changed.subscribe(lambda _: handler())

    def notify_changed(self) -> None:
        """Tell subscribers to re-read this object's state."""
        self._changed.emit(None)

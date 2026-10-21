"""Minimal observer primitives: the data-binding mechanism of the presentation layer.

Flet has no built-in binding, so Folio uses two tiny classes:

    - :class:`ObservableObject` - "something on this object changed, redraw
      yourself". Used by every ViewModel. Views call ``vm.subscribe(self.render)``
      once and re-read the ViewModel's properties inside ``render``. It is a
      thin wrapper around a ``Signal[None]``.

Both are synchronous: handlers run inside ``notify_changed()`` / ``emit()`` on
the caller's thread. That is either the asyncio loop or a Flet worker thread
(Flet runs plain, non-async handlers in a worker thread), and Flet's own
``update()`` is thread-safe, so no extra locking is needed for notification
itself.
"""

from collections.abc import Callable

from codex_query.application.observable.signal import Signal, Unsubscribe


class ObservableObject:
    """Base class for ViewModels (and any object a view binds to).

    Attributes:
        _changed (Signal[None]): The internal signal used to track and emit
            change events to all subscribers.
    """

    def __init__(self) -> None:
        """Initialize the ObservableObject with a fresh change signal."""
        self._changed: Signal[None] = Signal()

    def subscribe(self, handler: Callable[[], None]) -> Unsubscribe:
        """Subscribe a handler function to changes on this object.

        Args:
            handler (Callable[[], None]): The callback function to execute
                when the object changes.

        Returns:
            Unsubscribe: A callable that removes the subscription when invoked.
        """
        return self._changed.subscribe(lambda _: handler())

    def notify_changed(self) -> None:
        """Notify all subscribers that the object's state has changed.

        This triggers all registered handlers to re-read state and redraw.
        """
        self._changed.emit(None)

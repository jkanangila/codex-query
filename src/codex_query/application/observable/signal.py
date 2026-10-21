"""A typed, fire-and-forget event signal implementation.

Provides a generic :class:`Signal` class for publish-subscribe event handling
within the application layer, allowing safe subscription and emission of
typed values.
"""

from collections.abc import Callable

type Unsubscribe = Callable[[], None]


class Signal[T]:
    """A typed, fire-and-forget event.

    Attributes:
        _handlers (list[Callable[[T], None]]): Internal list of registered
            event handlers/callbacks.
    """

    def __init__(self) -> None:
        """Initialize a new empty Signal instance."""
        self._handlers: list[Callable[[T], None]] = []

    def subscribe(self, handler: Callable[[T], None]) -> Unsubscribe:
        """Register a handler to be called on every :meth:`emit`.

        Args:
            handler (Callable[[T], None]): The callback function to invoke
                when the signal is emitted, receiving the emitted value.

        Returns:
            Unsubscribe: A callable that removes the subscription when invoked.
        """
        self._handlers.append(handler)

        def unsubscribe() -> None:
            """Remove the handler from the signal's subscriber list."""
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    def emit(self, value: T) -> None:
        """Deliver a value to every registered subscriber.

        Iterates over a copy of the handler list so handlers can safely
        unsubscribe or subscribe during emission.

        Args:
            value (T): The value to pass to each subscriber handler.
        """
        for handler in list(self._handlers):
            handler(value)

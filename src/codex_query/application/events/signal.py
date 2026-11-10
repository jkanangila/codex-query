"""A typed, fire-and-forget event signal implementation.

Provides a generic :class:`Signal` class for publish-subscribe event handling
within the application layer, allowing safe subscription and emission of
typed values.
"""

from collections.abc import Callable

type Unsubscribe = Callable[[], None]


class Signal[T]:
    """A synchronous, typed event dispatcher.

    Subscribers are invoked in registration order. Each emission uses
    a snapshot of the current subscribers.

    Exceptions raised by subscribers propagate to the caller.
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[int, Callable[[T], None]]] = []
        self._next_id = 0

    def subscribe(self, handler: Callable[[T], None]) -> Unsubscribe:
        """Register a handler and return its unsubscribe function."""
        subscription_id = self._next_id
        self._next_id += 1

        self._handlers.append((subscription_id, handler))

        def unsubscribe() -> None:
            self._handlers[:] = [
                (sid, callback)
                for sid, callback in self._handlers
                if sid != subscription_id
            ]

        return unsubscribe

    def emit(self, value: T) -> None:
        """Synchronously notify all subscribers."""
        for _, handler in self._handlers.copy():
            handler(value)

    def clear(self) -> None:
        """Remove all registered subscribers."""
        self._handlers.clear()

    def __len__(self) -> int:
        """Return the number of registered subscribers."""
        return len(self._handlers)

    def __bool__(self) -> bool:
        """Return whether the signal has subscribers."""
        return bool(self._handlers)

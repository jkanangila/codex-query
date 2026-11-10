"""Asynchronous and synchronous signal event dispatcher."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
type Handler[T] = Callable[[T], Awaitable[None] | None]
type Unsubscribe = Callable[[], None]


class AsyncSignal[T]:
    """An event dispatcher supporting synchronous and asynchronous handlers.

    Synchronous handlers execute directly on the event-loop thread.
    Asynchronous handlers execute concurrently, subject to a semaphore.

    Each emission uses a snapshot of registered subscribers. Exceptions
    propagate to the caller.

    Attributes:
        max_concurrency (int): The maximum number of concurrent asynchronous
            handlers allowed during an emission.
    """

    def __init__(self, max_concurrency: int = 5) -> None:
        """Initialize the AsyncSignal instance.

        Args:
            max_concurrency: The maximum number of asynchronous handlers
                that can execute concurrently. Must be at least 1.

        Raises:
            ValueError: If `max_concurrency` is less than 1.
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

        self._handlers: list[tuple[int, Handler[T]]] = []
        self._next_id = 0
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def subscribe(self, handler: Handler[T]) -> Unsubscribe:
        """Register a synchronous or asynchronous handler.

        Args:
            handler: A callable that accepts a value of type T and returns
                either None or an Awaitable[None].

        Returns:
            An Unsubscribe callable that, when invoked, removes the handler
            from the subscriber list.
        """
        subscription_id = self._next_id
        self._next_id += 1

        self._handlers.append((subscription_id, handler))

        def unsubscribe() -> None:
            """Unsubscribe the handler from the signal."""
            self._handlers[:] = [
                (sid, callback)
                for sid, callback in self._handlers
                if sid != subscription_id
            ]

        return unsubscribe

    async def emit(self, value: T) -> None:
        """Notify all subscribers with the given value.

        Synchronous handlers run immediately on the event loop, while
        asynchronous handlers run concurrently under the configured semaphore.
        A snapshot of current handlers is taken before execution.

        Args:
            value: The payload to emit to all registered handlers.

        Raises:
            Exception: Any exception raised by a handler propagates upward.
        """
        handlers_snapshot = self._handlers.copy()

        async def invoke(handler: Handler[T]) -> None:
            try:
                result = handler(value)
                if inspect.isawaitable(result):
                    async with self._semaphore:
                        await result
            except Exception:
                raise

        await asyncio.gather(*(invoke(handler) for _, handler in handlers_snapshot))

    def clear(self) -> None:
        """Remove all registered subscribers."""
        self._handlers.clear()

    def __len__(self) -> int:
        """Return the number of currently registered subscribers."""
        return len(self._handlers)

    def __bool__(self) -> bool:
        """Return True if there are any registered subscribers, False otherwise."""
        return bool(self._handlers)

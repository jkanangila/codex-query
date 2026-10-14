"""Asynchronous cached property descriptor for concurrent environments.

This module provides an :class:`async_cached_property` descriptor that lazily
evaluates and caches asynchronous properties. It is designed to be safe across
concurrent awaiters within the same event loop, across multiple threads running
independent loops, and works seamlessly with classes utilizing ``__slots__``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import weakref
from collections.abc import Awaitable, Callable, Coroutine, Generator
from typing import Any, Final, cast, overload

# Sentinel: the computing task was cancelled, so waiters should retry.
_RETRY: Final = object()


class _LazyAwaitable[T]:
    """Awaitable that creates its coroutine only when awaited.

    Because no coroutine object exists until ``await``, discarding it
    unawaited cannot trigger "coroutine ... was never awaited".
    """

    __slots__ = ("_factory",)

    def __init__(self, factory: Callable[[], Coroutine[Any, Any, T]]) -> None:
        """Initialize the lazy awaitable with a coroutine factory."""
        self._factory = factory

    def __await__(self) -> Generator[Any, Any, T]:
        """Return the generator for the underlying coroutine."""
        return self._factory().__await__()


class async_cached_property[T]:
    """Descriptor that lazily evaluates and caches an async property.

    - Computed at most once per instance, even with concurrent awaiters in
      one event loop *or* several threads each running their own loop.
    - If the computation raises, nothing is cached. Awaiters that were
      waiting on that attempt see the same exception; the next access retries.
    - If the computing task is cancelled, a waiting task takes over.
    - Works with ``__slots__`` classes that include ``__weakref__``.
    - ``del obj.name`` invalidates the cache.
    - Accessing the property without awaiting it is harmless.

    Note: the access returns an awaitable, not a coroutine, so use
    ``asyncio.ensure_future(obj.name)`` rather than ``asyncio.create_task``.
    """

    def __init__(self, func: Callable[[Any], Awaitable[T]]) -> None:
        """Initialize the async cached property descriptor."""
        self.func = func
        self.attrname: str | None = None
        self.pendingname: str | None = None
        self.__doc__ = func.__doc__
        # Guards only short, non-awaiting state transitions (never held
        # across an ``await``), so it is safe to share across threads.
        self._guard = threading.Lock()
        # Fallback storage for instances without ``__dict__``.
        self._side: dict[int, tuple[weakref.ref[Any], dict[str, Any]]] = {}

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Bind the descriptor name to the class attribute."""
        if self.attrname is None:
            self.attrname = name
            self.pendingname = f"_async_cached_property_pending_{name}"
            return

        if name != self.attrname:
            raise RuntimeError(
                f"Cannot assign {self!r} to {name!r}; "
                f"already assigned to {self.attrname!r}"
            )

    # Defining __set__ makes this a data descriptor, so __get__ always runs
    # and always returns an awaitable (instead of the raw cached value).
    def __set__(self, instance: Any, value: Any) -> None:
        """Prevent direct assignment to the cached property."""
        raise AttributeError(f"Can't set attribute {self.attrname!r}")

    def __delete__(self, instance: Any) -> None:
        """Invalidate the cache by deleting the cached attribute."""
        if self.attrname is not None:
            ns = self._namespace(instance)
            with self._guard:
                ns.pop(self.attrname, None)

    def _namespace(self, instance: Any) -> dict[str, Any]:
        """Return the dictionary used to store state for ``instance``."""
        ns = getattr(instance, "__dict__", None)
        if ns is not None:
            return cast(dict[str, Any], ns)

        # No __dict__ (e.g. __slots__): use a weakly-keyed side table.
        # Keyed by id() so unhashable instances work; the callback drops
        # the entry when the instance dies, so ids are never reused while
        # an entry exists.
        key = id(instance)
        entry = self._side.get(key)
        if entry is None:

            def _forget(_ref: weakref.ref[Any]) -> None:
                self._side.pop(key, None)

            try:
                ref = weakref.ref(instance, _forget)
            except TypeError:
                raise TypeError(
                    f"{type(instance).__name__} has no __dict__ and does not "
                    f"support weak references; add '__weakref__' to __slots__ "
                    f"to use {type(self).__name__}"
                ) from None
            entry = self._side.setdefault(key, (ref, {}))
        return entry[1]

    @overload
    def __get__(
        self,
        instance: None,
        owner: type[Any] | None = None,
    ) -> async_cached_property[T]: ...

    @overload
    def __get__(
        self,
        instance: Any,
        owner: type[Any] | None = None,
    ) -> Awaitable[T]: ...

    def __get__(
        self,
        instance: Any,
        owner: type[Any] | None = None,
    ) -> async_cached_property[T] | Awaitable[T]:
        """Return the descriptor itself or a lazy awaitable for the value."""
        if instance is None:
            return self

        attrname = self.attrname
        pendingname = self.pendingname
        if attrname is None or pendingname is None:
            raise RuntimeError(
                "async_cached_property must be assigned to a class attribute"
            )

        ns = self._namespace(instance)  # fail early on unsupported instances
        return _LazyAwaitable(lambda: self._load(instance, ns, attrname, pendingname))

    async def _load(
        self,
        instance: Any,
        ns: dict[str, Any],
        attrname: str,
        pendingname: str,
    ) -> T:
        """Evaluate the property or wait for an in-flight computation."""
        while True:
            mine: concurrent.futures.Future[Any] | None = None

            with self._guard:
                if attrname in ns:
                    return cast(T, ns[attrname])

                pending = cast(
                    "concurrent.futures.Future[Any] | None",
                    ns.get(pendingname),
                )
                if pending is None:
                    # We are the computing task; others will wait on `mine`.
                    pending = mine = concurrent.futures.Future()
                    ns[pendingname] = pending

            if mine is not None:
                try:
                    value = await self.func(instance)
                except Exception as exc:
                    with self._guard:
                        ns.pop(pendingname, None)
                    mine.set_exception(exc)
                    raise
                except BaseException:
                    # Cancellation etc.: let a waiter take over.
                    with self._guard:
                        ns.pop(pendingname, None)
                    mine.set_result(_RETRY)
                    raise

                with self._guard:
                    ns[attrname] = value
                    ns.pop(pendingname, None)
                mine.set_result(value)
                return value

            # Wait on the in-flight computation, bridged into *our* loop.
            # shield() so cancelling this waiter never cancels the shared future.
            result = await asyncio.shield(asyncio.wrap_future(pending))
            if result is not _RETRY:
                return cast(T, result)
            # Computing task was cancelled: loop and try to take over.

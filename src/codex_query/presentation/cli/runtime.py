"""Composition root and async plumbing for the terminal front end.

The UI builds its object graph inside a Flet page. The terminal needs the same
graph minus two Flet-only pieces:

* API keys: ``flet_secure_storage`` needs a running Flet page, so the CLI uses
  environment variables first and a ``0600`` JSON file second.
* Logging: the shared setup prints JSON records to stdout, which would tear
  through Rich output, so the CLI logs to the rotating file only (stderr with
  ``--verbose``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Coroutine,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Literal, override

import click
from rich.console import Console

from codex_query.application.facade import UseCases
from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.di.bootstrap import CompositionRoot
from codex_query.domain.models.api_key import ApiKey
from codex_query.domain.models.document import Book
from codex_query.domain.models.provider import LLMProvider
from codex_query.infrastructure.database.sqlmodel.config import db_config
from codex_query.infrastructure.logging.factory import PythonLoggerFactory
from codex_query.infrastructure.paths import AppPaths
from codex_query.presentation.cli.prompts import Cancelled

console = Console()

_ENV_VARS: dict[LLMProvider, tuple[str, ...]] = {
    LLMProvider.OPENAI: ("OPENAI_API_KEY",),
    LLMProvider.ANTHROPIC: ("ANTHROPIC_API_KEY",),
    LLMProvider.GOOGLE_GEMINI: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    LLMProvider.MISTRAL: ("MISTRAL_API_KEY",),
    LLMProvider.COHERE: ("COHERE_API_KEY", "CO_API_KEY"),
}

type KeySource = Literal["env", "file"]


class CliApiKeyRepository(ApiKeyRepositoryPort):
    """API keys from the environment (read-only) or a private JSON file."""

    def __init__(self, path: Path) -> None:
        """Store keys at ``path``; the file is created with mode 0600."""
        self._path = path

    # -- file helpers ------------------------------------------------------
    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        tmp.replace(self._path)

    @staticmethod
    def _from_env(provider: LLMProvider) -> str:
        for name in _ENV_VARS.get(provider, ()):
            value = os.getenv(name, "").strip()
            if value:
                return value
        return ""

    # -- public ------------------------------------------------------------
    def source(self, provider: LLMProvider) -> KeySource | None:
        """Where the effective key for ``provider`` comes from, if anywhere."""
        if self._from_env(provider):
            return "env"
        if self._read().get(provider.value, "").strip():
            return "file"
        return None

    @override
    async def get(self, provider: LLMProvider) -> ApiKey | None:
        value = self._from_env(provider) or self._read().get(provider.value, "")
        return ApiKey(provider, value) if value.strip() else None

    @override
    async def save(self, key: ApiKey) -> None:
        data = self._read()
        data[key.provider.value] = key.value
        self._write(data)

    @override
    async def delete(self, provider: LLMProvider) -> None:
        data = self._read()
        if data.pop(provider.value, None) is not None:
            self._write(data)

    @override
    async def list_providers(self) -> list[LLMProvider]:
        return [p for p in LLMProvider if self.source(p) is not None]


def log_path() -> Path:
    """Path of the JSON log file shared with the UI."""
    from codex_query.infrastructure.logging.config import file_handler

    return Path(file_handler.baseFilename)


def _configure_cli_logging(*, verbose: bool) -> None:
    from codex_query.infrastructure.logging.config import LOG_FORMAT, file_handler

    handlers: list[logging.Handler] = [file_handler]
    if verbose:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        handlers.append(stream)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=handlers,
        force=True,
    )
    for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "aiosqlite", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class CliComposition(CompositionRoot):
    """The UI's composition root with terminal-friendly keys and logging."""

    def __init__(self, *, verbose: bool = False) -> None:
        """Build the graph; no I/O happens until ``start()``."""
        super().__init__("desktop", db_config)
        _configure_cli_logging(verbose=verbose)
        # Pre-seed the cached property so the base class never calls
        # ``configure_logging()`` (which logs JSON to stdout).
        self.__dict__["logger_factory"] = PythonLoggerFactory()

    @cached_property
    @override
    def api_keys_repository(self) -> CliApiKeyRepository:  # type: ignore[override]
        """Keys from env vars or ``<data>/.settings/api_keys.json``."""
        return CliApiKeyRepository(
            AppPaths.app_storage_data_dir() / ".settings" / "api_keys.json"
        )


@dataclass(frozen=True, slots=True)
class Ctx:
    """What every screen needs: the object graph and the console."""

    comp: CliComposition
    console: Console

    @property
    def uc(self) -> UseCases:
        """Application use cases, as the UI sees them."""
        return self.comp.use_cases

    async def books(self) -> list[Book]:
        """All books in the library."""
        return list(await self.uc.library.list_books())


@asynccontextmanager
async def open_session(*, verbose: bool = False) -> AsyncGenerator[CliComposition]:
    """Start the composition root and make sure it is closed again."""
    comp = CliComposition(verbose=verbose)
    try:
        comp.vector_store_factory  # noqa: B018 - fail fast if chromadb is missing
    except ModuleNotFoundError as exc:
        msg = (
            f"Missing dependency: {exc.name}. The terminal app needs the vector "
            "store extra: `uv sync --extra desktop`."
        )
        raise click.ClickException(msg) from exc
    await comp.start()
    try:
        # A fresh process has no running jobs: anything still marked running or
        # queued was interrupted, so park it as paused (resumable).
        await comp.use_cases.indexing.recover_interrupted_jobs()
        yield comp
    finally:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(comp.job_runner.cancel_all(), timeout=5)
        await comp.aclose()


def run_session(fn: Callable[[Ctx], Awaitable[None]], *, verbose: bool = False) -> None:
    """Run ``fn`` inside one event loop with a started composition root."""

    async def main() -> None:
        async with open_session(verbose=verbose) as comp:
            await fn(Ctx(comp, console))

    try:
        asyncio.run(main())
    except (Cancelled, KeyboardInterrupt):
        console.print("[dim]Cancelled.[/]")
        raise click.exceptions.Exit(130) from None


async def interruptible[T](work: Coroutine[Any, Any, T]) -> T | None:
    """Await ``work``; Ctrl-C cancels just this work and returns ``None``."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(work)
    installed = False
    with contextlib.suppress(NotImplementedError, RuntimeError):
        loop.add_signal_handler(signal.SIGINT, task.cancel)
        installed = True
    try:
        return await task
    except asyncio.CancelledError:
        if task.cancelled():
            return None
        raise
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGINT)

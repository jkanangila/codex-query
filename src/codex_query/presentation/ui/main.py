"""Flet application entry point and page lifecycle wiring.

Initializes environment configuration, logging, dependency injection, and the
Flet page lifecycle so startup and shutdown events coordinate cleanly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import flet as ft
from dotenv import load_dotenv

from codex_query.di.bootstrap import CompositionRoot
from codex_query.infrastructure.database.sqlmodel.config import db_config
from codex_query.infrastructure.logging.config import (
    asyncio_handler,
    configure_logging,
)
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.paths import AppPaths
from codex_query.presentation.ui.app import CodexApp
from codex_query.presentation.ui.lifecycle.manager import ApplicationLifecycle
from codex_query.presentation.ui.lifecycle.state import ApplicationState
from codex_query.presentation.ui.theme import configure_page
from codex_query.presentation.ui.utils.set_page_alignment import (
    set_page_alignment,
)
from codex_query.presentation.ui.views.splash_screen import SplashScreen

logger = create_logger(__name__)


async def _main(page: ft.Page) -> None:
    """Configure the Flet page, initialize resources, and run the UI shell.

    Mounts a splash screen while starting the application lifecycle, transitions
    to `CodexApp` once running, and coordinates idempotent shutdown across page
    close, window close, and startup failure paths.

    Args:
        page: Active Flet page instance managed by the Flet runtime.

    Raises:
        BaseException: Re-raises any exception raised during startup or UI
            initialization after attempting graceful shutdown.
    """
    configure_page(page)
    page.window.prevent_close = True

    platform = page.platform.value if page.platform else ""
    lifecycle = ApplicationLifecycle(CompositionRoot(platform, db_config))

    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()
    loop.set_exception_handler(asyncio_handler)

    shell: CodexApp | None = None
    shutdown_task: asyncio.Task[None] | None = None

    async def perform_shutdown() -> None:
        """
        Dispose the UI shell, shut down lifecycle resources, and restore loophooks.
        """
        logger.info("Flet page shutdown requested.")

        if shell is not None:
            try:
                shell.dispose()
            except Exception:
                logger.exception("Failed to detach CodexApp page subscriptions.")

        try:
            await lifecycle.shutdown()
        finally:
            # Do not overwrite a handler installed by another component after us.
            if loop.get_exception_handler() is asyncio_handler:
                loop.set_exception_handler(previous_exception_handler)

    async def shutdown() -> None:
        """Execute and await a shared shutdown task across close callbacks."""
        nonlocal shutdown_task
        if shutdown_task is None:
            shutdown_task = asyncio.create_task(perform_shutdown())
        await asyncio.shield(shutdown_task)

    async def on_page_close() -> None:
        """Run shared application shutdown when Flet closes the page."""
        await shutdown()

    window_destroy_requested = False

    async def on_window_event(
        e: ft.WindowEvent[Any],
    ) -> None:
        """Intercept native close events to run shutdown before destroying the window.

        Args:
            e: Window lifecycle event emitted by Flet.
        """
        nonlocal window_destroy_requested
        if e.type is not ft.WindowEventType.CLOSE or window_destroy_requested:
            return

        window_destroy_requested = True
        logger.info("Native window close event received.")
        await shutdown()
        try:
            await page.window.destroy()
        except Exception:
            logger.exception("Failed to destroy the native application window.")

    page.on_close = on_page_close
    page.window.on_event = on_window_event

    try:
        SplashScreen(page)
        logger.info("Starting Codex Query application.")
        vm = await lifecycle.start()

        # A close event may have been waiting for startup to finish. In that case
        # the lifecycle has already transitioned away from RUNNING; do not mount
        # a new shell on a page that is being destroyed.
        if lifecycle.state is not ApplicationState.RUNNING:
            return

        # No awaits occur between this check and mounting the shell.
        page.clean()
        set_page_alignment(page, "start")
        shell = CodexApp(page, vm)
        logger.info("Codex Query UI launched successfully.")
    except BaseException:
        logger.exception("Application startup or UI initialization failed.")
        await shutdown()
        raise


def main() -> None:
    """Load environment configuration, set up logging, and start Flet.

    Reads `.env` from the application storage directory if present without
    overriding pre-existing environment variables, configures logging, and
    starts the Flet runtime with `_main`.
    """
    env_file = AppPaths.app_storage_data_dir() / ".env"
    if env_file.is_file():
        # Existing process environment variables intentionally take precedence.
        load_dotenv(env_file, override=False)

    configure_logging()
    logger.info("Launching Flet application.")
    ft.run(_main)


if __name__ == "__main__":
    main()

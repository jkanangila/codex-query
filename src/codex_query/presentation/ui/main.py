"""Application launcher and lifecycle manager for the Codex Query Flet UI.

This module initializes the application environment, sets up dependency injection
via CompositionRoot, configures window event handlers, manages the Flet page
lifecycle, and boots the main application interface.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import flet as ft
from dotenv import find_dotenv, load_dotenv

from codex_query.di.bootstrap import CompositionRoot
from codex_query.infrastructure.database.sqlmodel.config import db_config
from codex_query.infrastructure.logging.config import asyncio_handler
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.presentation.ui.app import CodexApp
from codex_query.presentation.ui.theme import configure_page
from codex_query.presentation.ui.utils.set_page_alignment import (
    set_page_alignment,
)
from codex_query.presentation.ui.viewmodels.app_viewmodel import AppViewModel
from codex_query.presentation.ui.views.splash_screen import SplashScreen

logger = create_logger(__name__)


async def _main(page: ft.Page) -> None:
    """Build and manage the Flet GUI lifecycle.

    Initializes the page configuration, sets up window close interception,
    starts the composition root and view model, and renders either the
    splash screen or the main application view.

    Args:
        page (ft.Page): The root Flet page instance.

    Raises:
        BaseException: Re-raises any unhandled exception after cleaning up
            resources.
    """
    configure_page(page)
    page.window.prevent_close = True

    composition: CompositionRoot | None = None
    closing = False

    async def on_window_event(e: ft.WindowEvent[Any]) -> None:
        """Handle window events, specifically intercepting close actions."""
        nonlocal closing
        if e.type != ft.WindowEventType.CLOSE or closing:
            return
        closing = True
        logger.info("Window close event received. Initiating graceful shutdown.")
        try:
            if composition is not None:
                with contextlib.suppress(TimeoutError):
                    composition.job_events.on_job_done.clear()
                    composition.job_events.on_job_update.clear()

                    await asyncio.wait_for(
                        composition.job_runner.cancel_all(), timeout=5
                    )
                await composition.aclose()
        except Exception:
            logger.exception("Error occurred during graceful window shutdown.")
        finally:
            await page.window.destroy()

    page.window.on_event = on_window_event

    platform = page.platform.value if page.platform else ""
    SplashScreen(page)

    logger.info("Starting CompositionRoot...")
    composition = CompositionRoot(platform, db_config)
    await composition.start()

    try:
        asyncio.get_running_loop().set_exception_handler(asyncio_handler)

        async def on_close() -> None:
            """Clean up application events and close composition root."""
            logger.info("Application closing. Cleaning up resources...")
            events = [
                vm.events.embedding_reindex_requested,
                vm.events.source_requested,
                vm.events.toast,
                vm.indexing.job_completed,
            ]
            for event in events:
                event.clear()

            await composition.aclose()

        page.on_close = on_close

        # Create app viewmodel and initialize resources
        logger.info("Initializing AppViewModel...")
        vm = await AppViewModel.create(composition)

        page.clean()
        set_page_alignment(page, "start")
        CodexApp(page, vm)
        logger.info("CodexApp successfully launched.")
    except BaseException:
        logger.exception("Unhandled exception in application main loop.")
        await composition.aclose()
        raise


def main() -> None:
    """Application entry point to launch the Flet UI.

    Loads environment variables from `.dotenv` and starts the Flet event loop.
    """
    load_dotenv(find_dotenv())
    logger.info("Launching Flet application...")
    ft.run(_main)


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio

import flet as ft
from dotenv import find_dotenv, load_dotenv

from codex_query.di.bootstrap import CompositionRoot
from codex_query.infrastructure.logging.config import asyncio_handler
from codex_query.infrastructure.persistence.sqlmodel.config import db_config
from codex_query.presentation.ui.app import CodexApp
from codex_query.presentation.ui.theme import configure_page
from codex_query.presentation.ui.viewmodels.app_viewmodel import AppViewModel
from codex_query.presentation.ui.views.splash_screen import SplashScreen


async def _main(page: ft.Page) -> None:
    """Build and manage the Flet GUI lifecycle."""
    configure_page(page)
    platform = page.platform.value if page.platform else ""

    page.add(SplashScreen())

    composition = CompositionRoot(platform, db_config)
    await composition.start()
    try:
        asyncio.get_running_loop().set_exception_handler(asyncio_handler)

        async def on_close() -> None:
            await composition.aclose()

        page.on_close = on_close

        vm = AppViewModel(composition)
        # Restore and display interrupted indexing jobs from persistence.
        await vm.indexing.restore()

        page.clean()
        CodexApp(page, vm)
    except BaseException:
        await composition.aclose()
        raise


def main() -> None:
    """Application entry point to launch the Flet UI."""
    load_dotenv(find_dotenv())
    ft.run(_main)


if __name__ == "__main__":
    main()

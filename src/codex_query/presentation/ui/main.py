from __future__ import annotations

import asyncio

import flet as ft
from dotenv import find_dotenv, load_dotenv

from codex_query.di.bootstrap import build_composition_root
from codex_query.infrastructure.logging.config import asyncio_handler

load_dotenv(find_dotenv())


async def _main(page: ft.Page) -> None:
    """Build and manage the Flet GUI lifecycle."""
    platform = page.platform.value if page.platform else ""
    container = await build_composition_root(platform=platform)

    asyncio.get_running_loop().set_exception_handler(asyncio_handler)

    greetings = ft.Text(
        "Welcome to Codex Query", theme_style=ft.TextThemeStyle.DISPLAY_MEDIUM
    )
    platform = ft.Text(
        f"Current platform: {platform}", theme_style=ft.TextThemeStyle.BODY_MEDIUM
    )

    async def on_close() -> None:
        await container.database.shutdown()

    page.on_close = on_close

    page.add(
        ft.Container(
            content=ft.Column(controls=[greetings, platform]),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )
    )


def main() -> None:
    """Application entry point to launch the Flet UI."""
    ft.run(_main)


if __name__ == "__main__":
    main()

"""Interactive home menu: the terminal equivalent of the UI's navigation rail."""

from __future__ import annotations

import contextlib

import questionary
from rich.panel import Panel

from codex_query.presentation.cli.indexing import add_screen, jobs_screen
from codex_query.presentation.cli.jobs import load_jobs
from codex_query.presentation.cli.library import library_screen
from codex_query.presentation.cli.prompts import Cancelled, ask
from codex_query.presentation.cli.runtime import Ctx
from codex_query.presentation.cli.settings import settings_screen


async def home(ctx: Ctx) -> None:
    """Library, add a book, indexing jobs, settings."""
    ctx.console.print(
        Panel.fit(
            "[bold]Codex Query[/]\n[dim]Ask questions about your ebooks[/]",
            border_style="cyan",
        )
    )
    while True:
        waiting = len(await load_jobs(ctx))
        badge = f" ({waiting} waiting)" if waiting else ""
        try:
            action: str = await ask(
                questionary.select(
                    "What would you like to do?",
                    choices=[
                        questionary.Choice("Library: browse and ask", "library"),
                        questionary.Choice("Add a book", "add"),
                        questionary.Choice(f"Indexing jobs{badge}", "jobs"),
                        questionary.Choice("Settings", "settings"),
                        questionary.Choice("Quit", "quit"),
                    ],
                )
            )
        except Cancelled:
            return
        if action == "quit":
            return
        screens = {
            "library": library_screen,
            "add": add_screen,
            "jobs": jobs_screen,
            "settings": settings_screen,
        }
        with contextlib.suppress(Cancelled):
            await screens[action](ctx)

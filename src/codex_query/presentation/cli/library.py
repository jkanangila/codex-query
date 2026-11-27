"""Browse the library; picking a book opens the conversation."""

from __future__ import annotations

import contextlib

import questionary

from codex_query.domain.models.document import Book
from codex_query.presentation.cli.chat import chat_screen
from codex_query.presentation.cli.indexing import add_screen, reindex_screen
from codex_query.presentation.cli.prompts import Cancelled, ask, pick_book
from codex_query.presentation.cli.render import library_tree
from codex_query.presentation.cli.runtime import Ctx


async def show_library(ctx: Ctx, query: str = "") -> list[Book]:
    """Print the (filtered) library tree and return the visible books."""
    books = await ctx.books()
    listing = ctx.uc.library.search_books(books, query)
    ctx.console.print(library_tree(listing, query))
    visible = [b for g in listing.series for b in g.books] + listing.standalone
    return visible


async def library_screen(ctx: Ctx) -> None:
    """The UI's library tab: browse, filter, add, re-index, ask."""
    query = ""
    while True:
        visible = await show_library(ctx, query)
        choices = [
            questionary.Choice("Ask about a book", "ask"),
            questionary.Choice("Filter by title or series", "filter"),
        ]
        if query:
            choices.append(questionary.Choice("Clear filter", "clear"))
        choices += [
            questionary.Choice("Add a book", "add"),
            questionary.Choice("Re-index books", "reindex"),
            questionary.Choice("Back", "back"),
        ]
        action: str = await ask(questionary.select("Library", choices=choices))
        match action:
            case "ask":
                with contextlib.suppress(Cancelled):
                    book = await pick_book(visible)
                    await chat_screen(ctx, book)
            case "filter":
                query = await ask(questionary.text("Filter:", default=query))
            case "clear":
                query = ""
            case "add":
                with contextlib.suppress(Cancelled):
                    await add_screen(ctx)
            case "reindex":
                with contextlib.suppress(Cancelled):
                    await reindex_screen(ctx)
            case _:
                return

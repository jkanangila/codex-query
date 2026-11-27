"""Small questionary helpers shared by every screen."""

from __future__ import annotations

from typing import Any

import click
import questionary

from codex_query.domain.models.document import Book
from codex_query.presentation.ui.utils.formatting import book_subtitle


class Cancelled(Exception):
    """The user dismissed a prompt (Ctrl-C)."""


async def ask(question: questionary.Question) -> Any:
    """Await a questionary prompt; raise ``Cancelled`` if it was dismissed."""
    answer: Any = await question.ask_async()
    if answer is None:
        raise Cancelled
    return answer


async def confirm(message: str, *, default: bool = False) -> bool:
    """Yes/no question."""
    return await ask(questionary.confirm(message, default=default))


def book_choices(books: list[Book]) -> list[questionary.Choice | questionary.Separator]:
    """Books grouped by series, mirroring the library screen of the UI."""
    series: dict[str, list[Book]] = {}
    standalone: list[Book] = []
    for book in books:
        if book.series:
            series.setdefault(book.series, []).append(book)
        else:
            standalone.append(book)

    def choice(book: Book) -> questionary.Choice:
        return questionary.Choice(
            title=f"{book.title}  ({book_subtitle(book)})", value=book
        )

    out: list[questionary.Choice | questionary.Separator] = []
    for name in sorted(series):
        out.append(questionary.Separator(f"── {name}"))
        out.extend(
            choice(b)
            for b in sorted(series[name], key=lambda b: b.meta.book_number or 0)
        )
    if standalone:
        if series:
            out.append(questionary.Separator("── Standalone"))
        out.extend(choice(b) for b in sorted(standalone, key=lambda b: b.title.lower()))
    return out


async def pick_book(books: list[Book], message: str = "Pick a book") -> Book:
    """Searchable book picker. Raises ``Cancelled`` on Ctrl-C."""
    if not books:
        msg = "The library is empty. Add a book first: codex-query add"
        raise click.ClickException(msg)
    return await ask(
        questionary.select(
            message,
            choices=book_choices(books),
            use_search_filter=True,
            use_jk_keys=False,
        )
    )


def resolve_book(books: list[Book], ref: str) -> Book:
    """Find a book by id, exact title, or unique title fragment."""
    ref = ref.strip()
    if ref.isdigit():
        for book in books:
            if book.id == int(ref):
                return book
    needle = ref.casefold()
    exact = [b for b in books if b.title.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    partial = [b for b in books if needle in b.title.casefold()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        msg = f"No book matches {ref!r}. See `codex-query library`."
        raise click.ClickException(msg)
    names = "\n".join(f"  #{b.id}  {b.title}" for b in partial[:10])
    msg = f"{ref!r} matches several books, be more specific or use the id:\n{names}"
    raise click.ClickException(msg)

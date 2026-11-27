"""``codex-query``: the command-line front end.

Run without a command for the interactive menu, or use a subcommand directly::

    codex-query                       # interactive menu
    codex-query library [FILTER]      # list books
    codex-query add BOOK.epub         # add + index (prompts for metadata)
    codex-query ask -b "Dune"         # chat with a book
    codex-query jobs [resume|cancel]  # unfinished indexing
    codex-query reindex --stale       # rebuild out-of-date indexes
    codex-query settings [show|test]  # providers, models, keys

Heavy imports are deferred into the commands so ``--help`` stays instant and
``--data-dir`` can be applied before the storage modules read their paths.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click

from codex_query.infrastructure.utils import load_env

if TYPE_CHECKING:
    from codex_query.presentation.cli.runtime import Ctx


@dataclass(frozen=True, slots=True)
class _State:
    verbose: bool


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _run(ctx: click.Context, fn: Callable[[Ctx], Awaitable[None]]) -> None:
    from codex_query.presentation.cli.runtime import run_session

    state = ctx.find_object(_State)
    run_session(fn, verbose=bool(state and state.verbose))


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "-v", "--verbose", is_flag=True, help="Log to stderr as well as the log file."
)
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="CODEX_QUERY_DATA_DIR",
    help="Where the library, index and settings live.",
)
@click.pass_context
def main(ctx: click.Context, verbose: bool, data_dir: Path | None) -> None:
    """Ask questions about your ebooks from the terminal."""
    if data_dir is not None:
        os.environ["FLET_APP_STORAGE_DATA"] = str(data_dir.expanduser().resolve())
    load_env()
    ctx.obj = _State(verbose)
    if ctx.invoked_subcommand is None:
        if not _interactive():
            click.echo(ctx.get_help())
            return
        from codex_query.presentation.cli.home import home

        _run(ctx, home)


# ------------------------------------------------------------------ library
@main.command()
@click.argument("query", required=False, default="")
@click.pass_context
def library(ctx: click.Context, query: str) -> None:
    """List the books in your library, optionally filtered by title or series."""
    from codex_query.presentation.cli.library import show_library

    async def run(c: Ctx) -> None:
        await show_library(c, query)

    _run(ctx, run)


# ---------------------------------------------------------------------- add
@main.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--title", default="", help="Title (single file only).")
@click.option("--series", default="", help="Series name.")
@click.option(
    "--number", default="", help="Book number in the series (single file only)."
)
@click.option("--language", default="", help="Language code, e.g. en.")
@click.option("--publisher", default="")
@click.option("--description", default="")
@click.option("--isbn", default="")
@click.option("--year", default="", help="Published year.")
@click.option("--subject", "subjects", multiple=True, help="Repeatable.")
@click.option(
    "--type",
    "document_type",
    type=click.Choice(["auto", "book", "article"]),
    default=None,
    help="Document type (default: auto-detect).",
)
@click.option("-y", "--yes", is_flag=True, help="Never prompt; use flags and defaults.")
@click.pass_context
def add(
    ctx: click.Context,
    paths: tuple[Path, ...],
    title: str,
    series: str,
    number: str,
    language: str,
    publisher: str,
    description: str,
    isbn: str,
    year: str,
    subjects: tuple[str, ...],
    document_type: str | None,
    yes: bool,
) -> None:
    """Add and index books: files, or folders of .epub files.

    With a single file the form asks for whatever the flags leave out. With
    several files (or --yes) nothing is asked: titles come from file names.
    Ctrl-C pauses indexing; resume it with `codex-query jobs resume`.
    """
    from codex_query.domain.models.document import DocumentType
    from codex_query.presentation.cli.indexing import (
        AddOptions,
        add_books,
        add_screen,
        expand_paths,
    )

    files = expand_paths(paths)
    if len(files) > 1 and (title or number):
        msg = "--title and --number only make sense with a single file."
        raise click.UsageError(msg)
    kinds = {
        "auto": DocumentType.UNKNOWN,
        "book": DocumentType.BOOK,
        "article": DocumentType.ARTICLE,
    }
    opts = AddOptions(
        title=title,
        series=series,
        number=number,
        language=language,
        publisher=publisher,
        description=description,
        isbn=isbn,
        year=year,
        subjects=", ".join(subjects),
        document_type=kinds[document_type] if document_type else None,
    )
    interactive = _interactive() and not yes

    async def run(c: Ctx) -> None:
        if not files:
            if not interactive:
                msg = "Give at least one file or folder."
                raise click.UsageError(msg)
            await add_screen(c)
            return
        if not await add_books(c, files, opts, interactive=interactive):
            raise click.exceptions.Exit(1)

    _run(ctx, run)


# ---------------------------------------------------------------------- ask
@main.command()
@click.argument("question", required=False)
@click.option(
    "-b", "--book", "book_ref", help="Book id or title (default: pick from a list)."
)
@click.option(
    "--no-sources", is_flag=True, help="Hide the passages behind each answer."
)
@click.pass_context
def ask(
    ctx: click.Context, question: str | None, book_ref: str | None, no_sources: bool
) -> None:
    """Chat with a book. Give a QUESTION for a single answer, or none to converse."""
    from codex_query.presentation.cli.chat import chat_screen
    from codex_query.presentation.cli.prompts import pick_book, resolve_book

    async def run(c: Ctx) -> None:
        books = await c.books()
        if book_ref:
            book = resolve_book(books, book_ref)
        elif _interactive():
            book = await pick_book(books)
        else:
            msg = "Pass --book when not running in a terminal."
            raise click.UsageError(msg)
        await chat_screen(
            c, book, question, once=question is not None, show_sources=not no_sources
        )

    _run(ctx, run)


# --------------------------------------------------------------------- jobs
@main.group(invoke_without_command=True)
@click.pass_context
def jobs(ctx: click.Context) -> None:
    """Show unfinished indexing jobs (interactive menu in a terminal)."""
    if ctx.invoked_subcommand is not None:
        return
    from codex_query.presentation.cli.indexing import jobs_list, jobs_screen

    _run(ctx, jobs_screen if _interactive() else jobs_list)


@jobs.command("resume")
@click.argument("job_id", required=False)
@click.option(
    "--all", "resume_all", is_flag=True, help="Resume every paused or failed job."
)
@click.pass_context
def jobs_resume_cmd(ctx: click.Context, job_id: str | None, resume_all: bool) -> None:
    """Resume paused or failed jobs (JOB_ID may be a unique prefix)."""
    from codex_query.presentation.cli.indexing import jobs_resume

    async def run(c: Ctx) -> None:
        await jobs_resume(c, job_id, resume_all=resume_all)

    _run(ctx, run)


@jobs.command("cancel")
@click.argument("job_id")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
@click.pass_context
def jobs_cancel_cmd(ctx: click.Context, job_id: str, yes: bool) -> None:
    """Cancel a job. A book created only by it is removed with its partial index."""
    from codex_query.presentation.cli.indexing import jobs_cancel

    async def run(c: Ctx) -> None:
        await jobs_cancel(c, job_id, assume_yes=yes)

    _run(ctx, run)


# ------------------------------------------------------------------ reindex
@main.command()
@click.argument("books", nargs=-1)
@click.option("--all", "all_books", is_flag=True, help="Re-index every book.")
@click.option(
    "--stale",
    is_flag=True,
    help="Re-index books out of date with the embedding settings.",
)
@click.pass_context
def reindex(
    ctx: click.Context, books: tuple[str, ...], all_books: bool, stale: bool
) -> None:
    """Rebuild book indexes. BOOKS are ids or titles; no arguments opens a picker."""
    from codex_query.presentation.cli.indexing import (
        reindex_books,
        reindex_screen,
        stale_book_ids,
    )
    from codex_query.presentation.cli.prompts import resolve_book

    async def run(c: Ctx) -> None:
        ids: set[int] = set()
        if books:
            library_books = await c.books()
            ids |= {
                b.id
                for ref in books
                if (b := resolve_book(library_books, ref)).id is not None
            }
        if all_books:
            ids |= {b.id for b in await c.books() if b.id is not None}
        if stale:
            ids |= set(await stale_book_ids(c))
        if ids:
            if not await reindex_books(c, sorted(ids)):
                raise click.exceptions.Exit(1)
        elif books or all_books or stale:
            c.console.print("[dim]Nothing to re-index.[/]")
        elif _interactive():
            await reindex_screen(c)
        else:
            msg = "Name books, or use --all / --stale."
            raise click.UsageError(msg)

    _run(ctx, run)


# ----------------------------------------------------------------- settings
@main.group(invoke_without_command=True)
@click.pass_context
def settings(ctx: click.Context) -> None:
    """View and edit settings (interactive menu in a terminal)."""
    if ctx.invoked_subcommand is not None:
        return
    from codex_query.presentation.cli.settings import settings_screen, show_settings

    async def show(c: Ctx) -> None:
        show_settings(c)

    _run(ctx, settings_screen if _interactive() else show)


@settings.command("show")
@click.pass_context
def settings_show(ctx: click.Context) -> None:
    """Print the current settings."""
    from codex_query.presentation.cli.settings import show_settings

    async def run(c: Ctx) -> None:
        show_settings(c)

    _run(ctx, run)


@settings.command("test")
@click.argument(
    "endpoint", type=click.Choice(["all", "chat", "embedding"]), default="all"
)
@click.pass_context
def settings_test(ctx: click.Context, endpoint: str) -> None:
    """Check that the chat and/or embedding endpoint is reachable (exit 1 if not)."""
    from codex_query.presentation.cli.settings import (
        require_endpoints,
        test_connections,
    )

    async def run(c: Ctx) -> None:
        if not await test_connections(c, require_endpoints(endpoint)):
            raise click.exceptions.Exit(1)

    _run(ctx, run)

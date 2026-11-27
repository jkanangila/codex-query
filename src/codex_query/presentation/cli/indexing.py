"""Add books, follow/resume/cancel indexing jobs, re-index books."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import click
import questionary
from rich.markup import escape
from rich.table import Table

from codex_query.domain.models.document import Book, DocumentType
from codex_query.domain.models.job import IndexingJob
from codex_query.domain.value_objects import QueueIndexJobRequest
from codex_query.presentation.cli.forms import (
    DOCUMENT_TYPE_LABELS,
    build_request,
    validate_isbn,
    validate_number,
    validate_year,
)
from codex_query.presentation.cli.jobs import (
    JobFollower,
    load_jobs,
    print_outcomes,
)
from codex_query.presentation.cli.prompts import ask, confirm
from codex_query.presentation.cli.render import jobs_table
from codex_query.presentation.cli.runtime import Ctx


@dataclass(frozen=True, slots=True)
class AddOptions:
    """Values given as command-line flags; prompts only ask for what is missing."""

    title: str = ""
    series: str = ""
    number: str = ""
    language: str = ""
    publisher: str = ""
    description: str = ""
    isbn: str = ""
    year: str = ""
    subjects: str = ""
    document_type: DocumentType | None = None

    @property
    def has_advanced(self) -> bool:
        """Whether any advanced field was already given on the command line."""
        return any(
            (
                self.language,
                self.publisher,
                self.description,
                self.isbn,
                self.year,
                self.subjects,
                self.document_type,
            )
        )


def expand_paths(paths: Sequence[Path]) -> list[Path]:
    """Files as given; a directory contributes its ``*.epub`` files."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            found = sorted(p for p in path.iterdir() if p.suffix.lower() == ".epub")
            if not found:
                click.echo(f"No .epub files in {path}", err=True)
            files.extend(found)
        else:
            files.append(path)
    return files


def _valid(check: Callable[[str], str | None]) -> Callable[[str], bool | str]:
    """Adapt a ``str | None`` validator to questionary's ``True | message``."""

    def validator(text: str) -> bool | str:
        return check(text) or True

    return validator


async def _collect_interactive(
    path: Path, opts: AddOptions, series_names: list[str]
) -> QueueIndexJobRequest:
    title: str = opts.title or await ask(questionary.text("Title", default=path.stem))
    series: str = opts.series
    if not series:
        series = await ask(
            questionary.autocomplete(
                "Series (optional)",
                choices=series_names,
                match_middle=True,
                ignore_case=True,
            )
        )
    number = opts.number
    if series.strip() and not number:
        number = await ask(
            questionary.text(
                "Book # in the series (optional)", validate=_valid(validate_number)
            )
        )

    language, publisher, description = opts.language, opts.publisher, opts.description
    isbn, year, subjects = opts.isbn, opts.year, opts.subjects
    document_type = opts.document_type or DocumentType.UNKNOWN
    if not opts.has_advanced and await confirm(
        "Edit advanced metadata? (empty fields are read from the file)", default=False
    ):
        language = await ask(questionary.text("Language (e.g. en)"))
        publisher = await ask(questionary.text("Publisher"))
        description = await ask(questionary.text("Description"))
        isbn = await ask(questionary.text("ISBN", validate=_valid(validate_isbn)))
        year = await ask(
            questionary.text("Published year", validate=_valid(validate_year))
        )
        subjects = await ask(questionary.text("Subjects (comma separated)"))
        document_type = await ask(
            questionary.select(
                "Document type",
                choices=[
                    questionary.Choice(label, kind)
                    for kind, label in DOCUMENT_TYPE_LABELS
                ],
            )
        )
    return build_request(
        path,
        title=title,
        series=series,
        number=number,
        language=language,
        publisher=publisher,
        description=description,
        isbn=isbn,
        year=year,
        subjects=subjects,
        document_type=document_type,
    )


def _summary(request: QueueIndexJobRequest) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("File", escape(str(request.source)))
    table.add_row("Title", escape(request.title))
    if request.series:
        suffix = f" #{request.number}" if request.number else ""
        table.add_row("Series", escape(request.series) + suffix)
    for label, value in (
        ("Language", request.language),
        ("Publisher", request.publisher),
        ("ISBN", request.isbn),
        ("Year", request.published_year),
        ("Subjects", ", ".join(request.subjects)),
    ):
        if value:
            table.add_row(label, escape(str(value)))
    return table


async def add_books(
    ctx: Ctx,
    paths: Sequence[Path],
    opts: AddOptions,
    *,
    interactive: bool,
) -> bool:
    """Queue indexing for ``paths`` and follow it. Returns ``True`` on success."""
    if not paths:
        ctx.console.print("[yellow]Nothing to add.[/]")
        return False
    prompt = interactive and len(paths) == 1
    series_names: list[str] = []
    if prompt:
        series_names = sorted({b.series for b in await ctx.books() if b.series})

    requests: list[QueueIndexJobRequest] = []
    for path in paths:
        if not path.is_file():
            msg = f"Not a file: {path}"
            raise click.ClickException(msg)
        try:
            if prompt:
                requests.append(await _collect_interactive(path, opts, series_names))
            else:
                requests.append(
                    build_request(
                        path,
                        title=opts.title if len(paths) == 1 else "",
                        series=opts.series,
                        number=opts.number if len(paths) == 1 else "",
                        language=opts.language,
                        publisher=opts.publisher,
                        description=opts.description,
                        isbn=opts.isbn,
                        year=opts.year,
                        subjects=opts.subjects,
                        document_type=opts.document_type or DocumentType.UNKNOWN,
                    )
                )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if prompt:
        ctx.console.print(_summary(requests[0]))
        if not await confirm("Start indexing?", default=True):
            return False

    with JobFollower(ctx.comp, ctx.console) as follower:
        for request in requests:
            job = IndexingJob(id=uuid4(), book_id=-1)
            follower.track(job, request.title)
            ctx.uc.indexing.start(job, request)
        outcomes = await follower.wait()
    return print_outcomes(ctx.console, outcomes)


def _validate_epub_path(value: object) -> bool | str:
    if not isinstance(value, str) or not value:
        return "Pick an existing file."
    return Path(value).expanduser().is_file() or "Pick an existing file."


async def add_screen(ctx: Ctx) -> None:
    """Interactive "add a book": pick a file, fill the form, watch it index."""
    raw: str = await ask(
        questionary.path("Ebook file (.epub)", validate=_validate_epub_path)
    )
    await add_books(ctx, [Path(raw).expanduser()], AddOptions(), interactive=True)


# --------------------------------------------------------------------- jobs
def _resolve_job(
    rows: Sequence[tuple[IndexingJob, str]], ref: str
) -> tuple[IndexingJob, str]:
    matches = [row for row in rows if str(row[0].id).startswith(ref.strip().lower())]
    if len(matches) != 1:
        msg = (
            f"No job matches {ref!r}."
            if not matches
            else f"{ref!r} matches several jobs, use more characters."
        )
        raise click.ClickException(msg)
    return matches[0]


async def resume_jobs(ctx: Ctx, rows: Sequence[tuple[IndexingJob, str]]) -> bool:
    """Resume the given jobs and follow them to completion."""
    with JobFollower(ctx.comp, ctx.console) as follower:
        for job, title in rows:
            follower.track(job, title)
            await ctx.uc.indexing.resume(job.id)
        outcomes = await follower.wait()
    return print_outcomes(ctx.console, outcomes)


async def jobs_list(ctx: Ctx) -> None:
    """Print unfinished jobs (non-interactive)."""
    rows = await load_jobs(ctx)
    if rows:
        ctx.console.print(jobs_table(rows))
    else:
        ctx.console.print("[dim]No pending, paused or failed indexing jobs.[/]")


async def jobs_resume(ctx: Ctx, ref: str | None, *, resume_all: bool) -> None:
    """Non-interactive resume of one job, or all resumable jobs."""
    rows = [row for row in await load_jobs(ctx) if row[0].can_resume]
    if not rows:
        ctx.console.print("[dim]Nothing to resume.[/]")
        return
    if ref:
        rows = [_resolve_job(rows, ref)]
    elif not resume_all and len(rows) > 1:
        ctx.console.print(jobs_table(rows))
        msg = "Several jobs can be resumed: pass a job id or --all."
        raise click.UsageError(msg)
    if not await resume_jobs(ctx, rows):
        raise click.exceptions.Exit(1)


async def jobs_cancel(ctx: Ctx, ref: str, *, assume_yes: bool) -> None:
    """Non-interactive cancel."""
    job, title = _resolve_job(await load_jobs(ctx), ref)
    if not assume_yes and not await confirm(_cancel_prompt(title)):
        return
    await ctx.uc.indexing.cancel(job.id)
    ctx.console.print(f"[dim]Cancelled “{escape(title)}”.[/]")


def _cancel_prompt(title: str) -> str:
    return (
        f"Cancel “{title}”? A book created only by this job is removed "
        "together with its partial index."
    )


async def jobs_screen(ctx: Ctx) -> None:
    """The UI's indexing tab: list, resume, cancel."""
    while True:
        rows = await load_jobs(ctx)
        if not rows:
            ctx.console.print("[dim]No pending, paused or failed indexing jobs.[/]")
            return
        ctx.console.print(jobs_table(rows))
        resumable = [row for row in rows if row[0].can_resume]
        choices: list[questionary.Choice] = []
        if resumable:
            choices.append(questionary.Choice("Resume a job", "resume"))
            if len(resumable) > 1:
                choices.append(questionary.Choice("Resume all", "all"))
        choices += [
            questionary.Choice("Cancel a job", "cancel"),
            questionary.Choice("Back", "back"),
        ]
        action: str = await ask(questionary.select("Indexing jobs", choices=choices))

        def job_choices(
            source: Sequence[tuple[IndexingJob, str]],
        ) -> list[questionary.Choice]:
            return [
                questionary.Choice(f"{title}  ({job.status.value})", (job, title))
                for job, title in source
            ]

        match action:
            case "resume":
                row = await ask(
                    questionary.select("Which job?", choices=job_choices(resumable))
                )
                await resume_jobs(ctx, [row])
            case "all":
                await resume_jobs(ctx, resumable)
            case "cancel":
                job, title = await ask(
                    questionary.select("Which job?", choices=job_choices(rows))
                )
                if await confirm(_cancel_prompt(title)):
                    await ctx.uc.indexing.cancel(job.id)
                    ctx.console.print(f"[dim]Cancelled “{escape(title)}”.[/]")
            case _:
                return


# ----------------------------------------------------------------- reindex
async def reindex_books(ctx: Ctx, book_ids: Sequence[int]) -> bool:
    """Queue a re-index for ``book_ids`` and follow it."""
    if not book_ids:
        ctx.console.print("[dim]Nothing to re-index.[/]")
        return True
    with JobFollower(ctx.comp, ctx.console) as follower:
        queued = await ctx.uc.indexing.reindex_document(list(book_ids))
        for job, title in queued:
            follower.track(job, title)
        if not queued:
            ctx.console.print("[dim]No matching books to re-index.[/]")
            return True
        outcomes = await follower.wait()
    return print_outcomes(ctx.console, outcomes)


async def stale_book_ids(ctx: Ctx) -> list[int]:
    """Books whose index does not match the current embedding settings."""
    embedding = ctx.uc.settings.get_current().embedding
    stale = await ctx.uc.settings.check_embedding_compatibility(
        embedding.provider, embedding.model
    )
    return [b.id for b in stale if b.id is not None]


async def reindex_screen(ctx: Ctx) -> None:
    """
    Interactive multi-select; books out of date with the settings come pre-checked.
    """
    books: list[Book] = await ctx.books()
    if not books:
        ctx.console.print("[dim]The library is empty.[/]")
        return
    stale = set(await stale_book_ids(ctx))
    chosen: list[int] = await ask(
        questionary.checkbox(
            "Books to re-index (space to toggle, enter to confirm)",
            choices=[
                questionary.Choice(
                    f"{b.title}" + ("  (out of date)" if b.id in stale else ""),
                    b.id,
                    checked=b.id in stale,
                )
                for b in books
                if b.id is not None
            ],
        )
    )
    if chosen and await confirm(f"Re-index {len(chosen)} book(s)?", default=True):
        await reindex_books(ctx, chosen)

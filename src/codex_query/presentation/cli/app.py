from __future__ import annotations

from pathlib import Path

import click
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from codex_query.application.config import Settings
from codex_query.application.services import ProgressEvent
from codex_query.bootstrap import build_services
from codex_query.infrastructure.logging import configure_logging
from codex_query.infrastructure.rag.utils import get_ollama_base_url

# Initialize Rich console instance for terminal formatting
console = Console()


@click.group()
@click.option("--verbose", is_flag=True, help="Enable detailed debug logging.")
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    help="Write detailed logs to this file.",
)
def main(verbose: bool, log_file: Path | None) -> None:
    """Private offline RAG for local EPUB collections."""
    configure_logging(verbose=verbose, log_file=log_file)


def _rich_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TextColumn("{task.percentage:>5.1f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        refresh_per_second=5,
    )


@main.command()
@click.argument("series", required=False)
@click.option(
    "--books",
    "books_dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
@click.option(
    "--data",
    "data_dir",
    type=click.Path(path_type=Path),
    default=Path(".codex-query"),
    show_default=True,
)
def index(series: str | None, books_dir: Path | None, data_dir: Path) -> None:
    """Incrementally index a SERIES directory of EPUB files."""
    # Load configurations
    settings = Settings.from_data_dir(data_dir, get_ollama_base_url())

    # Prompt user interactively if series parameter was omitted
    if series is None:
        series = questionary.text("Series name:").ask() or "default"

    # Prompt user interactively if book directory parameter was omitted
    if books_dir is None:
        if settings.books_dir is not None:
            books_dir = Path(settings.books_dir)
        else:
            selected = questionary.path(
                "Series EPUB directory:", only_directories=True
            ).ask()
            if not selected:
                raise click.Abort()
            books_dir = Path(selected)

    with _rich_progress() as rich_progress:
        tasks: dict[str, TaskID] = {}

        def report(event: ProgressEvent) -> None:
            task_id = tasks.get(event.phase)
            if task_id is None:
                task_id = rich_progress.add_task(
                    event.message, total=max(event.total, 1)
                )
                tasks[event.phase] = task_id
            rich_progress.update(
                task_id,
                description=event.message,
                total=max(event.total, 1),
                completed=event.current,
            )

        indexer, _, ledger = build_services(settings, report)
        try:
            result = indexer.index_series(series or "", books_dir, report)
        finally:
            ledger.close()
    console.print(
        Panel(
            f"Books: {result.books_seen}\nIndexed chapters: {result.chapters_indexed}\n"
            f"Skipped chapters: {result.chapters_skipped}\nChunks stored: {
                result.chunks_indexed
            }\n"
            f"Removed chapters: {result.chapters_removed}\nFailures: {result.failures}",
            title=f"Index complete — {series}",
        )
    )


@main.command()
@click.argument("series")
@click.argument("question")
@click.option(
    "--data",
    "data_dir",
    type=click.Path(path_type=Path),
    default=Path(".codex-query"),
    show_default=True,
)
@click.option("--limit", type=click.IntRange(1, 20), default=6, show_default=True)
def ask(series: str, question: str, data_dir: Path, limit: int) -> None:
    """Ask a question against one isolated SERIES collection."""
    settings = Settings.from_data_dir(data_dir, get_ollama_base_url())
    with _rich_progress() as rich_progress:
        tasks: dict[str, TaskID] = {}

        def report(event: ProgressEvent) -> None:
            task_id = tasks.get(event.phase)
            if task_id is None:
                task_id = rich_progress.add_task(
                    event.message, total=max(event.total, 1)
                )
                tasks[event.phase] = task_id
            rich_progress.update(
                task_id,
                description=event.message,
                total=max(event.total, 1),
                completed=event.current,
            )

        _, query, ledger = build_services(settings, report)
        try:
            answer = query.ask(series, question, limit)
        finally:
            ledger.close()
    console.print(Panel(answer.answer, title="Answer"))
    if answer.sources:
        console.print("\n[bold]Sources[/bold]")
        for i, source in enumerate(answer.sources, 1):
            console.print(
                f"[{i}] {source.metadata.get('book_title')} — {
                    source.metadata.get('chapter_title')
                }"
            )


@main.command()
@click.argument("series")
@click.option(
    "--data",
    "data_dir",
    type=click.Path(path_type=Path),
    default=Path(".codex-query"),
    show_default=True,
)
def status(series: str, data_dir: Path) -> None:
    """Show indexed chapter count for SERIES."""
    # Load settings and construct ledger service instance
    settings = Settings.from_data_dir(data_dir, get_ollama_base_url())
    _, _, ledger = build_services(settings)

    try:
        # Query total count of indexed chapters recorded for the series
        console.print(f"{series}: {ledger.indexed_count(series)} indexed chapters")
    finally:
        # Close connection to persistent ledger store
        ledger.close()


if __name__ == "__main__":
    main()

"""Pure Rich renderers: domain values in, renderables out."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from codex_query.application.use_cases.library.search_books import LibraryListing
from codex_query.domain.models.document import Book
from codex_query.domain.models.job import IndexingJob, JobStatus, Stage
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    EndpointConfig,
    LLMProvider,
)
from codex_query.domain.models.rag import SourceRef
from codex_query.domain.models.settings import ServiceSettings, Settings
from codex_query.presentation.ui.utils.formatting import (
    book_subtitle,
    job_counter_text,
    source_heading,
)

_STATUS_STYLE: dict[JobStatus, str] = {
    JobStatus.QUEUED: "dim",
    JobStatus.RUNNING: "cyan",
    JobStatus.PAUSED: "yellow",
    JobStatus.FAILED: "red",
    JobStatus.COMPLETED: "green",
    JobStatus.CANCELLED: "dim",
}


def stage_stepper(job: IndexingJob) -> str:
    """``parse > chunk > embed > store`` with the active stage highlighted."""
    current = list(Stage).index(job.stage)
    parts: list[str] = []
    for i, stage in enumerate(Stage):
        if i == current and job.status == JobStatus.RUNNING:
            parts.append(f"[bold cyan]{stage.value}[/]")
        elif i <= current:
            parts.append(f"[green]{stage.value}[/]")
        else:
            parts.append(f"[dim]{stage.value}[/]")
    return " > ".join(parts)


def library_tree(listing: LibraryListing, query: str = "") -> RenderableType:
    """The library as a tree: series branches, then standalone books."""
    if listing.is_empty:
        if query:
            return Text(f"No books match {query!r}.", style="dim")
        return Text(
            "Your library is empty. Add a book with: codex-query add", style="dim"
        )

    def label(book: Book) -> str:
        return (
            f"[dim]#{book.id}[/] {escape(book.title)}  "
            f"[dim]{escape(book_subtitle(book))}[/]"
        )

    title = f"Library — filter: {escape(query)}" if query else "Library"
    tree = Tree(f"[bold]{title}[/]")
    for group in listing.series:
        branch = tree.add(f"[bold cyan]{escape(group.name)}[/]")
        for book in group.books:
            branch.add(label(book))
    if listing.standalone:
        target = tree.add("[bold cyan]Standalone[/]") if listing.series else tree
        for book in listing.standalone:
            target.add(label(book))
    return tree


def jobs_table(rows: Sequence[tuple[IndexingJob, str]]) -> Table:
    """Pending, paused and failed indexing jobs."""
    table = Table(title="Indexing jobs", title_justify="left", show_lines=False)
    table.add_column("Job", style="dim", no_wrap=True)
    table.add_column("Book")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Note", overflow="fold")
    for job, title in rows:
        style = _STATUS_STYLE[job.status]
        progress = job_counter_text(job) or "—"
        note = (job.error or "") if job.status == JobStatus.FAILED else ""
        if job.status == JobStatus.PAUSED:
            note = f"resumes from chunk {job.checkpoint:,}"
        table.add_row(
            str(job.id)[:8],
            escape(title),
            f"[{style}]{job.status.value}[/]",
            escape(progress),
            escape(note),
        )
    return table


def sources_view(sources: Sequence[SourceRef]) -> RenderableType:
    """Passages that grounded the last answer."""
    lines: list[RenderableType] = []
    for source in sources:
        lines.append(Text(source_heading(source), style="bold"))
        lines.append(Text(source.excerpt, style="dim"))
    return Panel(
        Group(*lines),
        title="Sources",
        title_align="left",
        border_style="dim",
    )


def _key_state(service: ServiceSettings, source: str | None, required: bool) -> str:
    if service.has_api_key:
        where = f", {source}" if source else ""
        return f"[green]✓[/] configured [dim]({service.api_key_hash}{where})[/]"
    return "[red]✗ missing[/]" if required else "[dim]not required[/]"


def settings_panel(
    settings: Settings,
    chat_key_source: str | None,
    embedding_key_source: str | None,
) -> RenderableType:
    """Current settings, laid out like the UI's settings screen."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()

    def service(
        name: str,
        svc: ServiceSettings,
        configs: Mapping[LLMProvider, EndpointConfig],
        source: str | None,
    ) -> None:
        config = configs.get(svc.provider)
        provider = config.name if config else svc.provider.value
        required = config.auth.api_key_required if config else True
        table.add_row(f"{name} provider", escape(provider))
        table.add_row(f"{name} model", escape(svc.model))
        table.add_row(f"{name} base URL", escape(svc.base_url))
        table.add_row(f"{name} API key", _key_state(svc, source, required))
        table.add_row("", "")

    service("Chat", settings.chat, CHAT_PROVIDER_CONFIGS, chat_key_source)
    service(
        "Embedding",
        settings.embedding,
        EMBEDDING_PROVIDER_CONFIGS,
        embedding_key_source,
    )
    table.add_row("Preset", settings.preset_mode.value.title())
    table.add_row("Temperature", f"{settings.temperature:g}")
    table.add_row("Max answer tokens", f"{settings.max_tokens:,}")
    table.add_row("Passages (top-k)", str(settings.top_k))
    table.add_row("Context window", f"{settings.num_ctx:,}")
    table.add_row("Chunk size", f"{settings.chunk_size:,} [dim](new books only)[/]")
    table.add_row("", "")
    table.add_row(
        "Estimate",
        f"up to ~{settings.est_tokens():,} tokens per question "
        "[dim](free on local models)[/]",
    )
    return Panel(table, title="Settings", title_align="left")

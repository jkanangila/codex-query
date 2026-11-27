"""Follow background indexing jobs with a live Rich progress display.

Indexing runs as asyncio tasks inside the composition root and reports through
``JobEvents``. A terminal process only lives as long as its command, so the CLI
subscribes, renders progress, and waits until every tracked job settles.
Ctrl-C pauses the jobs instead of killing them: progress is checkpointed and
``codex-query jobs resume`` picks it up again.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from uuid import UUID

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from codex_query.domain.models.job import IndexingJob, JobStatus
from codex_query.presentation.cli.render import stage_stepper
from codex_query.presentation.cli.runtime import CliComposition, Ctx, log_path
from codex_query.presentation.ui.utils.formatting import fmt_eta

_SETTLED = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.PAUSED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
)
_POLL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """How one tracked job ended."""

    title: str
    status: JobStatus | None
    job: IndexingJob | None


class JobFollower:
    """Subscribe to job events, render progress, wait for jobs to settle.

    Create it *before* starting jobs so no early event is missed::

        with JobFollower(comp, console) as follower:
            follower.track(job, title)
            ctx.uc.indexing.start(job, request)
            outcomes = await follower.wait()
    """

    def __init__(self, comp: CliComposition, console: Console) -> None:
        """Remember the graph to subscribe to and where to draw."""
        self._comp = comp
        self._console = console
        self._titles: dict[UUID, str] = {}
        self._states: dict[UUID, IndexingJob] = {}
        self._unsubscribe: list[Callable[[], None]] = []

    def __enter__(self) -> Self:
        """Start listening to the job events."""
        events = self._comp.job_events
        self._unsubscribe = [
            events.on_job_update.subscribe(self._on_event),
            events.on_job_done.subscribe(self._on_event),
        ]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop listening."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []

    def _on_event(self, job: IndexingJob) -> None:
        self._states[job.id] = job

    def track(self, job: IndexingJob, title: str) -> None:
        """Show and wait for ``job``."""
        self._titles[job.id] = title
        self._states.setdefault(job.id, job)

    # ------------------------------------------------------------------ wait
    def _settled(self, job_id: UUID) -> bool:
        job = self._states.get(job_id)
        if job is not None and job.status in _SETTLED:
            return True
        # The task is gone but nobody reported a result (e.g. the file could not
        # be parsed before the book was registered): stop waiting, look it up.
        return not self._comp.job_runner.is_running(job_id)

    def _paint(self, progress: Progress, tasks: dict[UUID, TaskID]) -> None:
        for job_id, task in tasks.items():
            job = self._states.get(job_id)
            if job is None or (job.status == JobStatus.QUEUED and not job.total):
                progress.update(task, detail="[dim]waiting for a free slot…[/]")
                continue
            eta = (
                fmt_eta(job.eta) if job.eta and job.status == JobStatus.RUNNING else ""
            )
            progress.update(
                task,
                total=job.total or None,
                completed=job.done,
                detail=f"{stage_stepper(job)} [dim]{eta}[/]",
            )

    async def wait(self) -> list[JobOutcome]:
        """Render progress until every tracked job settles or Ctrl-C pauses them."""
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        handler_installed = False
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal.SIGINT, stop.set)
            handler_installed = True

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("{task.fields[detail]}"),
            console=self._console,
        )
        try:
            with progress:
                tasks = {
                    job_id: progress.add_task(escape(title), total=None, detail="")
                    for job_id, title in self._titles.items()
                }
                while True:
                    self._paint(progress, tasks)
                    if all(self._settled(job_id) for job_id in tasks):
                        break
                    if stop.is_set():
                        if handler_installed:  # a second Ctrl-C is a hard stop
                            loop.remove_signal_handler(signal.SIGINT)
                            handler_installed = False
                        progress.console.print("[yellow]Pausing — saving progress…[/]")
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(
                                self._comp.job_runner.cancel_all(), timeout=10
                            )
                        self._paint(progress, tasks)
                        break
                    await asyncio.sleep(_POLL_SECONDS)
        finally:
            if handler_installed:
                loop.remove_signal_handler(signal.SIGINT)
        return await self._outcomes()

    async def _outcomes(self) -> list[JobOutcome]:
        outcomes: list[JobOutcome] = []
        for job_id, title in self._titles.items():
            job = self._states.get(job_id)
            if job is None or job.status not in _SETTLED:
                async with self._comp.read_uow_factory() as uow:
                    stored = await uow.jobs.get(job_id)
                job = stored or job
            outcomes.append(JobOutcome(title, job.status if job else None, job))
        return outcomes


def print_outcomes(console: Console, outcomes: Sequence[JobOutcome]) -> bool:
    """Summarise how jobs ended. Returns ``True`` if every job completed."""
    all_ok = True
    for outcome in outcomes:
        title = escape(outcome.title)
        job = outcome.job
        match outcome.status:
            case JobStatus.COMPLETED:
                console.print(f"[green]✓[/] “{title}” is ready to ask")
            case JobStatus.PAUSED:
                all_ok = False
                at = f" at chunk {job.checkpoint:,}" if job else ""
                console.print(
                    f"[yellow]⏸[/] “{title}” paused{at}. "
                    "Continue with: [bold]codex-query jobs resume[/]"
                )
            case JobStatus.FAILED:
                all_ok = False
                reason = escape((job.error if job else None) or "unknown error")
                console.print(f"[red]✗[/] “{title}” failed: {reason}")
                console.print("  Retry with: [bold]codex-query jobs resume[/]")
            case JobStatus.CANCELLED:
                all_ok = False
                console.print(f"[dim]∅ “{title}” was cancelled[/]")
            case _:
                all_ok = False
                console.print(
                    f"[red]✗[/] “{title}” stopped before it could be saved. "
                    f"Details: {escape(str(log_path()))}"
                )
    return all_ok


async def load_jobs(ctx: Ctx) -> list[tuple[IndexingJob, str]]:
    """Unfinished jobs (queued, paused, failed) with their book titles."""
    rows: list[tuple[IndexingJob, str]] = []
    async with ctx.comp.read_uow_factory() as uow:
        for job in await uow.jobs.list_active():
            book = await uow.books.get_by_id(job.book_id)
            rows.append((job, book.title if book else "(unknown book)"))
    return rows

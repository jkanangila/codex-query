"""Event channels shared by background indexing jobs and their consumers."""

from codex_query.application.events.async_signal import AsyncSignal
from codex_query.application.events.signal import Signal
from codex_query.domain.models.job import IndexingJob


class JobEvents:
    """Owns the event channels emitted by indexing jobs."""

    def __init__(self) -> None:
        self.on_job_update: Signal[IndexingJob] = Signal()
        self.on_job_done: AsyncSignal[IndexingJob] = AsyncSignal()

    def clear(self) -> None:
        """Remove all subscribers from both job event channels."""
        self.on_job_update.clear()
        self.on_job_done.clear()

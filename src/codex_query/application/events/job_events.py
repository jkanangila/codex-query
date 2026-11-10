from codex_query.application.events.async_signal import AsyncSignal
from codex_query.application.events.signal import Signal
from codex_query.domain.models.job import IndexingJob


class JobEvents:
    def __init__(self) -> None:
        self.on_job_update: Signal[IndexingJob] = Signal()
        self.on_job_done: AsyncSignal[IndexingJob] = AsyncSignal()

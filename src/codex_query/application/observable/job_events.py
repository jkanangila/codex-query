from codex_query.application.observable.signal import Signal
from codex_query.domain.models.job import IndexingJob


class JobEvents:
    def __init__(self) -> None:
        self.on_job_update: Signal[IndexingJob] = Signal()
        self.on_job_done: Signal[IndexingJob] = Signal()

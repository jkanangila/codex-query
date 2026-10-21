from dataclasses import dataclass
from enum import StrEnum, auto
from uuid import UUID


class JobStatus(StrEnum):
    QUEUED = auto()
    RUNNING = auto()
    PAUSED = auto()
    FAILED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class Stage(StrEnum):
    PARSE = auto()
    CHUNK = auto()
    EMBED = auto()
    STORE = auto()


_ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset(
        {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.CANCELLED}
    ),
    JobStatus.RUNNING: frozenset(
        {JobStatus.PAUSED, JobStatus.FAILED, JobStatus.COMPLETED, JobStatus.CANCELLED}
    ),
    JobStatus.PAUSED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.FAILED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.CANCELLED}
)  # add FAILED here if failed jobs ever stop being retryable


class InvalidTransition(Exception): ...


@dataclass(slots=True)
class IndexingJob:
    id: UUID
    book_id: int
    status: JobStatus = JobStatus.QUEUED
    stage: Stage = Stage.PARSE
    done: int = 0
    total: int = 0
    checkpoint: int = 0  # chunks durably stored; resume starts here
    eta: float = 0.0
    error: str | None = None

    def _to(self, new: JobStatus) -> None:
        if new not in _ALLOWED[self.status]:
            raise InvalidTransition(f"{self.status} -> {new}")
        self.status = new

    def start(self) -> None:
        self._to(JobStatus.RUNNING)
        self.error = None

    def pause(self) -> None:
        self._to(JobStatus.PAUSED)

    def complete(self) -> None:
        self._to(JobStatus.COMPLETED)

    def cancel(self) -> None:
        self._to(JobStatus.CANCELLED)

    def fail(self, reason: str) -> None:
        self._to(JobStatus.FAILED)
        self.error = reason

    def record(
        self, stage: Stage, done: int, total: int, checkpoint: int, eta: float
    ) -> None:
        self.stage, self.done, self.total, self.eta = stage, done, total, eta
        self.checkpoint = max(self.checkpoint, checkpoint)  # never moves backwards

    @property
    def can_resume(self) -> bool:
        return self.status in (JobStatus.PAUSED, JobStatus.FAILED)

    @property
    def is_active(self) -> bool:
        return self.status not in TERMINAL_STATUSES

    @property
    def fraction(self) -> float:
        """Completion in ``[0, 1]``; ``0.0`` while the total is still unknown."""
        return self.done / self.total if self.total else 0.0

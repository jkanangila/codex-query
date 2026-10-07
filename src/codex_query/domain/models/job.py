from dataclasses import dataclass
from enum import StrEnum, auto


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


class InvalidTransition(Exception): ...


@dataclass(slots=True)
class IndexingJob:
    id: int | None
    book_id: int
    status: JobStatus = JobStatus.QUEUED
    stage: Stage = Stage.PARSE
    done: int = 0
    total: int = 0
    checkpoint: int = 0  # chunks durably stored; resume starts here
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

    def record(self, stage: Stage, done: int, total: int, checkpoint: int) -> None:
        self.stage, self.done, self.total = stage, done, total
        self.checkpoint = max(self.checkpoint, checkpoint)  # never moves backwards

    @property
    def can_resume(self) -> bool:
        return self.status in (JobStatus.PAUSED, JobStatus.FAILED)

    @property
    def is_active(self) -> bool:
        return self.status not in (JobStatus.COMPLETED, JobStatus.CANCELLED)

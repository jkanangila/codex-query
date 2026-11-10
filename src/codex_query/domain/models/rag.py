from dataclasses import dataclass
from enum import StrEnum, auto


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A passage the answer was grounded in. `number` matches the [n] citations."""

    number: int
    chunk_id: int
    chapter_title: str
    distance: float  # score
    excerpt: str

    @property
    def label(self) -> str:
        return f"[{self.number}] · Ch. {self.chapter_title}"


@dataclass(frozen=True, slots=True)
class SourcesFound:
    sources: list[SourceRef]


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class Completed:
    text: str  # the full answer, for persisting the message


class FailureKind(StrEnum):
    INVALID_INPUT = auto()
    INDEX_MISSING = auto()
    INDEX_MISMATCH = auto()
    AUTH = auto()
    RATE_LIMIT = auto()
    UNAVAILABLE = auto()
    OTHER = auto()


@dataclass(frozen=True, slots=True)
class Failed:
    kind: FailureKind
    message: str

    @property
    def retryable(self) -> bool:
        return self.kind in (FailureKind.RATE_LIMIT, FailureKind.UNAVAILABLE)


type AnswerEvent = SourcesFound | TextDelta | Completed | Failed

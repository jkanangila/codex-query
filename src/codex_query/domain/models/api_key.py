from dataclasses import dataclass, field
from datetime import datetime

from codex_query.domain.models.provider import LLMProvider

_MASK = "\u2022" * 4
_VISIBLE_TAIL = 4
_MIN_LEN_FOR_TAIL = 12


@dataclass(frozen=True, slots=True)
class ApiKey:
    """A provider credential. `value` is hidden from repr() so it can't be logged."""

    provider: LLMProvider
    value: str = field(repr=False)
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "API key must not be empty"
            raise ValueError(msg)

    @property
    def masked(self) -> str:
        """Safe-to-display form, e.g. '••••a1b2'."""
        if len(self.value) < _MIN_LEN_FOR_TAIL:
            return _MASK
        return f"{_MASK}{self.value[-_VISIBLE_TAIL:]}"

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from codex_query.domain.models.chat import (
    ChatMessage,
    ChatResult,
    GenerationParams,
)


class ChatPort(Protocol):
    """What the application needs from *any* chat model. No provider details."""

    async def complete(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> ChatResult: ...

    def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]:
        """Yield the answer incrementally as text deltas."""
        ...

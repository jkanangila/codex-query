from collections.abc import Sequence
from typing import Protocol

from codex_query.domain.models.embedding import EmbeddingInputType


class EmbeddingPort(Protocol):
    """What the application needs from *any* embedding model."""

    async def embed(
        self,
        texts: Sequence[str],
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> list[list[float]]:
        """Return one vector per text, in the same order as `texts`.

        Implementations split large inputs into provider-sized batches.
        """
        ...

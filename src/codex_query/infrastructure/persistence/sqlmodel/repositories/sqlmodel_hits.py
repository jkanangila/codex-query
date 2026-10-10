from collections.abc import Sequence

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.domain.models.chat import SearchHit
from codex_query.infrastructure.persistence.sqlmodel.models import TextChunk


async def load_hits(
    session: AsyncSession,
    chunk_ids: Sequence[int],
    distances: Sequence[float],
) -> list[SearchHit]:
    """Turn ranked (chunk_id, distance) pairs into SearchHits.

    SQLite stays the source of truth for chunk text and metadata, so every
    vector backend hydrates its results here. Ids whose chunk no longer exists
    (e.g. orphaned vectors) are skipped. Input order is preserved.
    """
    if not chunk_ids:
        return []
    result = await session.exec(
        select(TextChunk).where(col(TextChunk.id).in_(list(chunk_ids)))
    )
    by_id = {c.id: c for c in result.all()}
    hits: list[SearchHit] = []
    for chunk_id, distance in zip(chunk_ids, distances, strict=True):
        row = by_id.get(chunk_id)
        if row is None:
            continue
        hits.append(
            SearchHit(
                text=row.text,
                distance=distance,
                metadata={
                    **row.meta,
                    "chunk_id": chunk_id,
                    "chapter_id": row.chapter_id,
                    "chunk_index": row.chunk_index,
                },
            )
        )
    return hits

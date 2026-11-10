from collections.abc import Sequence
from dataclasses import fields

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.domain.models.chat import SearchHit
from codex_query.domain.models.document import TextChunkMetadata
from codex_query.infrastructure.database.sqlmodel.models import TextChunk

_META_FIELDS = {f.name for f in fields(TextChunkMetadata)}


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

        row_meta = TextChunkMetadata(
            **{k: v for k, v in row.meta.items() if k in _META_FIELDS}
        )

        hits.append(
            SearchHit(
                text=row.text,
                distance=distance,
                metadata={
                    "book_id": row_meta.book_id,
                    "book_title": row_meta.book_title,
                    "chapter_href": row_meta.chapter_href,
                    "chapter_id": row.chapter_id,
                    "chapter_order": row_meta.chapter_order,
                    "chapter_title": row_meta.chapter_title,
                    "chunk_id": chunk_id,
                    "chunk_index": row_meta.chunk_index,
                    "series": row_meta.series,
                },
            )
        )
    return hits

"""Hydration helper converting ranked chunk IDs and distances into search hits."""

from collections.abc import Sequence
from dataclasses import fields

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.domain.models.chat import SearchHit
from codex_query.domain.models.document import TextChunkMetadata
from codex_query.infrastructure.database.sqlmodel.models import TextChunk
from codex_query.infrastructure.logging.factory import create_logger

_META_FIELDS = {f.name for f in fields(TextChunkMetadata)}

logger = create_logger(__name__)


async def load_hits(
    session: AsyncSession,
    chunk_ids: Sequence[int],
    distances: Sequence[float],
) -> list[SearchHit]:
    """Hydrate ranked `(chunk_id, distance)` pairs into `SearchHit` objects.

    SQLite remains the source of truth for chunk text and metadata so all vector
    backends hydrate consistently. Chunk IDs with no matching `TextChunk` row
    (such as orphaned vectors) are skipped while preserving the input order of
    `chunk_ids`.

    Args:
        session: Active asynchronous database session used to query chunks.
        chunk_ids: Ranked chunk primary keys in desired result order.
        distances: Cosine distance scores paired one-to-one with `chunk_ids`.

    Returns:
        Hydrated `SearchHit` instances for existing chunks in `chunk_ids` order.

    Raises:
        ValueError: If `chunk_ids` and `distances` have different lengths.
    """
    if len(chunk_ids) != len(distances):
        raise ValueError("chunk_ids and distances must have the same length")
    if not chunk_ids:
        return []

    result = await session.exec(
        select(TextChunk).where(col(TextChunk.id).in_(list(chunk_ids)))
    )
    by_id = {c.id: c for c in result.all()}
    hits: list[SearchHit] = []
    skipped = 0

    for chunk_id, distance in zip(chunk_ids, distances, strict=True):
        row = by_id.get(chunk_id)
        if row is None:
            skipped += 1
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

    if skipped > 0:
        logger.warning(
            "Skipped %d orphaned chunk ID(s) while hydrating search hits",
            skipped,
        )

    return hits

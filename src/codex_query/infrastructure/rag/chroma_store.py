from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import override

import chromadb

from codex_query.application.ports.interfaces import IVectorStore
from codex_query.domain.models.document import SearchHit, TextChunk

logger = logging.getLogger(__name__)


class ChromaVectorStore(IVectorStore):
    """Persistent vector store implementation powered by ChromaDB.

    Manages document embeddings, metadata indexing, and similarity searching
    partitioned into distinct collections per book series.
    """

    def __init__(self, root: Path) -> None:
        """Initialize the ChromaDB persistent client.

        Args:
            root: Directory path where ChromaDB persistent database
            files will be stored.
        """
        # Ensure the target persistence directory exists on disk
        root.mkdir(parents=True, exist_ok=True)
        # Initialize disk-backed ChromaDB client
        self._client = chromadb.PersistentClient(path=str(root))

    @override
    def upsert(
        self,
        series: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Insert or update text chunks and their corresponding vector embeddings.

        Args:
            series: The book series identifier used to partition collections.
            chunks: Sequence of text chunks containing content and metadata.
            embeddings: Parallel sequence of dense vector embeddings for each chunk.
        """
        # Guard clause: skip processing if no chunks are provided
        if not chunks:
            return

        # Fetch existing series collection or create a new one using cosine
        # distance metric
        logger.debug("Chroma upsert: series=%r chunks=%d", series, len(chunks))
        collection = self._client.get_or_create_collection(
            name=_collection_name(series),
            metadata={"series": series, "hnsw:space": "cosine"},
        )

        # Upsert documents, vector embeddings, and metadata into ChromaDB
        collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=[list(e) for e in embeddings],
            metadatas=[c.metadata for c in chunks],
        )

    @override
    def delete_chapter(self, series: str, book_id: str, chapter_href: str) -> None:
        """Remove all indexed vector embeddings associated with a specific chapter.

        Args:
            series: The book series identifier.
            book_id: Unique identifier for the book.
            chapter_href: Relative link/path identifying the chapter within the book.
        """
        try:
            collection = self._client.get_collection(name=_collection_name(series))
            logger.debug(
                "Chroma delete chapter: series=%r book=%s chapter=%s",
                series,
                book_id,
                chapter_href,
            )

            # Delete all records matching both book_id and chapter_href metadata filters
            collection.delete(
                where={"$and": [{"book_id": book_id}, {"chapter_href": chapter_href}]}
            )
        except ValueError:
            logger.warning("Chroma delete failed! series=%s doesn't exist. %s", series)

    @override
    def search(
        self, series: str, embedding: Sequence[float], limit: int
    ) -> list[SearchHit]:
        """Perform a cosine similarity vector search against a series collection.

        Args:
            series: The target book series collection to query.
            embedding: The dense query vector embedding.
            limit: Maximum number of matching search hits to retrieve.

        Returns:
            List of SearchHit instances sorted by similarity distance.
        """
        try:
            collection = self._client.get_collection(name=_collection_name(series))
            logger.debug("Chroma query: series=%r limit=%d", series, limit)

            # Execute vector query against ChromaDB
            result = collection.query(
                query_embeddings=[list(embedding)], n_results=limit
            )

            # Safe extraction of primary result list from query payload
            documents = (result.get("documents") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]

            # Map raw query results into domain model SearchHit objects
            return [
                SearchHit(
                    text=str(d),
                    distance=float(distances[i]),
                    metadata=dict(metadatas[i] or {}),
                )
                for i, d in enumerate(documents)
            ]
        except ValueError:
            logger.warning("Chroma query failed! series=%s doesn't exist. %s", series)
            return []


def _collection_name(series: str) -> str:
    """Sanitize and format a book series string into a valid ChromaDB collection name.

    ChromaDB requires collection names to be between 3 and 63 characters, contain
    only alphanumeric characters, underscores, or hyphens, and start/end with an
    alphanumeric character.

    Args:
        series: Raw series string identifier.

    Returns:
        Sanitized, deterministic ChromaDB-compliant collection name.
    """
    # Replace invalid special characters with hyphens and strip leading/trailing hyphens
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", series.lower()).strip("-") or "default"

    # Truncate and prefix to ensure compliant length and clear naming structure
    return f"series-{clean[:50]}"

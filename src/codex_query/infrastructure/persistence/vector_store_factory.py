"""Composition-root helpers for choosing the vector backend."""

from collections.abc import Callable
from enum import StrEnum, auto
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.vector_store import VectorStorePort
from codex_query.infrastructure.paths import AppPaths
from codex_query.infrastructure.persistence.sqlmodel.repositories import (
    sqlmodel_vector_store,
)


class VectorBackend(StrEnum):
    """Supported vector storage engine implementations."""

    SQLITE = "sqlite"
    CHROMA = "chroma"


class MobilePlatform(StrEnum):
    """Supported mobile platforms for vector storage targeting."""

    ANDROID = auto()
    IOS = auto()


type VectorStoreFactory = Callable[[AsyncSession], VectorStorePort]


def backend_for_platform(platform: str) -> VectorBackend:
    """Determine the vector storage backend based on target platform.

    Uses SQLite + numpy on mobile platforms and Chroma elsewhere.

    Args:
        platform: Platform identifier string (e.g., `page.platform.value`).

    Returns:
        VectorBackend: The appropriate vector backend for the platform.
    """
    return (
        VectorBackend.SQLITE
        if platform.lower() in MobilePlatform
        else VectorBackend.CHROMA
    )


def build_vector_store_factory(
    backend: VectorBackend,
    data_dir: Path | None = None,
) -> VectorStoreFactory:
    """Construct a factory function for generating vector store instances.

    Imports `chromadb` lazily when selected to keep mobile builds lightweight.

    Args:
        backend: Target vector backend implementation type.
        data_dir: Optional custom storage path for persistent backends.

    Returns:
        VectorStoreFactory: A callable accepting an `AsyncSession` and
            returning a `VectorStorePort` instance.
    """
    if backend == VectorBackend.SQLITE:
        return sqlmodel_vector_store.SqlModelVectorStore

    import chromadb

    from codex_query.infrastructure.persistence.chromadb_vector_store import (
        ChromaVectorStore,
    )

    path = data_dir or AppPaths.app_storage_data_dir() / "db" / "chroma"
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    return lambda session: ChromaVectorStore(client, session)

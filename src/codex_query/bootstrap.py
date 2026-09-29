from __future__ import annotations

import os
from collections.abc import Callable

from ollama import Client

from codex_query.application.config import Settings
from codex_query.application.services import (
    IndexService,
    ProgressEvent,
    QueryServiceImpl,
)
from codex_query.infrastructure.epub.reader import EpubBookReader
from codex_query.infrastructure.persistence.sqlmodel.ledger import SQLModelIndexLedger
from codex_query.infrastructure.rag.chroma_store import ChromaVectorStore
from codex_query.infrastructure.rag.ollama_client import (
    OllamaEmbeddingModel,
    OllamaGenerator,
)


def build_services(
    settings: Settings,
    progress: Callable[[ProgressEvent], None] | None = None,
) -> tuple[IndexService, QueryServiceImpl, SQLModelIndexLedger]:
    host = os.environ.get("OLLAMA_HOST", settings.ollama_host)
    client = Client(host=host)
    reader = EpubBookReader()
    ledger = SQLModelIndexLedger(settings.sqlite_path)
    vectors = ChromaVectorStore(settings.chroma_dir)
    embeddings = OllamaEmbeddingModel(client, settings.embedding_model)
    generator = OllamaGenerator(client, settings.generation_model)
    indexer = IndexService(
        reader,
        ledger,
        vectors,
        embeddings,
        chunk_chars=settings.chunk_chars,
        chunk_overlap=settings.chunk_overlap,
        batch_size=settings.batch_size,
    )
    return indexer, QueryServiceImpl(embeddings, vectors, generator, progress), ledger

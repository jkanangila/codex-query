from dataclasses import dataclass
from functools import partial

import flet_secure_storage as fss
import httpx

from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.application.ports.chat import ChatPort
from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.application.ports.indexing import (
    DocumentParserPort,
    SettingsRepositoryPort,
    TextChunksPort,
)
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.services.chunks import TextChunkService
from codex_query.application.services.settings_service import SettingsService
from codex_query.infrastructure.document_parsing.ebook_lib.ebook_lib_document_parser import (  # noqa: E501
    EbookLibDocumentParser,
)
from codex_query.infrastructure.llm.factory import (
    create_chat_adapter,
    create_embedding_adapter,
)
from codex_query.infrastructure.logging.config import configure_logging
from codex_query.infrastructure.logging.factory import PythonLoggerFactory
from codex_query.infrastructure.persistence.sqlmodel.config import db_config
from codex_query.infrastructure.persistence.sqlmodel.database import SqlModelDatabase
from codex_query.infrastructure.persistence.sqlmodel.uow import (
    SqlReadOnlyUnitOfWork,
    SqlUnitOfWork,
)
from codex_query.infrastructure.persistence.vector_store_factory import (
    backend_for_platform,
    build_vector_store_factory,
)
from codex_query.infrastructure.security.secure_storage_api_keys import (
    SecureStorageApiKeyRepository,
)
from codex_query.infrastructure.settings.json_settings_repository import (
    JsonSettingsRepository,
)


@dataclass(frozen=True)
class ApplicationContainer:
    """Dependency injection container holding instantiated application services."""

    logger_factory: LoggerFactoryPort
    database: SqlModelDatabase
    uow_factory: UnitOfWorkFactory
    read_only_uow_factory: UnitOfWorkFactory
    document_parser: DocumentParserPort
    settings_service: SettingsService
    text_chunk_service: TextChunksPort
    async_http_client: httpx.AsyncClient
    chat_adapter: ChatPort
    embedding_adapter: EmbeddingPort


async def build_composition_root(platform: str) -> ApplicationContainer:
    """Build and initialize the dependency graph for the application.

    Args:
        platform: Target platform used to select vector store backend implementations.

    Returns:
        ApplicationContainer holding all configured ports and adapters.
    """
    # --------------------------------------------------------------------------
    # Logging & Security
    # --------------------------------------------------------------------------
    configure_logging()
    logger_factory: LoggerFactoryPort = PythonLoggerFactory()

    storage = fss.SecureStorage()
    api_keys_repository: ApiKeyRepositoryPort = SecureStorageApiKeyRepository(
        storage=storage
    )

    # --------------------------------------------------------------------------
    # Database & Persistence (SQL + Vector)
    # --------------------------------------------------------------------------
    database = SqlModelDatabase(db_config)
    await database.startup()

    vector_backend = backend_for_platform(platform=platform)
    vector_store_factory = build_vector_store_factory(backend=vector_backend)

    uow_factory: UnitOfWorkFactory = partial(
        SqlUnitOfWork,
        database.session_factory,
        vector_store_factory,
    )
    read_only_uow_factory: UnitOfWorkFactory = partial(
        SqlReadOnlyUnitOfWork,
        database.session_factory,
        vector_store_factory,
    )

    # --------------------------------------------------------------------------
    # Document Parsing & Domain Services
    # --------------------------------------------------------------------------
    document_parser: DocumentParserPort = EbookLibDocumentParser()
    text_chunk_service: TextChunksPort = TextChunkService(logger_factory=logger_factory)

    settings_repository: SettingsRepositoryPort = JsonSettingsRepository()
    settings_service = SettingsService(
        settings_repo=settings_repository,
        logger_factory=logger_factory,
        api_keys=api_keys_repository,
    )
    settings = await settings_service.load()

    # --------------------------------------------------------------------------
    # HTTP Client & LLM Adapters
    # --------------------------------------------------------------------------
    # Long read timeout configured to accommodate slow local Ollama inference
    async_http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    )

    chat_adapter: ChatPort = create_chat_adapter(
        client=async_http_client,
        settings=settings.chat,
    )
    embedding_adapter: EmbeddingPort = create_embedding_adapter(
        client=async_http_client,
        settings=settings.embedding,
    )

    return ApplicationContainer(
        logger_factory=logger_factory,
        database=database,
        uow_factory=uow_factory,
        read_only_uow_factory=read_only_uow_factory,
        document_parser=document_parser,
        settings_service=settings_service,
        text_chunk_service=text_chunk_service,
        async_http_client=async_http_client,
        chat_adapter=chat_adapter,
        embedding_adapter=embedding_adapter,
    )

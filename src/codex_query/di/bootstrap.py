from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from functools import cached_property
from types import TracebackType
from typing import Self

import flet_secure_storage as fss
import httpx

from codex_query.application.facade import IndexingJobsFacade, SettingsFacade, UseCases
from codex_query.application.pipelines.indexing_pipeline import IndexingPipeline
from codex_query.application.pipelines.parsing_pipeline import ParsePersistPipeline
from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.application.ports.chat import ChatPort
from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.application.ports.indexing import (
    DocumentParserPort,
    JobRunnerPort,
    SettingsRepositoryPort,
    TextChunksPort,
)
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.application.services.chunks import TextChunkService
from codex_query.application.services.settings_service import SettingsService
from codex_query.application.services.test_connection_service import (
    ConnectionTestService,
)
from codex_query.application.use_cases.indexing.cancel_indexing import CancelIndexing
from codex_query.application.use_cases.indexing.pause_indexing import PauseIndexing
from codex_query.application.use_cases.indexing.recover_interrupted_jobs import (
    RecoverInterruptedJobs,
)
from codex_query.application.use_cases.indexing.reindex_book import ReindexDocument
from codex_query.application.use_cases.indexing.resume_indexing import ResumeIndexing
from codex_query.application.use_cases.indexing.start_indexing import StartIndexing
from codex_query.application.use_cases.settings.apply_budget_preset import (
    ApplyBudgetPreset,
)
from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    CheckEmbeddingCompatibility,
)
from codex_query.application.use_cases.settings.get_draft import GetDraftSettings
from codex_query.application.use_cases.settings.get_settings import GetCurrentSettings
from codex_query.application.use_cases.settings.test_model_connection import (
    TestConnection,
)
from codex_query.application.use_cases.settings.update_settings import UpdateSettings
from codex_query.domain.models.settings import ServiceSettings, Settings
from codex_query.infrastructure.document_parsing.ebook_lib.ebook_lib_document_parser import (  # noqa: E501
    EbookLibDocumentParser,
)
from codex_query.infrastructure.jobs.asyncio_job_runner import AsyncioJobRunner
from codex_query.infrastructure.llm.factory import (
    create_chat_adapter,
    create_embedding_adapter,
)
from codex_query.infrastructure.logging.config import configure_logging
from codex_query.infrastructure.logging.factory import PythonLoggerFactory
from codex_query.infrastructure.persistence.sqlmodel.config import (
    DatabaseConfig,
)
from codex_query.infrastructure.persistence.sqlmodel.database import SqlModelDatabase
from codex_query.infrastructure.persistence.sqlmodel.uow import (
    SqlReadOnlyUnitOfWork,
    SqlUnitOfWork,
)
from codex_query.infrastructure.persistence.vector_store_factory import (
    VectorStoreFactory,
    backend_for_platform,
    build_vector_store_factory,
)
from codex_query.infrastructure.security.secure_storage_api_keys import (
    SecureStorageApiKeyRepository,
)
from codex_query.infrastructure.settings.json_settings_repository import (
    JsonSettingsRepository,
)
from codex_query.application.observable.job_events import JobEvents


class _LatestByKey[K, V]:
    """Single-slot cache that rebuilds its value whenever the key changes."""

    def __init__(self, build: Callable[[K], V]) -> None:
        self._build = build
        self._slot: tuple[K, V] | None = None

    def get(self, key: K) -> V:
        slot = self._slot
        if slot is not None and slot[0] == key:
            return slot[1]
        value = self._build(key)
        self._slot = (key, value)
        return value


class CompositionRoot:
    """Wires the object graph.

    Lifecycle: construct (no I/O) -> ``await start()`` -> use -> ``await aclose()``.
    Prefer ``async with CompositionRoot(...) as root:``. A root is single-use and
    belongs to one event loop: ``httpx.AsyncClient`` and the async engine are
    bound to the loop they first run on.
    """

    def __init__(self, platform: str, db_config: DatabaseConfig) -> None:
        self.platform = platform
        self.db_config = db_config
        self._exit_stack = AsyncExitStack()
        self._chat_cache = _LatestByKey[ServiceSettings, ChatPort](self._build_chat)
        self._embedding_cache = _LatestByKey[ServiceSettings, EmbeddingPort](
            self._build_embedding
        )

    # --------------------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------------------
    async def start(self) -> None:
        """Run the I/O-bound initialization. Call once, before using use_cases."""
        try:
            await self.database.startup()
            await self.settings_service.load()
        except BaseException:
            await self.aclose()  # don't leak a half-initialized engine
            raise

    async def aclose(self) -> None:
        """Close everything that was actually built, in reverse order."""
        await self._exit_stack.aclose()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --------------------------------------------------------------------------
    # Logging & Security
    # --------------------------------------------------------------------------
    @cached_property
    def logger_factory(self) -> LoggerFactoryPort:
        configure_logging()
        return PythonLoggerFactory()

    @cached_property
    def api_keys_repository(self) -> ApiKeyRepositoryPort:
        storage = fss.SecureStorage()
        return SecureStorageApiKeyRepository(storage=storage)

    # --------------------------------------------------------------------------
    # Database & Persistence (SQL + Vector)
    # --------------------------------------------------------------------------
    @cached_property
    def database(self) -> SqlModelDatabase:
        db = SqlModelDatabase(self.db_config)
        self._exit_stack.push_async_callback(db.shutdown)
        return db

    @cached_property
    def vector_store_factory(self) -> VectorStoreFactory:
        vector_backend = backend_for_platform(platform=self.platform)
        return build_vector_store_factory(backend=vector_backend)

    @cached_property
    def uow_factory(self) -> UnitOfWorkFactory:
        session_factory = self.database.session_factory
        vector_stores = self.vector_store_factory

        def make_uow() -> SqlUnitOfWork:
            return SqlUnitOfWork(session_factory, vector_stores)

        return make_uow

    @cached_property
    def read_uow_factory(self) -> UnitOfWorkFactory:
        session_factory = self.database.session_factory
        vector_stores = self.vector_store_factory

        def make_uow() -> SqlReadOnlyUnitOfWork:
            return SqlReadOnlyUnitOfWork(session_factory, vector_stores)

        return make_uow

    # --------------------------------------------------------------------------
    # Document Parsing & Domain Services
    # --------------------------------------------------------------------------
    @cached_property
    def document_parser(self) -> DocumentParserPort:
        return EbookLibDocumentParser()

    @cached_property
    def text_chunk_service(self) -> TextChunksPort:
        return TextChunkService(logger_factory=self.logger_factory)

    @cached_property
    def settings_service(self) -> SettingsService:
        settings_repository: SettingsRepositoryPort = JsonSettingsRepository()
        return SettingsService(
            settings_repo=settings_repository,
            logger_factory=self.logger_factory,
            api_keys=self.api_keys_repository,
        )

    @property
    def settings(self) -> Settings:
        """Live view of the current settings. Deliberately not cached here."""
        return self.settings_service.current

    # --------------------------------------------------------------------------
    # HTTP Client & LLM Adapters
    # --------------------------------------------------------------------------
    @cached_property
    def async_http_client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        )
        self._exit_stack.push_async_callback(client.aclose)
        return client

    def _build_chat(self, settings: ServiceSettings) -> ChatPort:
        return create_chat_adapter(client=self.async_http_client, settings=settings)

    def _build_embedding(self, settings: ServiceSettings) -> EmbeddingPort:
        return create_embedding_adapter(
            client=self.async_http_client, settings=settings
        )

    def chat_adapter(self) -> ChatPort:
        """Adapter for the *current* settings; rebuilt when they change."""
        return self._chat_cache.get(self.settings.chat)

    def embedding_adapter(self) -> EmbeddingPort:
        """Same contract as ``chat_adapter``."""
        return self._embedding_cache.get(self.settings.embedding)

    @cached_property
    def connection_test_service(self) -> ConnectionTestService:
        return ConnectionTestService(
            chat_factory=self._build_chat, embedding_factory=self._build_embedding
        )

    @cached_property
    def job_events(self) -> JobEvents:
        return JobEvents()

    @cached_property
    def job_runner(self) -> JobRunnerPort:
        return AsyncioJobRunner()

    @cached_property
    def parsing_pipeline(self) -> ParsePersistPipeline:
        return ParsePersistPipeline(
            self.uow_factory,
            self.read_uow_factory,
            self.document_parser,
            self.text_chunk_service,
            self.settings_service,
            self.logger_factory,
        )

    @cached_property
    def indexing_pipeline(self) -> IndexingPipeline:
        return IndexingPipeline(
            self.uow_factory,
            self.read_uow_factory,
            self._build_embedding,
            self.settings_service,
            self.logger_factory,
        )

    # --------------------------------------------------------------------------
    # Use cases
    # --------------------------------------------------------------------------
    @cached_property
    def use_cases(self) -> UseCases:
        settings_facade = SettingsFacade(
            apply_budget_preset=ApplyBudgetPreset(self.settings_service),
            check_embedding_compatibility=CheckEmbeddingCompatibility(
                self.read_uow_factory
            ),
            get_current=GetCurrentSettings(self.settings_service),
            get_new_draft=GetDraftSettings(self.settings_service),
            test_model_connection=TestConnection(self.connection_test_service),
            update_settings=UpdateSettings(self.settings_service),
        )

        start = StartIndexing(
            self.uow_factory,
            self.job_runner,
            self.job_events,
            self.parsing_pipeline,
            self.indexing_pipeline,
            self.logger_factory,
        )
        indexing_jobs = IndexingJobsFacade(
            cancel=CancelIndexing(
                self.uow_factory, self.job_runner, self.job_events, self.logger_factory
            ),
            pause=PauseIndexing(
                self.uow_factory, self.job_runner, self.job_events, self.logger_factory
            ),
            recover_interrupted_jobs=RecoverInterruptedJobs(
                self.uow_factory, self.logger_factory
            ),
            reindex_document=ReindexDocument(),
            resume=ResumeIndexing(self.read_uow_factory, start, self.logger_factory),
            start=start,
        )

        return UseCases(settings=settings_facade, indexing=indexing_jobs)

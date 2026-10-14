"""Joins non-secret settings (JSON) with API keys (platform secure storage)."""

import asyncio
from copy import deepcopy

from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.application.ports.indexing import SettingsRepositoryPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.errors import ProviderConfigurationError
from codex_query.domain.models.api_key import ApiKey
from codex_query.domain.models.provider import LLMProvider
from codex_query.domain.models.settings import Settings


class SettingsService:
    """Manages application settings and API key persistence.

    Committed settings (``current``) are replaced wholesale by ``load`` and
    ``save`` and are never mutated in place. UI code edits a draft obtained from
    ``new_draft`` and commits it with ``save``.
    """

    def __init__(
        self,
        settings_repo: SettingsRepositoryPort,
        api_keys: ApiKeyRepositoryPort,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the settings service with required ports.

        Args:
            settings_repo: Port for persisting and loading application settings.
            api_keys: Port for reading and writing provider API keys.
            logger_factory: Factory port for instantiating class loggers.
        """
        self._settings_repo = settings_repo
        self._settings: Settings | None = None
        self._api_keys = api_keys
        self._logger = logger_factory.create(__name__)
        # Serializes load/save so one can't overwrite the other mid-flight.
        # Reads of ``current`` stay lock-free.
        self._lock = asyncio.Lock()

    @property
    def current(self) -> Settings:
        """The committed settings. Treat as read-only; edit a draft instead.

        Raises:
            RuntimeError: If settings haven't been loaded yet.
        """
        if self._settings is None:
            raise RuntimeError("Settings aren't loaded; call load() first")
        return self._settings

    def new_draft(self) -> Settings:
        """Create an independent, editable copy of the committed settings.

        Returns:
            Settings: A deep copy that can be modified (e.g. as form state)
                without affecting the rest of the application until saved.
        """
        return deepcopy(self.current)

    async def load(self) -> None:
        """Load settings from storage and commit them as the current settings.

        Populates API keys from secure storage for chat and embedding services.
        """
        async with self._lock:
            self._logger.debug("Starting application settings loading sequence")
            settings = self._settings_repo.load()
            if settings is None:
                settings = Settings()

            for service_type, service in (
                ("chat", settings.chat),
                ("embedding", settings.embedding),
            ):
                key = await self._saved_key(service.provider)
                service.api_key = key
                if key:
                    self._logger.debug(
                        "Populated API key for %s provider '%s' from secure storage",
                        service_type,
                        service.provider.value,
                    )

            self._settings = settings  # fresh object; never mutated afterwards
            self._logger.debug("Application settings load complete")

    async def save(self, draft: Settings) -> None:
        """Validate and save settings along with provider API keys.

        The draft is copied, so later edits to it don't affect the committed
        settings. On success the copy becomes the current settings; on failure
        the previous current settings remain in effect.

        Args:
            draft: Settings configuration to persist and commit.

        Raises:
            ProviderConfigurationError: If conflicting API keys are provided for
                the same provider across services.
        """
        self._logger.info("Persisting application settings and API key updates")
        committed = self._normalized(draft)
        keys = self._collect_keys(committed)  # validate before touching anything

        async with self._lock:
            self._settings_repo.save(committed)

            for provider, value in keys.items():
                if value:
                    await self._api_keys.save(ApiKey(provider, value))
                    self._logger.debug(
                        "Saved API key for provider '%s'",
                        provider.value,
                    )
                else:
                    await self._api_keys.delete(provider)
                    self._logger.debug(
                        "Removed API key for provider '%s' from storage",
                        provider.value,
                    )

            self._settings = committed  # publish only after everything succeeded

        self._logger.info("Successfully persisted settings and provider API keys")

    async def change_chat_provider(
        self, draft: Settings, provider: LLMProvider
    ) -> bool:
        """Switch the chat provider and commit the result as the current settings.

        Args:
            draft: Draft settings instance to update (see ``new_draft``).
            provider: New chat provider to activate.

        Returns:
            bool: True if the default endpoint URL changed, False otherwise.
        """
        self._logger.info(
            "Changing chat provider from '%s' to '%s'",
            self.current.chat.provider.value,
            provider.value,
        )
        async with self._lock:
            draft = self.new_draft()
            key = await self._saved_key(provider)
            url_changed = draft.select_chat_provider(provider)
            draft.chat.api_key = key
            self._settings = draft  # swap, don't mutate: adapters see a new object
        self._log_key_restore(provider, key)
        return url_changed

    async def change_embedding_provider(
        self, draft: Settings, provider: LLMProvider
    ) -> bool:
        """Switch the embedding provider and commit the result as the current settings.

        Args:
            draft: Draft settings instance to update (see ``new_draft``).
            provider: New embedding provider to activate.

        Returns:
            bool: True if the default endpoint URL changed, False otherwise.
        """
        self._logger.info(
            "Changing embedding provider from '%s' to '%s'",
            draft.embedding.provider.value,
            provider.value,
        )
        async with self._lock:
            draft = self.new_draft()
            key = await self._saved_key(provider)
            url_changed = draft.select_embedding_provider(provider)
            draft.embedding.api_key = key
            self._settings = draft  # swap, don't mutate: adapters see a new object
        self._log_key_restore(provider, key)
        return url_changed

    async def providers_with_saved_key(self) -> list[LLMProvider]:
        """Retrieve a list of providers with saved API keys.

        Returns:
            list[LLMProvider]: Providers currently stored in the key repository.
        """
        self._logger.debug("Querying secure storage for providers with saved API keys")
        providers = await self._api_keys.list_providers()
        self._logger.debug("Found %d provider(s) with saved keys", len(providers))
        return providers

    async def _saved_key(self, provider: LLMProvider) -> str:
        """Look up the saved API key for a provider.

        Args:
            provider: Provider whose key to fetch.

        Returns:
            str: The saved key, or an empty string if none is stored.
        """
        stored = await self._api_keys.get(provider)
        return stored.value if stored is not None else ""

    def _log_key_restore(self, provider: LLMProvider, key: str) -> None:
        if key:
            self._logger.debug(
                "Restored API key for provider '%s'",
                provider.value,
            )
        else:
            self._logger.debug(
                "No saved API key found for provider '%s'",
                provider.value,
            )

    @staticmethod
    def _normalized(settings: Settings) -> Settings:
        """Copy settings and strip whitespace from API keys.

        Args:
            settings: Settings instance to copy.

        Returns:
            Settings: Independent copy with normalized API key values, so what
                is kept in memory matches what is stored.
        """
        copy = deepcopy(settings)
        for service in (copy.chat, copy.embedding):
            service.api_key = service.api_key.strip()
        return copy

    @staticmethod
    def _collect_keys(settings: Settings) -> dict[LLMProvider, str]:
        """Extract and validate API keys across all configured services.

        Args:
            settings: Settings instance containing service configurations.

        Returns:
            dict[LLMProvider, str]: Map of provider to validated API key value.

        Raises:
            ProviderConfigurationError: If chat and embedding services share
                a provider but supply different API key values.
        """
        keys: dict[LLMProvider, str] = {}
        for service in (settings.chat, settings.embedding):
            value = service.api_key.strip()
            if service.provider in keys and keys[service.provider] != value:
                msg = (
                    f"Chat and embeddings both use {service.provider.value} "
                    "but have different API keys; keys are stored per provider"
                )
                raise ProviderConfigurationError(msg)
            keys[service.provider] = value
        return keys

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

    API keys are stored per provider. A draft whose service has an empty key
    (e.g. right after switching provider) does not mean "delete this provider's
    key": ``save`` restores the stored key instead. Keys are only deleted through
    the explicit ``remove_api_key``.

    Attributes:
        _settings_repo: Port for persisting and loading application settings.
        _settings: Current active settings instance, or None if not loaded.
        _api_keys: Port for reading and writing provider API keys.
        _logger: Contextual component logger instance.
        _lock: Async lock for synchronizing load and save operations.
    """

    def __init__(
        self,
        settings_repo: SettingsRepositoryPort,
        api_keys: ApiKeyRepositoryPort,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initializes the SettingsService with required ports.

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

        Returns:
            The current active application settings.

        Raises:
            RuntimeError: If settings haven't been loaded yet.
        """
        if self._settings is None:
            raise RuntimeError("Settings aren't loaded; call load() first")
        return self._settings

    def new_draft(self) -> Settings:
        """Create an independent, editable copy of the committed settings.

        Returns:
            A deep copy that can be modified (e.g. as form state)
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
                        "Populated API key for %s provider '%s' from storage",
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

        A service with an empty key gets the key stored for its provider (so
        switching back to a provider keeps its key). Keys are written only when
        they differ from what is stored, and are never deleted here.

        Args:
            draft: Settings configuration to persist and commit.

        Raises:
            ProviderConfigurationError: If conflicting API keys are provided for
                the same provider across services.
        """
        self._logger.info("Persisting application settings and API key updates")
        committed = self._normalized(draft)

        async with self._lock:
            await self._restore_missing_keys(committed)
            keys = self._collect_keys(committed)  # validate before touching anything

            self._settings_repo.save(committed)

            for provider, value in keys.items():
                if value != await self._saved_key(provider):
                    await self._api_keys.save(ApiKey(provider, value))
                    self._logger.debug(
                        "Saved API key for provider '%s'",
                        provider.value,
                    )

            self._settings = committed  # publish only after success

        self._logger.info("Successfully persisted settings and API keys")

    async def remove_api_key(self, provider: LLMProvider) -> None:
        """Delete a provider's stored API key and clear it from current settings.

        This is the only place a key is deleted; ``save`` never does it.

        Args:
            provider: Provider whose key to remove.
        """
        self._logger.info("Removing API key for provider '%s'", provider.value)
        async with self._lock:
            await self._api_keys.delete(provider)
            active_draft = self.new_draft()
            for service in (active_draft.chat, active_draft.embedding):
                if service.provider == provider:
                    service.api_key = ""
            self._settings = active_draft

    async def _restore_missing_keys(self, settings: Settings) -> None:
        """Fill empty keys from secure storage, in place.

        An empty key on a draft means "not entered in this session", not "delete
        the stored key" (e.g. the key is cleared when the provider is switched).

        Args:
            settings: Normalized settings copy to complete.
        """
        for service in (settings.chat, settings.embedding):
            if not service.api_key:
                service.api_key = await self._saved_key(service.provider)
                self._log_key_restore(service.provider, service.api_key)

    async def _saved_key(self, provider: LLMProvider) -> str:
        """Look up the saved API key for a provider.

        Args:
            provider: Provider whose key to fetch.

        Returns:
            The saved key, or an empty string if none is stored.
        """
        stored = await self._api_keys.get(provider)
        return stored.value if stored is not None else ""

    def _log_key_restore(self, provider: LLMProvider, key: str) -> None:
        """Log whether a saved key was successfully restored for a provider.

        Args:
            provider: Provider whose key state was evaluated.
            key: The retrieved API key string.
        """
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
            Independent copy with normalized API key values.
        """
        copy = deepcopy(settings)
        for service in (copy.chat, copy.embedding):
            service.api_key = service.api_key.strip()
        return copy

    @staticmethod
    def _collect_keys(settings: Settings) -> dict[LLMProvider, str]:
        """Extract the non-empty API key of each provider in use.

        Args:
            settings: Settings instance containing service configurations.

        Returns:
            Map of provider to API key value. Providers without a key are omitted.

        Raises:
            ProviderConfigurationError: If chat and embedding use the same
                provider with different keys.
        """
        keys: dict[LLMProvider, str] = {}
        for service in (settings.chat, settings.embedding):
            value = service.api_key.strip()
            if not value:
                continue
            existing = keys.get(service.provider)
            if existing is not None and existing != value:
                msg = (
                    f"Chat and embedding use different API keys for "
                    f"{service.provider.value}; a provider has a single key"
                )
                raise ProviderConfigurationError(msg)
            keys[service.provider] = value
        return keys

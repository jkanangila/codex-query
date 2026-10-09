"""Joins non-secret settings (JSON) with API keys (encrypted sqlite)."""

from codex_query.application.ports.indexing import SettingsRepositoryPort
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.errors import ProviderConfigurationError
from codex_query.domain.models.api_key import ApiKey
from codex_query.domain.models.provider import LLMProvider
from codex_query.domain.models.settings import ServiceSettings, Settings


class SettingsService:
    """Manages application settings and API key persistence/migration."""

    def __init__(
        self,
        settings_repo: SettingsRepositoryPort,
        uow_factory: UnitOfWorkFactory,
        read_only_uow_factory: UnitOfWorkFactory,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the settings service with required ports.

        Args:
            settings_repo: Port for persisting and loading application settings.
            uow_factory: Factory for unit of work instances managing key storage.
            logger_factory: Factory port for instantiating class loggers.
        """
        self._settings_repo = settings_repo
        self._uow_factory = uow_factory
        self._read_only_uow_factory = read_only_uow_factory
        self._logger = logger_factory.create(__name__)

    async def load(self) -> Settings:
        """Load settings from storage and handle legacy API key migrations.

        Populates API keys from encrypted storage for chat and embedding services.
        If legacy plaintext/Fernet keys exist in pre-v2 settings files, they are
        automatically migrated to encrypted storage and scrubbed from the JSON file.

        Returns:
            Settings: Loaded or default settings instance with updated API keys.
        """
        self._logger.debug("Starting application settings loading sequence")
        settings = self._settings_repo.load() or Settings()
        migrated = False

        for service_type, service in (
            ("chat", settings.chat),
            ("embedding", settings.embedding),
        ):
            async with self._read_only_uow_factory() as uow:
                stored = await uow.api_keys.get(service.provider)

            if stored is not None:
                service.api_key = stored.value
                self._logger.debug(
                    "Populated API key for %s provider '%s' from secure storage",
                    service_type,
                    service.provider.value,
                )
            elif service.api_key.strip():
                # The repository only yields a key from a pre-v2 settings file.
                legacy = service.api_key.strip()
                async with self._uow_factory() as uow:
                    await uow.api_keys.save(ApiKey(service.provider, legacy))
                    await uow.commit()
                migrated = True
                self._logger.info(
                    "Successfully migrated legacy API key for provider '%s' to "
                    "secure storage",
                    service.provider.value,
                )

        if migrated:
            self._logger.info(
                "Saving sanitized settings file to remove legacy API keys"
            )
            self._settings_repo.save(settings)  # rewrites the file without the key

        self._logger.debug("Application settings load complete")
        return settings

    async def save(self, settings: Settings) -> None:
        """Validate and save settings along with provider API keys.

        Args:
            settings: Settings configuration to persist.

        Raises:
            ProviderConfigurationError: If conflicting API keys are provided for
                the same provider across services.
        """
        self._logger.info("Persisting application settings and API key updates")
        try:
            keys = self._collect_keys(settings)  # validate before touching anything
        except ProviderConfigurationError as err:
            self._logger.error(
                "Validation failed during settings save: %s",
                err,
            )
            raise

        self._settings_repo.save(settings)

        for provider, value in keys.items():
            async with self._uow_factory() as uow:
                if value:
                    await uow.api_keys.save(ApiKey(provider, value))
                    self._logger.debug(
                        "Saved encrypted API key for provider '%s'",
                        provider.value,
                    )
                else:
                    await uow.api_keys.delete(provider)
                    self._logger.debug(
                        "Removed API key for provider '%s' from storage",
                        provider.value,
                    )
                await uow.commit()

        self._logger.info("Successfully persisted settings and provider API keys")

    async def change_chat_provider(
        self, settings: Settings, provider: LLMProvider
    ) -> bool:
        """Switch the chat provider and load its saved API key.

        Args:
            settings: Target settings instance to update.
            provider: New chat provider to activate.

        Returns:
            bool: True if the default endpoint URL changed, False otherwise.
        """
        self._logger.info(
            "Changing chat provider from '%s' to '%s'",
            settings.chat.provider.value,
            provider.value,
        )
        url_changed = settings.select_chat_provider(provider)
        await self._restore_key(settings.chat)
        return url_changed

    async def change_embedding_provider(
        self, settings: Settings, provider: LLMProvider
    ) -> bool:
        """Switch the embedding provider and load its saved API key.

        Args:
            settings: Target settings instance to update.
            provider: New embedding provider to activate.

        Returns:
            bool: True if the default endpoint URL changed, False otherwise.
        """
        self._logger.info(
            "Changing embedding provider from '%s' to '%s'",
            settings.embedding.provider.value,
            provider.value,
        )
        url_changed = settings.select_embedding_provider(provider)
        await self._restore_key(settings.embedding)
        return url_changed

    async def providers_with_saved_key(self) -> list[LLMProvider]:
        """Retrieve a list of providers with saved API keys.

        Returns:
            list[LLMProvider]: Providers currently stored in the key repository.
        """
        self._logger.debug("Querying secure storage for providers with saved API keys")
        async with self._read_only_uow_factory() as uow:
            providers = await uow.api_keys.list_providers()
        self._logger.debug("Found %d provider(s) with saved keys", len(providers))
        return providers

    async def _restore_key(self, service: ServiceSettings) -> None:
        """Restore the API key for a given service settings object.

        Args:
            service: Service configuration instance to update with a saved key.
        """
        async with self._read_only_uow_factory() as uow:
            stored = await uow.api_keys.get(service.provider)
        if stored is not None:
            service.api_key = stored.value
            self._logger.debug(
                "Restored API key for provider '%s'",
                service.provider.value,
            )
        else:
            service.api_key = ""
            self._logger.debug(
                "No saved API key found for provider '%s'",
                service.provider.value,
            )

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

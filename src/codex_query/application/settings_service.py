from codex_query.application.ports.indexing import ISettingsRepository
from codex_query.application.ports.logger import ILogger
from codex_query.domain.models.provider import LLMProvider
from codex_query.domain.models.settings import (
    PresetMode,
    ProviderUrlResolver,
    Settings,
)


class SettingsService:
    """Application service for managing settings state and persistence."""

    def __init__(
        self,
        repository: ISettingsRepository,
        url_resolver: ProviderUrlResolver,
        logger: ILogger,
    ) -> None:
        """Initialize the settings service.

        Args:
            repository: Repository interface for loading/saving settings.
            url_resolver: Resolver strategy for LLM provider base URLs.
            logger: Logger instance for application logging.
        """
        self._repository = repository
        self.url_resolver = url_resolver
        self._logger = logger
        self.settings: Settings = self._initialize_settings()

    def _initialize_settings(self) -> Settings:
        """Load existing settings from repository or create and save defaults.

        Returns:
            Settings: The active settings instance.
        """
        existing = self._repository.load()
        if existing:
            self._logger.info("Loaded existing settings from repository.")
            return existing

        self._logger.info("No existing settings found. Initializing defaults.")
        default_settings = Settings()
        default_settings.base_url = self.url_resolver.get_default_url(
            default_settings.provider
        )
        self._repository.save(default_settings)
        self._logger.info(
            "Default settings saved with provider: %s", default_settings.provider
        )
        return default_settings

    def change_provider(self, provider: LLMProvider, auto_save: bool = True) -> bool:
        """Change the active LLM provider and update provider URL.

        Args:
            provider: The new LLM provider to switch to.
            auto_save: Whether to persist changes immediately. Defaults to True.

        Returns:
            bool: True if the provider was changed, False if already set to provider.
        """
        old_provider = self.settings.provider
        changed = self.settings.select_provider(provider, self.url_resolver)

        if changed:
            self._logger.info(
                "Changed LLM provider from '%s' to '%s'.", old_provider, provider
            )
            if auto_save:
                self.save()
        else:
            self._logger.debug("Provider is already set to '%s'. No change.", provider)

        return changed

    def change_preset(self, mode: PresetMode, auto_save: bool = True) -> None:
        """Change the configuration preset mode.

        Args:
            mode: The target preset mode to apply.
            auto_save: Whether to persist changes immediately. Defaults to True.
        """
        self.settings.select_preset(mode)
        self._logger.info("Changed preset mode to '%s'.", mode)

        if auto_save:
            self.save()

    def save(self) -> None:
        """Persist current settings to repository."""
        self._repository.save(self.settings)
        self._logger.info("Settings saved successfully.")

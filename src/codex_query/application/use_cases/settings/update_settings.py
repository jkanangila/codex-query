"""Application use case for updating and persisting application settings."""

from codex_query.application.services.settings_service import SettingsService
from codex_query.domain.models.settings import Settings


class UpdateSettings:
    """Use case for updating application settings with new values or providers."""

    def __init__(self, settings_service: SettingsService) -> None:
        """Initialize the use case with required services.

        Args:
            settings_service: Service responsible for settings and key persistence.
        """
        self._settings_service = settings_service

    async def __call__(self, draft: Settings) -> bool:
        """Execute the settings update use case.

        Args:
            payload: Incoming update data containing optional service
                and scalar field updates.
            settings: Current application settings instance to modify.

        Returns:
            bool: True if any changes were made and saved, False otherwise.
        """
        # Create a working copy of the payload to track processed attributes
        await self._settings_service.save(draft)
        return True

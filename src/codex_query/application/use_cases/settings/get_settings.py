from codex_query.application.services.settings_service import SettingsService
from codex_query.domain.models.settings import Settings


class GetCurrentSettings:
    def __init__(self, settings_service: SettingsService) -> None:
        self._service = settings_service

    def __call__(self) -> Settings:
        return self._service.current

from dataclasses import replace

from codex_query.application.services.settings_service import SettingsService
from codex_query.domain.models.settings import PresetMode, Settings


class ApplyBudgetPreset:
    def __init__(self, settings_service: SettingsService) -> None:
        self._settings_service = settings_service

    async def execute(self, preset: PresetMode, settings: Settings) -> Settings:
        new = replace(settings)
        new.select_preset(preset)

        await self._settings_service.save(new)

        return new

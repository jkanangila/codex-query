"""Presentation view model for application settings and configuration management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from codex_query.application.facade import SettingsFacade
from codex_query.domain.models.connection import ConnectionTestResult
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    LLMProvider,
)
from codex_query.domain.models.settings import PresetMode, Settings
from codex_query.domain.value_objects import PendingEmbeddingChange
from codex_query.presentation.ui.viewmodels.events import UiEvents
from codex_query.presentation.ui.viewmodels.observable import ObservableObject

CHAT_PROVIDER_OPTIONS: dict[str, LLMProvider] = {
    config.name: provider for provider, config in CHAT_PROVIDER_CONFIGS.items()
}
EMBEDDING_PROVIDER_OPTIONS: dict[str, LLMProvider] = {
    config.name: provider for provider, config in EMBEDDING_PROVIDER_CONFIGS.items()
}

# Keys representing attribute names on the Settings model.
TuningKeys = Literal[
    "temperature",
    "max_tokens",
    "top_k",
    "num_ctx",
    "chunk_size",
]


@dataclass(frozen=True, slots=True)
class _TuningSpec:
    """Static description of one tuning slider and the setting it edits."""

    key: TuningKeys
    label: str
    minimum: float
    maximum: float
    step: float
    cast: Callable[[float], float]
    """Converts the slider's float to the setting's real type."""


@dataclass(frozen=True, slots=True)
class TuningSlider:
    """Representation of a slider as the view should render it."""

    key: TuningKeys
    label: str
    minimum: float
    maximum: float
    step: float
    value: float

    @property
    def value_text(self) -> str:
        """Formatted string representation of the current slider value."""
        return f"{self.value:g}"


_SPECS = [
    _TuningSpec(
        "temperature",
        "Temperature",
        0,
        1,
        0.05,
        lambda v: round(v, 2),
    ),
    _TuningSpec(
        "max_tokens",
        "Max answer tokens",
        100,
        2000,
        100,
        lambda v: int(v),
    ),
    _TuningSpec(
        "top_k",
        "Passages retrieved (top-k)",
        1,
        12,
        1,
        lambda v: int(v),
    ),
    _TuningSpec(
        "num_ctx",
        "Context window",
        1024,
        16384,
        1024,
        lambda v: int(v),
    ),
    _TuningSpec(
        "chunk_size",
        "Chunk size (new books only)",
        200,
        2000,
        100,
        lambda v: int(v),
    ),
]
_SPECS_BY_KEY = {s.key: s for s in _SPECS}


class SettingsViewModel(ObservableObject):
    """View model managing user preferences, parameters, and service connections."""

    def __init__(self, use_cases: SettingsFacade, events: UiEvents) -> None:
        super().__init__()
        self._use_cases = use_cases
        self._events = events

        self._test_result_chat: ConnectionTestResult | None = None
        self._test_result_embedding: ConnectionTestResult | None = None
        self._is_testing_chat: bool = False
        self._is_testing_embedding: bool = False

        self._pending_embedding: PendingEmbeddingChange | None = None

    @property
    def settings(self) -> Settings:
        """Retrieve current application settings."""
        return self._use_cases.get_current()

    # ── Text Fields ───────────────────────────────────────────────────────
    @property
    def chat_base_url(self) -> str:
        """Base URL for the chat service provider."""
        return self.settings.chat.base_url

    async def set_chat_base_url(self, value: str) -> None:
        """Update and save the chat service base URL."""
        draft = self._use_cases.get_new_draft()
        draft.chat.base_url = value
        await self._use_cases.update_settings(draft)

    @property
    def embedding_base_url(self) -> str:
        """Base URL for the embedding service provider."""
        return self.settings.embedding.base_url

    async def set_embedding_base_url(self, value: str) -> None:
        """Update and save the embedding service base URL."""
        draft = self._use_cases.get_new_draft()
        draft.embedding.base_url = value
        await self._use_cases.update_settings(draft)

    @property
    def chat_api_key(self) -> str:
        """API key for the chat service provider."""
        return self.settings.chat.api_key

    async def set_chat_api_key(self, value: str) -> None:
        """Update and save the chat API key."""
        draft = self._use_cases.get_new_draft()
        draft.chat.api_key = value
        await self._use_cases.update_settings(draft)

    @property
    def embedding_api_key(self) -> str:
        """API key for the embedding service provider."""
        return self.settings.embedding.api_key

    async def set_embedding_api_key(self, value: str) -> None:
        """Update and save the embedding API key."""
        draft = self._use_cases.get_new_draft()
        draft.embedding.api_key = value
        await self._use_cases.update_settings(draft)

    @property
    def chat_model(self) -> str:
        """Active model name for the chat service."""
        return self.settings.chat.model

    async def set_chat_model(self, value: str) -> None:
        """Update and save the active chat model."""
        draft = self._use_cases.get_new_draft()
        draft.chat.model = value
        await self._use_cases.update_settings(draft)

    @property
    def embedding_model(self) -> str:
        """Active model name for the embedding service."""
        return self.settings.embedding.model

    async def set_embedding_model(self, value: str) -> None:
        """Update and stage changes for the active embedding model."""
        draft = self._use_cases.get_new_draft()
        draft.embedding.model = value.strip()
        await self._stage_embedding_change(draft)

    # ── Select Fields ─────────────────────────────────────────────────────
    @property
    def chat_provider(self) -> str:
        """Current provider key for chat services."""
        return self.settings.chat.provider

    async def select_chat_provider(self, key: str) -> None:
        """Select and persist a new chat service provider."""
        provider = CHAT_PROVIDER_OPTIONS[key]
        draft = self._use_cases.get_new_draft()
        draft.select_chat_provider(provider)
        await self._use_cases.update_settings(draft)
        self.notify_changed()

    @property
    def embedding_provider(self) -> str:
        """Current provider key for embedding services."""
        return self.settings.embedding.provider

    async def select_embedding_provider(self, key: str) -> None:
        """Select and stage changes for a new embedding provider."""
        provider = EMBEDDING_PROVIDER_OPTIONS[key]
        draft = self._use_cases.get_new_draft()
        draft.select_embedding_provider(provider)
        await self._stage_embedding_change(draft)

    # ── Choices ───────────────────────────────────────────────────────────
    @property
    def preset(self) -> PresetMode:
        """Current configuration preset mode."""
        return self.settings.preset_mode

    async def select_preset(self, key: str) -> None:
        """Switch and persist a configuration preset mode."""
        mode = PresetMode(key)
        draft = self._use_cases.get_new_draft()
        draft.select_preset(mode)
        await self._use_cases.update_settings(draft)
        self.notify_changed()

    # ── Tuning ────────────────────────────────────────────────────────────
    @property
    def tuning(self) -> list[TuningSlider]:
        """Generate a list of current tuning sliders for the UI."""
        settings = self.settings
        return [
            TuningSlider(
                s.key,
                s.label,
                s.minimum,
                s.maximum,
                s.step,
                float(getattr(settings, s.key)),
            )
            for s in _SPECS
        ]

    async def set_tuning(self, key: str, value: float) -> None:
        """Update a specific tuning parameter, switch to custom mode, and save.

        Raises:
            KeyError: For an unknown slider key.
        """
        draft = self._use_cases.get_new_draft()
        setattr(draft, key, _SPECS_BY_KEY[key].cast(value))
        draft.select_preset(PresetMode.CUSTOM)
        await self._use_cases.update_settings(draft)
        self.notify_changed()

    @property
    def estimate_text(self) -> str:
        """Human-readable estimation string of token consumption per question."""
        tokens = self.settings.est_tokens()
        return f"Estimated up to ~{tokens:,} tokens per question (free on local models)"

    # ── Connection Test ───────────────────────────────────────────────────
    @property
    def test_result_chat(self) -> ConnectionTestResult | None:
        """Latest connection test results, if available."""
        return self._test_result_chat

    @property
    def test_result_embedding(self) -> ConnectionTestResult | None:
        """Latest connection test results, if available."""
        return self._test_result_embedding

    @property
    def is_testing_chat(self) -> bool:
        """Flag indicating whether a connection test is currently running."""
        return self._is_testing_chat

    @property
    def is_testing_embedding(self) -> bool:
        """Flag indicating whether a connection test is currently running."""
        return self._is_testing_embedding

    async def test_connection(self, endpoint: Literal["chat", "embedding"]) -> None:
        """Probe endpoints and publish testing status followed by the outcome."""
        match endpoint:
            case "chat":
                self._is_testing_chat = True
                self.notify_changed()

                self._test_result_chat = await self._use_cases.test_model_connection(
                    self.settings.chat
                )

                self._is_testing_chat = False
                self.notify_changed()
            case "embedding":
                self._is_testing_embedding = True
                self.notify_changed()

                self._test_result_embedding = (
                    await self._use_cases.test_model_connection(self.settings.embedding)
                )

                self._is_testing_embedding = False
                self.notify_changed()

    # ── Embedding Change ──────────────────────────────────────────────────
    @property
    def pending_embedding_change(self) -> PendingEmbeddingChange | None:
        """Pending embedding model changes awaiting confirmation."""
        return self._pending_embedding

    async def confirm_embedding_change(self) -> None:
        """Commit pending embedding model updates and stale reindexing books."""
        pending, self._pending_embedding = self._pending_embedding, None
        if pending is not None:
            await self._use_cases.update_settings(pending.draft)
        self.notify_changed()

    def cancel_embedding_change(self) -> None:
        """Discard pending changes, reverting UI values back to current settings."""
        self._pending_embedding = None
        self.notify_changed()

    async def _stage_embedding_change(self, draft: Settings) -> None:
        """Check compatibility and stage pending changes if books need reindexing."""
        stale = await self._use_cases.check_embedding_compatibility(
            draft.embedding.provider, draft.embedding.model
        )

        if not stale:
            await self._use_cases.update_settings(draft)
        else:
            self._pending_embedding = PendingEmbeddingChange(
                draft=draft,
                stale_books=list(stale),
                confirm_embedding_change=self.confirm_embedding_change,
                cancel_embedding_change=self.cancel_embedding_change,
            )
            self._events.embedding_reindex_requested.emit(self._pending_embedding)

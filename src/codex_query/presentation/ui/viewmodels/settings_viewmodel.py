"""Presentation view model for application settings and configuration management."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from codex_query.application.facade import SettingsFacade
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    StaleBook,
)
from codex_query.domain.models.connection import ConnectionTestResult, Endpoint
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    LLMProvider,
)
from codex_query.domain.models.settings import PresetMode, Settings
from codex_query.presentation.ui.viewmodels.events import (
    EmbeddingChangeRequest,
    UiEvents,
)
from codex_query.presentation.ui.viewmodels.observable import ObservableObject

CHAT_PROVIDER_OPTIONS: dict[str, LLMProvider] = {
    config.name: provider for provider, config in CHAT_PROVIDER_CONFIGS.items()
}
EMBEDDING_PROVIDER_OPTIONS: dict[str, LLMProvider] = {
    config.name: provider for provider, config in EMBEDDING_PROVIDER_CONFIGS.items()
}

# (key, label) pairs for the preset selector, in display order.
PRESET_OPTIONS: list[tuple[str, str]] = [
    (preset.value, preset.value.replace("_", " ").title()) for preset in PresetMode
]

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
        int,
    ),
    _TuningSpec(
        "top_k",
        "Passages retrieved (top-k)",
        1,
        12,
        1,
        int,
    ),
    _TuningSpec(
        "num_ctx",
        "Context window",
        1024,
        16384,
        1024,
        int,
    ),
    _TuningSpec(
        "chunk_size",
        "Chunk size (new books only)",
        200,
        2000,
        100,
        int,
    ),
]
_SPECS_BY_KEY = {s.key: s for s in _SPECS}


class SettingsViewModel(ObservableObject):
    """View model managing user preferences, parameters, and service connections."""

    def __init__(
        self,
        use_cases: SettingsFacade,
        events: UiEvents,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        super().__init__()
        self._use_cases = use_cases
        self._events = events
        self._logger = logger_factory.create(__name__)

        # Serializes read-modify-write cycles on the settings (see ``_update``).
        self._lock = asyncio.Lock()

        self._test_results: dict[Endpoint, ConnectionTestResult | None] = {
            "chat": None,
            "embedding": None,
        }
        self._testing: dict[Endpoint, bool] = {"chat": False, "embedding": False}

        # Draft awaiting the user's answer to the re-index confirmation dialog.
        self._pending_draft: Settings | None = None

    @property
    def settings(self) -> Settings:
        """Retrieve current application settings."""
        return self._use_cases.get_current()

    async def _update(
        self,
        mutate: Callable[[Settings], None],
        *,
        invalidate: Endpoint | None = None,
    ) -> None:
        """Apply ``mutate`` to a fresh draft, persist it, and notify the view.

        The draft is created *inside* the lock, so two edits that arrive close
        together (e.g. a slider release and a text field commit) cannot both start
        from the same snapshot and overwrite each other.

        Args:
            mutate: Edits the draft in place.
            invalidate: Endpoint whose last connection-test result is now stale.
        """
        async with self._lock:
            draft = self._use_cases.get_new_draft()
            mutate(draft)
            await self._use_cases.update_settings(draft)
        if invalidate is not None:
            self._test_results[invalidate] = None
        self.notify_changed()

    # ── Text Fields ───────────────────────────────────────────────────────
    @property
    def chat_base_url(self) -> str:
        """Base URL for the chat service provider."""
        return self.settings.chat.base_url

    async def set_chat_base_url(self, value: str) -> None:
        """Update and save the chat service base URL."""

        def apply(draft: Settings) -> None:
            draft.chat.base_url = value

        await self._update(apply, invalidate="chat")

    @property
    def embedding_base_url(self) -> str:
        """Base URL for the embedding service provider."""
        return self.settings.embedding.base_url

    async def set_embedding_base_url(self, value: str) -> None:
        """Update and save the embedding service base URL."""

        def apply(draft: Settings) -> None:
            draft.embedding.base_url = value

        await self._update(apply, invalidate="embedding")

    @property
    def chat_api_key(self) -> str:
        """API key for the chat service provider."""
        return self.settings.chat.api_key

    async def set_chat_api_key(self, value: str) -> None:
        """Update and save the chat API key."""

        def apply(draft: Settings) -> None:
            draft.chat.api_key = value

        await self._update(apply, invalidate="chat")

    @property
    def embedding_api_key(self) -> str:
        """API key for the embedding service provider."""
        return self.settings.embedding.api_key

    async def set_embedding_api_key(self, value: str) -> None:
        """Update and save the embedding API key."""

        def apply(draft: Settings) -> None:
            draft.embedding.api_key = value

        await self._update(apply, invalidate="embedding")

    @property
    def chat_model(self) -> str:
        """Active model name for the chat service."""
        return self.settings.chat.model

    async def set_chat_model(self, value: str) -> None:
        """Update and save the active chat model."""

        def apply(draft: Settings) -> None:
            draft.chat.model = value

        await self._update(apply, invalidate="chat")

    @property
    def embedding_model(self) -> str:
        """Active model name for the embedding service."""
        return self.settings.embedding.model

    async def set_embedding_model(self, value: str) -> None:
        """Update, or stage for confirmation, the active embedding model."""

        def apply(draft: Settings) -> None:
            draft.embedding.model = value.strip()

        await self._update_embedding(apply)

    # ── Select Fields ─────────────────────────────────────────────────────
    @property
    def chat_provider_options(self) -> list[str]:
        """Display names of the selectable chat providers."""
        return list(CHAT_PROVIDER_OPTIONS)

    @property
    def chat_provider(self) -> str:
        """Display name of the current chat provider (a key of the options)."""
        provider = self.settings.chat.provider
        config = CHAT_PROVIDER_CONFIGS.get(provider)
        return config.name if config else str(provider)

    async def select_chat_provider(self, key: str) -> None:
        """Select and persist a new chat service provider."""
        provider = CHAT_PROVIDER_OPTIONS[key]

        def apply(draft: Settings) -> None:
            draft.select_chat_provider(provider)

        await self._update(apply, invalidate="chat")

    @property
    def embedding_provider_options(self) -> list[str]:
        """Display names of the selectable embedding providers."""
        return list(EMBEDDING_PROVIDER_OPTIONS)

    @property
    def embedding_provider(self) -> str:
        """Display name of the current embedding provider (a key of the options)."""
        provider = self.settings.embedding.provider
        config = EMBEDDING_PROVIDER_CONFIGS.get(provider)
        return config.name if config else str(provider)

    async def select_embedding_provider(self, key: str) -> None:
        """Select, or stage for confirmation, a new embedding provider."""
        provider = EMBEDDING_PROVIDER_OPTIONS[key]

        def apply(draft: Settings) -> None:
            draft.select_embedding_provider(provider)

        await self._update_embedding(apply)

    # ── Choices ───────────────────────────────────────────────────────────
    @property
    def preset_options(self) -> list[tuple[str, str]]:
        """``(key, label)`` pairs for the preset selector."""
        return PRESET_OPTIONS

    @property
    def preset(self) -> PresetMode:
        """Current configuration preset mode."""
        return self.settings.preset_mode

    @property
    def preset_key(self) -> str:
        """Key of the current preset, matching :attr:`preset_options`."""
        return self.settings.preset_mode.value

    async def select_preset(self, key: str) -> None:
        """Switch and persist a configuration preset mode."""
        mode = PresetMode(key)

        def apply(draft: Settings) -> None:
            draft.select_preset(mode)

        await self._update(apply)

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
        spec = _SPECS_BY_KEY[key]

        def apply(draft: Settings) -> None:
            setattr(draft, spec.key, spec.cast(value))
            draft.select_preset(PresetMode.CUSTOM)

        await self._update(apply)

    @property
    def estimate_text(self) -> str:
        """Human-readable estimation string of token consumption per question."""
        tokens = self.settings.est_tokens()
        return f"Estimated up to ~{tokens:,} tokens per question (free on local models)"

    # ── Connection Test ───────────────────────────────────────────────────
    def test_result(self, endpoint: Endpoint) -> ConnectionTestResult | None:
        """Latest connection test result for ``endpoint``, if still valid.

        Editing the endpoint's provider, URL, model or key discards the result.
        """
        return self._test_results[endpoint]

    def is_testing(self, endpoint: Endpoint) -> bool:
        """Whether a connection test for ``endpoint`` is currently running."""
        return self._testing[endpoint]

    async def test_connection(self, endpoint: Endpoint) -> None:
        """Probe an endpoint and publish testing status followed by the outcome."""
        if self._testing[endpoint]:
            return
        self._testing[endpoint] = True
        self._test_results[endpoint] = None
        self.notify_changed()
        try:
            settings = self.settings
            config = settings.chat if endpoint == "chat" else settings.embedding
            self._test_results[endpoint] = await self._use_cases.test_model_connection(
                config, endpoint
            )
        except Exception:
            self._logger.exception(
                "Connection test for %s failed unexpectedly", endpoint
            )
            self._events.toast.emit("The connection test failed unexpectedly.")
        finally:
            self._testing[endpoint] = False
            self.notify_changed()

    # ── Embedding Change ──────────────────────────────────────────────────
    async def confirm_embedding_change(self) -> None:
        """Apply the staged embedding change."""
        draft, self._pending_draft = self._pending_draft, None
        if draft is not None:
            async with self._lock:
                await self._use_cases.update_settings(draft)
            self._test_results["embedding"] = None
        self.notify_changed()

    def cancel_embedding_change(self) -> None:
        """Discard the staged change, reverting UI values to current settings."""
        self._pending_draft = None
        self.notify_changed()

    async def _update_embedding(self, mutate: Callable[[Settings], None]) -> None:
        """Apply an embedding edit, or stage it if books would need re-indexing."""
        stale: list[StaleBook] = []
        async with self._lock:
            draft = self._use_cases.get_new_draft()
            mutate(draft)
            stale = list(
                await self._use_cases.check_embedding_compatibility(
                    draft.embedding.provider, draft.embedding.model
                )
            )
            if not stale:
                await self._use_cases.update_settings(draft)
            else:
                self._pending_draft = draft

        if not stale:
            self._test_results["embedding"] = None
            # Refresh the form: selecting a provider fills in new defaults.
            self.notify_changed()
            return

        # The form keeps showing the user's selection while the dialog is open;
        # ``cancel_embedding_change`` re-syncs it if they back out.
        self._events.embedding_reindex_requested.emit(
            EmbeddingChangeRequest(
                stale_books=stale,
                confirm=self.confirm_embedding_change,
                cancel=self.cancel_embedding_change,
            )
        )

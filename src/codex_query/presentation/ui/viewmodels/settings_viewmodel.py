"""Presentation view model for application settings and configuration management."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
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
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject
from codex_query.presentation.ui.viewmodels.events.ui_events import (
    EmbeddingChangeRequest,
    UiEvents,
)

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
    """Static description of one tuning slider and the setting it edits.

    Attributes:
        key: The tuning attribute name on the settings model.
        label: Human-readable display label.
        minimum: Minimum allowable slider value.
        maximum: Maximum allowable slider value.
        step: Incremental step size.
        cast: Converts the slider's float to the setting's real type.
    """

    key: TuningKeys
    label: str
    minimum: float
    maximum: float
    step: float
    cast: Callable[[float], float]


@dataclass(frozen=True, slots=True)
class TuningSlider:
    """Representation of a slider as the view should render it.

    Attributes:
        key: The tuning attribute name.
        label: Human-readable display label.
        minimum: Minimum slider value.
        maximum: Maximum slider value.
        step: Step increment.
        value: Current value of the slider.
    """

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
    """View model managing user preferences, parameters, and service connections.

    Attributes:
        _use_cases: The settings facade for retrieving and updating configurations.
        _events: UI event emitter for toasts and dialog triggers.
        _on_reindex: Callback invoked with stale book IDs after embedding changes.
        _logger: Contextual logger instance.
        _lock: Async lock for synchronizing read-modify-write cycles on settings.
        _test_results: Mapping of endpoints to their latest connection test results.
        _testing: Mapping of endpoints to their active testing status flags.
        _editing_key: Mapping of endpoints to whether the user is replacing the key.
        _pending_draft: Staged settings draft awaiting re-index confirmation.
        _pending_stale: List of stale books affected by the pending embedding change.
    """

    def __init__(
        self,
        use_cases: SettingsFacade,
        events: UiEvents,
        logger_factory: LoggerFactoryPort,
        on_reindex: Callable[[Sequence[int]], Awaitable[None]] | None = None,
    ) -> None:
        """Initializes the SettingsViewModel.

        Args:
            use_cases: The settings facade for retrieving and updating configurations.
            events: UI event emitter for toasts and dialog triggers.
            logger_factory: Factory used to create a contextual logger.
            on_reindex: Called with the IDs of stale books once the user confirms
                an embedding change.
        """
        super().__init__()
        self._use_cases = use_cases
        self._events = events
        self._on_reindex = on_reindex
        self._logger = logger_factory.create(__name__)

        # Serializes read-modify-write cycles on the settings (see ``_update``).
        self._lock = asyncio.Lock()

        self._test_results: dict[Endpoint, ConnectionTestResult | None] = {
            "chat": None,
            "embedding": None,
        }
        self._testing: dict[Endpoint, bool] = {"chat": False, "embedding": False}

        # Whether the user asked to replace an already configured key. Whether the
        # key field is shown is *derived* from this and the settings (see
        # ``is_api_key_field_visible``), so it can never go stale.
        self._editing_key: dict[Endpoint, bool] = {"chat": False, "embedding": False}

        # Draft awaiting the user's answer to the re-index confirmation dialog,
        # with the books that change would leave stale.
        self._pending_draft: Settings | None = None
        self._pending_stale: list[StaleBook] = []

        self._logger.info("Initialized SettingsViewModel")

    @property
    def settings(self) -> Settings:
        """Retrieve current application settings.

        Returns:
            The current active `Settings` instance.
        """
        return self._use_cases.get_current()

    async def _update(
        self,
        mutate: Callable[[Settings], None],
        *,
        invalidate: Endpoint | Literal["all"] | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        """Apply ``mutate`` to a fresh draft, persist it, and notify the view.

        The draft is created *inside* the lock, so two edits that arrive close
        together cannot both start from the same snapshot and overwrite each other.

        ``mutate`` must only edit the draft. Anything else (UI flags, ...) belongs
        in ``on_saved``, which runs only after the settings were persisted.

        Args:
            mutate: Callable that edits the settings draft in place.
            invalidate: Endpoint whose last connection-test result is now stale.
            on_saved: Called after a successful save, before the view is notified.
        """
        async with self._lock:
            draft = self._use_cases.get_new_draft()
            mutate(draft)
            await self._use_cases.update_settings(draft)
        if on_saved is not None:
            on_saved()
        if invalidate is not None:
            if invalidate == "all":
                self._logger.debug(
                    "Invalidating all connection test results",
                )
                for endpoint in self._test_results:
                    self._test_results[endpoint] = None
            else:
                self._logger.debug(
                    "Invalidating connection test result for endpoint: %s", invalidate
                )
                self._test_results[invalidate] = None
        self.notify_changed()

    # ── Text Fields ───────────────────────────────────────────────────────
    @property
    def chat_base_url(self) -> str:
        """Base URL for the chat service provider.

        Returns:
            The chat service base URL string.
        """
        return self.settings.chat.base_url

    async def set_chat_base_url(self, value: str) -> None:
        """Update and save the chat service base URL.

        Args:
            value: The new chat service base URL.
        """
        self._logger.info("Updating chat base URL")

        def apply(draft: Settings) -> None:
            draft.chat.base_url = value

        await self._update(apply, invalidate="chat")

    @property
    def embedding_base_url(self) -> str:
        """Base URL for the embedding service provider.

        Returns:
            The embedding service base URL string.
        """
        return self.settings.embedding.base_url

    async def set_embedding_base_url(self, value: str) -> None:
        """Update and save the embedding service base URL.

        Args:
            value: The new embedding service base URL.
        """
        self._logger.info("Updating embedding base URL")

        def apply(draft: Settings) -> None:
            draft.embedding.base_url = value

        await self._update(apply, invalidate="embedding")

    @property
    def chat_model(self) -> str:
        """Active model name for the chat service.

        Returns:
            The chat model name string.
        """
        return self.settings.chat.model

    async def set_chat_model(self, value: str) -> None:
        """Update and save the active chat model.

        Args:
            value: The new chat model name.
        """
        self._logger.info("Updating active chat model to '%s'", value)

        def apply(draft: Settings) -> None:
            draft.chat.model = value

        await self._update(apply, invalidate="chat")

    @property
    def embedding_model(self) -> str:
        """Active model name for the embedding service.

        Returns:
            The embedding model name string.
        """
        return self.settings.embedding.model

    async def set_embedding_model(self, value: str) -> None:
        """Update, or stage for confirmation, the active embedding model.

        Args:
            value: The new embedding model name.
        """
        self._logger.info("Setting active embedding model to '%s'", value.strip())

        def apply(draft: Settings) -> None:
            draft.embedding.model = value.strip()

        await self._update_embedding(apply)

    # ── API Keys ──────────────────────────────────────────────────────────
    # The stored key itself is deliberately not exposed to the view: the view only
    # needs to know whether a key exists and a short fingerprint to display.
    def has_api_key(self, endpoint: Endpoint) -> bool:
        """Whether an API key is configured for ``endpoint``.

        Args:
            endpoint: The service endpoint to query.

        Returns:
            True if a key is stored for the endpoint, False otherwise.
        """
        settings = self.settings
        config = settings.chat if endpoint == "chat" else settings.embedding
        return config.has_api_key

    @property
    def has_chat_api(self) -> bool:
        """Whether the chat API key is configured.

        Returns:
            True if the chat API key is present, False otherwise.
        """
        return self.has_api_key("chat")

    @property
    def has_embedding_api(self) -> bool:
        """Whether the embedding API key is configured.

        Returns:
            True if the embedding API key is present, False otherwise.
        """
        return self.has_api_key("embedding")

    def api_key_hash(self, endpoint: Endpoint) -> str:
        """Short fingerprint of the stored key, safe to display.

        Args:
            endpoint: The service endpoint to query.

        Returns:
            The key fingerprint, or an empty string if no key is stored.
        """
        settings = self.settings
        config = settings.chat if endpoint == "chat" else settings.embedding
        return config.api_key_hash

    def is_api_key_field_visible(self, endpoint: Endpoint) -> bool:
        """Whether the key input should be shown instead of the "Configured" row.

        Derived state: the input is shown when no key exists yet, or while the
        user is replacing the existing one.

        Args:
            endpoint: The service endpoint to query.

        Returns:
            True if the key input field should be visible.
        """
        return self._editing_key[endpoint] or not self.has_api_key(endpoint)

    def begin_edit_api_key(self, endpoint: Endpoint) -> None:
        """Start replacing the configured key (shows the input field).

        Args:
            endpoint: The service endpoint whose key is being replaced.
        """
        self._logger.debug("Beginning API key edit for endpoint: %s", endpoint)
        self._editing_key[endpoint] = True
        self.notify_changed()

    def cancel_edit_api_key(self, endpoint: Endpoint) -> None:
        """Abandon replacing the key and go back to the "Configured" row.

        Args:
            endpoint: The service endpoint whose edit is cancelled.
        """
        self._logger.debug("Cancelling API key edit for endpoint: %s", endpoint)
        self._editing_key[endpoint] = False
        self.notify_changed()

    async def set_api_key(self, endpoint: Endpoint, value: str) -> None:
        """Update and save the API key of ``endpoint``.

        An empty value is ignored: clearing the field must not silently delete a
        stored key. If the other endpoint uses the same provider and has no key
        yet, it receives the same key.

        Args:
            endpoint: The service endpoint the key belongs to.
            value: The new API key string.
        """
        value = value.strip()
        if not value:
            self._logger.debug("Ignoring empty API key for endpoint: %s", endpoint)
            return
        self._logger.info("Updating %s API key", endpoint)

        def apply(draft: Settings) -> None:
            this = draft.chat if endpoint == "chat" else draft.embedding
            other = draft.embedding if endpoint == "chat" else draft.chat
            this.api_key = value
            if other.provider == this.provider and not other.has_api_key:
                other.api_key = value

        def saved() -> None:
            for key in self._editing_key:
                self._editing_key[key] = False

        await self._update(apply, invalidate="all", on_saved=saved)

    async def set_chat_api_key(self, value: str) -> None:
        """Update and save the chat API key.

        Args:
            value: The new chat API key string.
        """
        await self.set_api_key("chat", value)

    async def set_embedding_api_key(self, value: str) -> None:
        """Update and save the embedding API key.

        Args:
            value: The new embedding API key string.
        """
        await self.set_api_key("embedding", value)

    # ── Select Fields ─────────────────────────────────────────────────────
    @property
    def chat_provider_options(self) -> list[str]:
        """Display names of the selectable chat providers.

        Returns:
            A list of chat provider option names.
        """
        return list(CHAT_PROVIDER_OPTIONS)

    @property
    def chat_provider(self) -> str:
        """Display name of the current chat provider.

        Returns:
            The display name string of the active chat provider.
        """
        provider = self.settings.chat.provider
        config = CHAT_PROVIDER_CONFIGS.get(provider)
        return config.name if config else str(provider)

    async def select_chat_provider(self, key: str) -> None:
        """Select and persist a new chat service provider.

        Args:
            key: The option key corresponding to the selected provider.
        """
        self._logger.info("Selecting chat provider option: '%s'", key)
        provider = CHAT_PROVIDER_OPTIONS[key]

        def apply(draft: Settings) -> None:
            draft.select_chat_provider(provider)

        await self._update(apply, invalidate="chat")

    @property
    def embedding_provider_options(self) -> list[str]:
        """Display names of the selectable embedding providers.

        Returns:
            A list of embedding provider option names.
        """
        return list(EMBEDDING_PROVIDER_OPTIONS)

    @property
    def embedding_provider(self) -> str:
        """Display name of the current embedding provider.

        Returns:
            The display name string of the active embedding provider.
        """
        provider = self.settings.embedding.provider
        config = EMBEDDING_PROVIDER_CONFIGS.get(provider)
        return config.name if config else str(provider)

    async def select_embedding_provider(self, key: str) -> None:
        """Select, or stage for confirmation, a new embedding provider.

        Args:
            key: The option key corresponding to the selected embedding provider.
        """
        self._logger.info("Selecting embedding provider option: '%s'", key)
        provider = EMBEDDING_PROVIDER_OPTIONS[key]

        def apply(draft: Settings) -> None:
            draft.select_embedding_provider(provider)

        await self._update_embedding(apply)

    # ── Choices ───────────────────────────────────────────────────────────
    @property
    def preset_options(self) -> list[tuple[str, str]]:
        """``(key, label)`` pairs for the preset selector.

        Returns:
            A list of tuples containing preset keys and human-readable labels.
        """
        return PRESET_OPTIONS

    @property
    def preset(self) -> PresetMode:
        """Current configuration preset mode.

        Returns:
            The active `PresetMode` enumeration value.
        """
        return self.settings.preset_mode

    @property
    def preset_key(self) -> str:
        """Key of the current preset, matching :attr:`preset_options`.

        Returns:
            The string key of the current preset mode.
        """
        return self.settings.preset_mode.value

    async def select_preset(self, key: str) -> None:
        """Switch and persist a configuration preset mode.

        Args:
            key: The preset mode key to switch to.
        """
        self._logger.info("Switching configuration preset mode to '%s'", key)
        mode = PresetMode(key)

        def apply(draft: Settings) -> None:
            draft.select_preset(mode)

        await self._update(apply)

    # ── Tuning ────────────────────────────────────────────────────────────
    @property
    def tuning(self) -> list[TuningSlider]:
        """Generate a list of current tuning sliders for the UI.

        Returns:
            A list of `TuningSlider` configurations reflecting active settings.
        """
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

        Args:
            key: The tuning parameter identifier.
            value: The new numerical value for the parameter.

        Raises:
            KeyError: For an unknown slider key.
        """
        self._logger.info("Setting tuning parameter '%s' to %s", key, value)
        spec = _SPECS_BY_KEY[key]

        def apply(draft: Settings) -> None:
            setattr(draft, spec.key, spec.cast(value))
            draft.select_preset(PresetMode.CUSTOM)

        await self._update(apply)

    @property
    def estimate_text(self) -> str:
        """Human-readable estimation string of token consumption per question.

        Returns:
            A formatted token estimation string.
        """
        tokens = self.settings.est_tokens()
        return f"Estimated up to ~{tokens:,} tokens per question (free on local models)"

    # ── Connection Test ───────────────────────────────────────────────────
    def test_result(self, endpoint: Endpoint) -> ConnectionTestResult | None:
        """Latest connection test result for ``endpoint``, if still valid.

        Editing the endpoint's provider, URL, model or key discards the result.

        Args:
            endpoint: The service endpoint to query.

        Returns:
            The latest `ConnectionTestResult`, or None if invalid or untested.
        """
        return self._test_results[endpoint]

    def is_testing(self, endpoint: Endpoint) -> bool:
        """Whether a connection test for ``endpoint`` is currently running.

        Args:
            endpoint: The service endpoint to check.

        Returns:
            True if a test is in progress, False otherwise.
        """
        return self._testing[endpoint]

    async def test_connection(self, endpoint: Endpoint) -> None:
        """Probe an endpoint and publish testing status followed by the outcome.

        Args:
            endpoint: The service endpoint to test.
        """
        if self._testing[endpoint]:
            self._logger.debug(
                "Connection test for %s already in progress; skipping", endpoint
            )
            return

        self._logger.info("Starting connection test for endpoint: %s", endpoint)
        self._testing[endpoint] = True
        self._test_results[endpoint] = None
        self.notify_changed()
        try:
            settings = self.settings
            config = settings.chat if endpoint == "chat" else settings.embedding
            self._test_results[endpoint] = await self._use_cases.test_model_connection(
                config, endpoint
            )
            self._logger.info("Connection test for %s completed successfully", endpoint)
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
        """Apply the staged embedding change and re-index the books it affects."""
        self._logger.info("Confirming pending embedding change...")
        draft, self._pending_draft = self._pending_draft, None
        stale, self._pending_stale = self._pending_stale, []
        if draft is not None:
            # Save first: the re-index jobs read the new settings when they run.
            async with self._lock:
                await self._use_cases.update_settings(draft)
            self._test_results["embedding"] = None
        self.notify_changed()

        book_ids = [book.id for book in stale if book.id is not None]
        if draft is not None and book_ids and self._on_reindex is not None:
            try:
                await self._on_reindex(book_ids)
            except Exception:
                self._logger.exception("Could not start re-indexing")
                self._events.toast.emit(
                    "Settings saved, but re-indexing could not be started."
                )

    def cancel_embedding_change(self) -> None:
        """Discard the staged change, reverting UI values to current settings."""
        self._logger.info("Canceling pending embedding change")
        self._pending_draft = None
        self._pending_stale = []
        self.notify_changed()

    async def _update_embedding(self, mutate: Callable[[Settings], None]) -> None:
        """Apply an embedding edit, or stage it if books would need re-indexing.

        Args:
            mutate: Callable that edits the embedding settings draft in place.
        """
        self._logger.debug("Evaluating embedding compatibility for change...")
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
                self._logger.warning(
                    "Embedding change leaves %d stale book(s) requiring re-indexing",
                    len(stale),
                )
                self._pending_draft = draft
                self._pending_stale = stale

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

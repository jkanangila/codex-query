"""Persist non-secret application settings as JSON.

API keys are NOT stored here (see `ApiKeyRepositoryPort`). Files without a schema
version are ignored and defaults are used.
"""

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final, cast, override

from codex_query.application.ports.indexing import SettingsRepositoryPort
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    EndpointConfig,
    LLMProvider,
)
from codex_query.domain.models.settings import PresetMode, ServiceSettings, Settings
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.paths import AppPaths

logger = create_logger(__name__)

SCHEMA_VERSION: Final = 2

type Json = Mapping[str, object]


def settings_path() -> Path:
    """Resolve the path of `settings.json` (same location as before).

    Returns:
        Path: The absolute filesystem path to the `settings.json` file.
    """
    path = AppPaths.app_storage_data_dir() / ".settings" / "settings.json"
    logger.debug("Resolved settings path to: %s", path)
    return path


def _as_mapping(value: object) -> Json:
    """Safely convert an unknown object into a mapping dictionary.

    Args:
        value: Raw data object to inspect.

    Returns:
        Json: A dictionary mapping if valid, or an empty dictionary fallback.
    """
    if isinstance(value, dict):
        return cast("Json", value)
    logger.debug(
        "Expected dict mapping but received %s; falling back to empty dict",
        type(value).__name__,
    )
    return {}


def _str(data: Json, key: str, default: str) -> str:
    """Extract a string value from a JSON dictionary with fallback.

    Args:
        data: Source mapping dictionary.
        key: Dictionary key to lookup.
        default: Fallback string value if key is missing or invalid.

    Returns:
        str: Extracted string value or fallback default.
    """
    value = data.get(key)
    if isinstance(value, str):
        return value
    if key in data:
        logger.debug(
            "Invalid type for key '%s': expected str, got %s. Using default: %r",
            key,
            type(value).__name__,
            default,
        )
    return default


def _int(data: Json, key: str, default: int) -> int:
    """Extract an integer value from a JSON dictionary with fallback.

    Ensures booleans are explicitly rejected since bool inherits from int in Python.

    Args:
        data: Source mapping dictionary.
        key: Dictionary key to lookup.
        default: Fallback integer value if key is missing or invalid.

    Returns:
        int: Extracted integer value or fallback default.
    """
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if key in data:
        logger.debug(
            "Invalid type for key '%s': expected int, got %s. Using default: %r",
            key,
            type(value).__name__,
            default,
        )
    return default


def _float(data: Json, key: str, default: float) -> float:
    """Extract a float value from a JSON dictionary with fallback.

    Args:
        data: Source mapping dictionary.
        key: Dictionary key to lookup.
        default: Fallback float value if key is missing or invalid.

    Returns:
        float: Extracted float value or fallback default.
    """
    value = data.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if key in data:
        logger.debug(
            "Invalid type for key '%s': expected float, got %s. Using default: %r",
            key,
            type(value).__name__,
            default,
        )
    return default


def _provider(
    data: Json,
    key: str,
    configs: Mapping[LLMProvider, EndpointConfig],
    default: LLMProvider,
) -> LLMProvider:
    """Extract and validate an LLMProvider enum from JSON data.

    Args:
        data: Source mapping dictionary.
        key: Dictionary key holding the provider string.
        configs: Mapping of valid endpoint configurations to check support.
        default: Fallback LLMProvider enum value.

    Returns:
        LLMProvider: Validated provider enum or default fallback.
    """
    raw = data.get(key)
    if isinstance(raw, str):
        try:
            candidate = LLMProvider(raw)
        except ValueError:
            logger.warning(
                "Unknown provider '%s' specified for key '%s'; using default '%s'",
                raw,
                key,
                default.value,
            )
            return default

        if candidate in configs:
            return candidate

        logger.warning(
            "Provider '%s' is not supported in given configs; using default '%s'",
            candidate.value,
            default.value,
        )
    elif key in data:
        logger.debug(
            "Invalid provider key '%s' type: %s; using default '%s'",
            key,
            type(raw).__name__,
            default.value,
        )
    return default


def _preset(data: Json, default: PresetMode) -> PresetMode:
    """Extract and validate PresetMode enum from JSON data.

    Args:
        data: Source mapping dictionary.
        default: Fallback PresetMode enum value.

    Returns:
        PresetMode: Validated preset mode enum or default fallback.
    """
    raw = data.get("preset_mode")
    if isinstance(raw, str):
        try:
            return PresetMode(raw)
        except ValueError:
            logger.warning(
                "Unknown preset_mode '%s'; using default '%s'",
                raw,
                default.value,
            )
            return default
    elif "preset_mode" in data:
        logger.debug(
            "Invalid preset_mode type: %s; using default '%s'",
            type(raw).__name__,
            default.value,
        )
    return default


def _service_from_dict(
    raw: object,
    configs: Mapping[LLMProvider, EndpointConfig],
    fallback: ServiceSettings,
) -> ServiceSettings:
    """Parse raw dictionary data into a ServiceSettings instance.

    Args:
        raw: Raw unparsed service dictionary object.
        configs: Mapping of endpoint configurations to fall back to for base URL/model.
        fallback: Fallback ServiceSettings instance used for default values.

    Returns:
        ServiceSettings: Parsed service settings configuration.
    """
    data = _as_mapping(raw)
    provider = _provider(data, "provider", configs, fallback.provider)
    defaults = configs[provider]

    base_url = _str(data, "base_url", "") or defaults.base_url
    model = _str(data, "model", "") or defaults.default_model

    logger.debug(
        "Parsed service settings for provider '%s' (model: %s)",
        provider.value,
        model,
    )
    return ServiceSettings(
        provider=provider,
        base_url=base_url,
        model=model,
    )


def _service_to_dict(service: ServiceSettings) -> dict[str, object]:
    """Serialize ServiceSettings instance into a standard dictionary.

    API keys are deliberately excluded from serialized output.

    Args:
        service: ServiceSettings instance to serialize.

    Returns:
        dict[str, object]: Serialized JSON-compatible dictionary.
    """
    logger.debug(
        "Serializing service settings for provider '%s'", service.provider.value
    )
    return {
        "provider": service.provider.value,
        "base_url": service.base_url,
        "model": service.model,
    }


def _to_dict(settings: Settings) -> dict[str, object]:
    """Serialize full Settings domain model into a JSON-compatible dictionary.

    Args:
        settings: Settings instance to serialize.

    Returns:
        dict[str, object]: Dictionary representation matching standard schema.
    """
    logger.debug("Serializing Settings object to dictionary (v%d)", SCHEMA_VERSION)
    return {
        "version": SCHEMA_VERSION,
        "chat": _service_to_dict(settings.chat),
        "embedding": _service_to_dict(settings.embedding),
        "preset_mode": settings.preset_mode.value,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "top_k": settings.top_k,
        "num_ctx": settings.num_ctx,
        "chunk_size": settings.chunk_size,
    }


def _from_current(data: Json) -> Settings:
    """Parse schema v2 JSON mapping into a Settings object.

    Args:
        data: Source mapping dictionary following schema v2.

    Returns:
        Settings: Instantiated Settings object.
    """
    logger.debug("Parsing current schema v2 settings payload")
    d = Settings()
    return Settings(
        chat=_service_from_dict(data.get("chat"), CHAT_PROVIDER_CONFIGS, d.chat),
        embedding=_service_from_dict(
            data.get("embedding"), EMBEDDING_PROVIDER_CONFIGS, d.embedding
        ),
        preset_mode=_preset(data, d.preset_mode),
        temperature=_float(data, "temperature", d.temperature),
        max_tokens=_int(data, "max_tokens", d.max_tokens),
        top_k=_int(data, "top_k", d.top_k),
        num_ctx=_int(data, "num_ctx", d.num_ctx),
        chunk_size=_int(data, "chunk_size", d.chunk_size),
    )


class JsonSettingsRepository(SettingsRepositoryPort):
    """Implements `SettingsRepositoryPort` with atomic JSON file persistence."""

    def __init__(self, file_path: Path | None = None) -> None:
        """Initialize repository with target file path.

        Args:
            file_path: Target JSON file path. Defaults to `settings_path()`.
        """
        self._file_path = file_path or settings_path()

    @override
    def load(self) -> Settings | None:
        """Load settings from the JSON file.

        Handles missing files, unparsable JSON content, and unversioned files.

        Returns:
            Settings | None: Parsed Settings object, or None if reading fails or
                file does not exist.
        """
        if not self._file_path.exists():
            logger.info("No settings file at %s; using defaults", self._file_path)
            return None

        logger.debug("Loading settings from %s", self._file_path)
        try:
            raw: object = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("Could not read settings from %s", self._file_path)
            return None

        data = _as_mapping(raw)
        if "version" not in data:
            logger.info("Ignoring unversioned settings file at %s", self._file_path)
            return None

        logger.debug("Successfully loaded schema v%s settings", data.get("version"))
        return _from_current(data)

    @override
    def save(self, settings: Settings) -> None:
        """Persist settings to disk atomically using a temporary file.

        Args:
            settings: Settings object instance to persist.

        Raises:
            Exception: Re-raises any underlying I/O or serialization error.
        """
        logger.debug("Preparing to write settings to %s", self._file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self._file_path.parent,
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(_to_dict(settings), handle, indent=2)

            temp_path.replace(self._file_path)  # atomic on the same filesystem
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            logger.exception("Failed to save settings to %s", self._file_path)
            raise

        logger.info("Saved settings to %s", self._file_path)

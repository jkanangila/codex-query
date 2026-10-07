"""Module for managing application settings stored in JSON format with
Fernet encryption."""

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_config_dir

from codex_query.domain.models.provider import LLMProvider
from codex_query.domain.models.settings import PresetMode, Settings
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.security.keys import get_or_create_secret_key

logger = create_logger(__name__)


def settings_path() -> Path:
    """Resolve the filesystem path for storing application settings JSON.

    Determines the path using environment variables `APP_NAME` and
    `FLET_APP_STORAGE_DATA`, falling back to platform-specific user config directories.

    Returns:
        Path: The fully resolved destination path for `settings.json`.
    """
    app_name = os.getenv("APP_NAME", "codex_query")
    base = os.getenv("FLET_APP_STORAGE_DATA", user_config_dir(app_name))
    resolved_path = Path(base) / ".settings" / "settings.json"
    logger.debug("Resolved settings file path: %s", resolved_path)
    return resolved_path


class JsonSettingsRepository:
    """Repository for persisting and loading application settings to/from JSON.

    Handles transparent field-level encryption for sensitive properties (e.g., API keys)
    and atomic file writes to prevent configuration corruption.
    """

    def __init__(
        self,
        file_path: Path | None = None,
        secret_key: bytes | str | None = None,
    ) -> None:
        """Initialize the JsonSettingsRepository instance.

        Args:
            file_path: Optional custom path to the settings file.
                Defaults to `settings_path()`.
            secret_key: Optional secret key for Fernet encryption. If omitted, fetches
                or generates a default key via `get_or_create_secret_key()`.
        """
        self.file_path = file_path or settings_path()
        logger.debug(
            "Initializing JsonSettingsRepository with file path: %s", self.file_path
        )

        resolved_key = secret_key or get_or_create_secret_key()
        self._fernet: Fernet | None = self._init_fernet(resolved_key)

    def _init_fernet(self, secret_key: bytes | str | None) -> Fernet | None:
        """Initialize the Fernet encryption cipher using a provided key.

        Args:
            secret_key: The secret key as a string or byte sequence.

        Returns:
            Fernet | None: Configured Fernet cipher instance, or None if key is missing.
        """
        if not secret_key:
            logger.warning(
                "No secret key provided; secret encryption/decryption disabled."
            )
            return None

        key_bytes = (
            secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        )

        if len(key_bytes) == 44 and key_bytes.endswith(b"="):
            try:
                if len(base64.urlsafe_b64decode(key_bytes)) == 32:
                    logger.debug("Successfully validated 32-byte URL-safe base64 key.")
                    return Fernet(key_bytes)
            except Exception:
                logger.exception(
                    "Failed base64 validation for existing key; "
                    "falling back to SHA-256 derivation."
                )

        logger.debug("Deriving Fernet encryption key via SHA-256 digest.")
        derived_key = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
        return Fernet(derived_key)

    def encrypt_secret(self, secret: str) -> str:
        """Encrypt a plain text secret string using Fernet cipher.

        Args:
            secret: Plain text value to encrypt.

        Returns:
            str: Ciphertext string if encryption succeeds;
                otherwise, the original string.
        """
        if not self._fernet:
            logger.debug("Encryption skipped: Fernet cipher is not initialized.")
            return secret
        if not secret:
            logger.debug("Encryption skipped: Plaintext secret is empty.")
            return secret

        try:
            encrypted = self._fernet.encrypt(secret.encode("utf-8")).decode("utf-8")
            logger.debug("Successfully encrypted secret field.")
            return encrypted
        except Exception:
            logger.exception("Unexpected error encountered during secret encryption.")
            raise

    def decrypt_secret(self, cipher_text: str) -> str:
        """Decrypt a Fernet ciphertext secret string.

        Args:
            cipher_text: Encrypted string to decrypt.

        Returns:
            str: Decrypted plaintext string, or raw `cipher_text`
                on failure/unencrypted input.
        """
        if not self._fernet:
            logger.debug("Decryption skipped: Fernet cipher is not initialized.")
            return cipher_text
        if not cipher_text:
            logger.debug("Decryption skipped: Ciphertext value is empty.")
            return cipher_text

        try:
            decrypted = self._fernet.decrypt(cipher_text.encode("utf-8")).decode(
                "utf-8"
            )
            logger.debug("Successfully decrypted secret field.")
            return decrypted
        except (InvalidToken, TypeError, ValueError):
            logger.exception(
                "Failed to decrypt secret field. Returning unencrypted raw value."
            )
            return cipher_text

    def load(self) -> Settings | None:
        """Load settings configuration from the JSON file on disk.

        Returns:
            Settings | None: Populated `Settings` instance if file exists and parses
            successfully; `None` on file missing or parse errors.
        """
        logger.info("Attempting to load settings from %s", self.file_path)

        if not self.file_path.exists():
            logger.info(
                "Settings file does not exist at %s. Returning default state.",
                self.file_path,
            )
            return None

        try:
            with open(self.file_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            if isinstance(data.get("api_key"), str):
                data["api_key"] = self.decrypt_secret(data["api_key"])

            # Map primitive string values back into Domain Enums
            if "preset_mode" in data and data["preset_mode"] is not None:
                data["preset_mode"] = PresetMode(data["preset_mode"])

            if "provider" in data and data["provider"] is not None:
                data["provider"] = LLMProvider(data["provider"])

            settings = Settings(**data)
            logger.info("Successfully loaded settings from %s", self.file_path)
            return settings
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            logger.exception(
                "Failed to load or parse settings from %s. Falling back to defaults.",
                self.file_path,
            )
            return None

    def save(self, settings: Settings) -> None:
        """Persist settings to disk atomically using a temporary file.

        Args:
            settings: The `Settings` object instance to persist.

        Raises:
            Exception: Re-raises filesystem or serialization exceptions after logging.
        """
        logger.info("Saving settings to %s", self.file_path)

        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(settings)

            if isinstance(data.get("api_key"), str):
                data["api_key"] = self.encrypt_secret(data["api_key"])

            # Convert Enum attributes to string values for JSON serialization safety
            data["preset_mode"] = settings.preset_mode.value
            data["provider"] = settings.provider.value

            temp_dir = self.file_path.parent
            temp_file_path: Path | None = None

            try:
                with tempfile.NamedTemporaryFile(
                    "w", dir=temp_dir, delete=False, encoding="utf-8"
                ) as temp_file:
                    json.dump(data, temp_file, indent=2, default=str)
                    temp_file_path = Path(temp_file.name)

                temp_file_path.replace(self.file_path)
                logger.info("Successfully persisted settings to %s", self.file_path)
            finally:
                if (
                    temp_file_path
                    and temp_file_path.exists()
                    and temp_file_path != self.file_path
                ):
                    try:
                        temp_file_path.unlink()
                        logger.debug("Cleaned up temporary file %s", temp_file_path)
                    except OSError:
                        logger.exception(
                            "Failed to clean up temporary file %s", temp_file_path
                        )

        except Exception:
            logger.exception("Failed to save settings to %s", self.file_path)
            raise

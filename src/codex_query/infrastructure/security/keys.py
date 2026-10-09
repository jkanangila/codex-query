"""Master encryption key: system keyring first, protected file as fallback."""

import contextlib
import os
from pathlib import Path

import keyring
from cryptography.fernet import Fernet

from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.paths import AppPaths

SERVICE_NAME = "codex_query"
KEY_ACCOUNT = "settings_encryption_key"

logger = create_logger(__name__)


def key_file_path() -> Path:
    return AppPaths.app_storage_data_dir() / ".secrets" / "master.key"


def _generate() -> str:
    return Fernet.generate_key().decode("utf-8")


def _get_or_create_file_key(new_key: str | None = None) -> str:
    """Headless/container fallback. Only as safe as the file's permissions."""
    path = key_file_path()
    with contextlib.suppress(FileNotFoundError):
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    key = new_key or _generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(key)
    logger.warning("Master key stored in %s because no keyring is usable.", path)
    return key


def get_or_create_secret_key() -> str:
    """Return the Fernet master key, creating and persisting it if needed.

    Never generates a replacement key when the keyring merely *failed to read*:
    that would orphan every secret already encrypted with the old key.

    Returns:
        A URL-safe base64 Fernet key.
    """
    try:
        existing = keyring.get_password(SERVICE_NAME, KEY_ACCOUNT)
    except Exception as err:
        logger.warning("Keyring unavailable (%s); using key file.", type(err).__name__)
        return _get_or_create_file_key()

    if existing:
        return existing

    new_key = _generate()
    try:
        keyring.set_password(SERVICE_NAME, KEY_ACCOUNT, new_key)
    except Exception as err:
        logger.warning("Cannot write keyring (%s); using key file.", type(err).__name__)
        return _get_or_create_file_key(new_key)

    logger.info("Created a new master key in the system keyring.")
    return new_key

"""Module for managing settings encryption keys via system keyring."""

import keyring
from cryptography.fernet import Fernet

from codex_query.infrastructure.logging.factory import create_logger

SERVICE_NAME = "codex_query"
KEY_ACCOUNT = "settings_encryption_key"

logger = create_logger(__name__)


def get_or_create_secret_key() -> str:
    """Retrieve the secret key from system keyring or generate and store a new one.

    Attempts to fetch an existing encryption key from the system keyring service.
    If no key exists or if accessing the keyring fails (e.g., in headless or
    container environments), a new Fernet-compatible key is generated.

    Returns:
        str: A 32-byte URL-safe base64-encoded key string suitable for Fernet.
    """
    try:
        existing_key = keyring.get_password(SERVICE_NAME, KEY_ACCOUNT)
        if existing_key:
            logger.debug("Successfully retrieved encryption key from system keyring.")
            return existing_key
        logger.info("No existing encryption key found in system keyring.")
    except Exception:
        logger.exception(
            "Failed to access system keyring during key retrieval; "
            "falling back to key generation.",
        )

    logger.info("Generating a new Fernet encryption key.")
    new_key = Fernet.generate_key().decode("utf-8")

    try:
        keyring.set_password(SERVICE_NAME, KEY_ACCOUNT, new_key)
        logger.info("Successfully stored new encryption key in system keyring.")
    except Exception:
        logger.exception(
            "Failed to store new encryption key in system keyring. "
            "Key will not persist across application restarts.",
        )

    return new_key

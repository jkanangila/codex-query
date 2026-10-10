"""API key repository backed by the platform keystore via flet-secure-storage.

Keychain (iOS/macOS), Credential Manager (Windows), libsecret (Linux) and
Keystore (Android) do the encryption, so no master key is managed here.
"""

import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import override

import flet_secure_storage as fss

from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.domain.errors import SecureStorageUnavailableError
from codex_query.domain.models.api_key import ApiKey
from codex_query.domain.models.provider import LLMProvider
from codex_query.infrastructure.logging.factory import create_logger

KEY_PREFIX = "codex.api_key."

LINUX_DEPENDENCY_HINT = (
    "Secure storage is unavailable on this Linux system. Install libsecret "
    "(e.g. `sudo apt-get install libsecret-1-0`) and a keyring service such as "
    "gnome-keyring or kwalletmanager, make sure it is running, then restart the codex."
)

# Lower-case fragments of the errors libsecret / D-Bus produce when the library or
# the Secret Service (org.freedesktop.secrets) is missing or unreachable.
_MISSING_DEPENDENCY_MARKERS = (
    "org.freedesktop.secrets",
    "secret service",
    "secretservice",
    "serviceunknown",
    "dbus",
    "d-bus",
)

logger = create_logger(__name__)


def is_linux_desktop() -> bool:
    """True on desktop Linux; False on Android, which also reports 'linux'."""
    if not sys.platform.startswith("linux"):
        return False
    return not (hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ)


def is_missing_dependency_error(err: BaseException) -> bool:
    """Whether `err` looks like missing libsecret / Secret Service."""
    text = f"{type(err).__name__} {err}".lower()
    return any(marker in text for marker in _MISSING_DEPENDENCY_MARKERS)


def _storage_key(provider: LLMProvider) -> str:
    return f"{KEY_PREFIX}{provider.value}"


class SecureStorageApiKeyRepository(ApiKeyRepositoryPort):
    """Implements `ApiKeyRepositoryPort`: one key per provider."""

    def __init__(
        self,
        storage: fss.SecureStorage,
        *,
        linux_desktop: bool | None = None,
    ) -> None:
        """Initialize with a `SecureStorage` service instance.

        Args:
            storage: Flet secure storage service used to persist the keys.
            linux_desktop: Override platform detection (mainly for tests).
        """
        self._storage = storage
        self._linux_desktop = (
            is_linux_desktop() if linux_desktop is None else linux_desktop
        )

    @contextmanager
    def _translated(self) -> Generator[None]:
        """Raise `SecureStorageUnavailableError` for Linux missing-dependency errors.

        Any other failure propagates unchanged.
        """
        try:
            yield
        except Exception as err:
            if self._linux_desktop and is_missing_dependency_error(err):
                logger.error("Linux secure storage dependencies missing: %s", err)
                raise SecureStorageUnavailableError(LINUX_DEPENDENCY_HINT) from err
            raise

    @override
    async def get(self, provider: LLMProvider) -> ApiKey | None:
        """Return the stored key, or None if absent or unreadable.

        Raises:
            SecureStorageUnavailableError: On Linux when libsecret or the keyring
                service is missing.
        """
        try:
            with self._translated():
                value = await self._storage.get(_storage_key(provider))
        except SecureStorageUnavailableError:
            raise
        except Exception as err:
            logger.warning(
                "Secure storage read failed for '%s' (%s)",
                provider.value,
                type(err).__name__,
            )
            return None
        if value is None or not value.strip():
            return None
        return ApiKey(provider, value)

    @override
    async def save(self, key: ApiKey) -> None:
        """Insert or replace the key for `key.provider`.

        Raises:
            SecureStorageUnavailableError: On Linux when libsecret or the keyring
                service is missing.
        """
        with self._translated():
            await self._storage.set(_storage_key(key.provider), key.value)

    @override
    async def delete(self, provider: LLMProvider) -> None:
        """Remove the key for `provider`, if any.

        Raises:
            SecureStorageUnavailableError: On Linux when libsecret or the keyring
                service is missing.
        """
        with self._translated():
            await self._storage.remove(_storage_key(provider))

    @override
    async def list_providers(self) -> list[LLMProvider]:
        """Providers that have a saved key.

        Raises:
            SecureStorageUnavailableError: On Linux when libsecret or the keyring
                service is missing.
        """
        with self._translated():
            stored = await self._storage.get_all()
        return [
            provider
            for provider in LLMProvider
            if stored.get(_storage_key(provider), "").strip()
        ]

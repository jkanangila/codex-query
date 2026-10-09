from typing import Protocol

from codex_query.domain.models.api_key import ApiKey
from codex_query.domain.models.provider import LLMProvider


class ApiKeyRepositoryPort(Protocol):
    """One key per provider, shared by chat and embeddings."""

    async def get(self, provider: LLMProvider) -> ApiKey | None:
        """Return the stored key, or None if absent or unreadable."""
        ...

    async def save(self, key: ApiKey) -> None:
        """Insert or replace the key for `key.provider`."""
        ...

    async def delete(self, provider: LLMProvider) -> None: ...

    async def list_providers(self) -> list[LLMProvider]:
        """Providers that have a saved key (for 'key saved' badges in the UI)."""
        ...

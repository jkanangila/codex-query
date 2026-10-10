from datetime import UTC, datetime
from typing import override

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.domain.models.api_key import ApiKey as DomainApiKey
from codex_query.domain.models.provider import LLMProvider
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import ApiKey
from codex_query.infrastructure.security.cipher import (
    SecretCipher,
    SecretDecryptionError,
)

logger = create_logger(__name__)


class SqlModelApiKeyRepository(ApiKeyRepositoryPort):
    """Implements `ApiKeyRepositoryPort`; values are Fernet-encrypted at rest."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: SecretCipher,
    ) -> None:
        self._session = session
        self._cipher = cipher

    @override
    async def get(self, provider: LLMProvider) -> DomainApiKey | None:
        record = await self._session.get(ApiKey, provider.value)
        if record is None:
            return None
        try:
            value = self._cipher.decrypt(record.encrypted_key)
        except SecretDecryptionError:
            logger.warning("Stored key for %s is unreadable", provider.value)
            return None
        updated_at = record.updated_at
        if updated_at.tzinfo is None:  # SQLite drops tzinfo
            updated_at = updated_at.replace(tzinfo=UTC)
        return DomainApiKey(provider, value, updated_at)

    @override
    async def save(self, key: DomainApiKey) -> None:
        encrypted = self._cipher.encrypt(key.value)
        record = await self._session.get(ApiKey, key.provider.value)
        if record is None:
            self._session.add(
                ApiKey(provider=key.provider.value, encrypted_key=encrypted)
            )
        else:
            record.encrypted_key = encrypted
            record.updated_at = datetime.now(UTC)
        await self._session.flush()
        logger.debug("Saved API key for %s", key.provider.value)

    @override
    async def delete(self, provider: LLMProvider) -> None:
        record = await self._session.get(ApiKey, provider.value)
        if record is not None:
            await self._session.delete(record)

    @override
    async def list_providers(self) -> list[LLMProvider]:
        result = await self._session.exec(select(col(ApiKey.provider)))
        names = result.all()
        providers: list[LLMProvider] = []
        for name in names:
            try:
                providers.append(LLMProvider(name))
            except ValueError:
                logger.warning("Ignoring key row for unknown provider %r", name)
        return providers

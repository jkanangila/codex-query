"""Checks that a chat or embedding configuration actually works.

Tests the settings you pass in (e.g. unsaved form values), so the UI can offer
a "Test connection" button before the user commits anything.
"""

import asyncio
from collections.abc import Callable
from time import perf_counter

from codex_query.application.ports.chat import ChatPort
from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.domain.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from codex_query.domain.models.chat import ChatMessage, GenerationParams, Role
from codex_query.domain.models.connection import ConnectionTestResult
from codex_query.domain.models.embedding import EmbeddingInputType
from codex_query.domain.models.settings import ServiceSettings

type ChatFactory = Callable[[ServiceSettings], ChatPort]
type EmbeddingFactory = Callable[[ServiceSettings], EmbeddingPort]

_CHAT_PROBE = [ChatMessage(Role.USER, "Reply with the single word: OK")]
# Small but not tiny: some providers reject or return nothing for very low limits.
_CHAT_PARAMS = GenerationParams(temperature=0.0, max_tokens=32)
_EMBEDDING_PROBE = ["connection test"]
_MAX_DETAIL_CHARS = 300
_NOT_FOUND = 404


def _describe(exc: ProviderError) -> str:
    """Turn a provider error into one actionable sentence."""
    detail = str(exc)[:_MAX_DETAIL_CHARS]
    match exc:
        case ProviderAuthError():
            return f"Authentication failed. Check the API key. ({detail})"
        case ProviderRateLimitError(retry_after=wait):
            hint = f" Retry in {wait:.0f}s." if wait else ""
            return f"The provider is rate limiting requests.{hint}"
        case ProviderRequestError(status_code=status) if status == _NOT_FOUND:
            return f"Not found. Check the base URL and model name. ({detail})"
        case ProviderRequestError(status_code=status):
            code = f" ({status})" if status is not None else ""
            return f"The request was rejected{code}: {detail}"
        case ProviderUnavailableError():
            return f"Could not reach the server: {detail}"
        case ProviderResponseError():
            return f"The server answered with something unexpected: {detail}"
        case _:  # e.g. ProviderConfigurationError: missing key, unsupported service
            return detail


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000


class ConnectionTestService:
    def __init__(
        self,
        chat_factory: ChatFactory,
        embedding_factory: EmbeddingFactory,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Args:
        chat_factory: Builds a chat adapter from settings (injected from the
            composition root so this layer never imports infrastructure).
        embedding_factory: Same, for embeddings.
        timeout_seconds: Overall limit per test. Local models can need a while
            for their first request while they load into memory.
        """
        self._chat_factory = chat_factory
        self._embedding_factory = embedding_factory
        self._timeout = timeout_seconds

    async def test_chat(self, settings: ServiceSettings) -> ConnectionTestResult:
        start = perf_counter()
        try:
            async with asyncio.timeout(self._timeout):
                chat = self._chat_factory(settings)
                await chat.complete(_CHAT_PROBE, _CHAT_PARAMS)
        except TimeoutError:
            return self._timed_out(start)
        except ProviderError as exc:
            return ConnectionTestResult(False, _describe(exc), _elapsed_ms(start))
        return ConnectionTestResult(
            True,
            f"Connected. Chat model {settings.model!r} responded.",
            _elapsed_ms(start),
        )

    async def test_embedding(self, settings: ServiceSettings) -> ConnectionTestResult:
        start = perf_counter()
        try:
            async with asyncio.timeout(self._timeout):
                embedder = self._embedding_factory(settings)
                vectors = await embedder.embed(
                    _EMBEDDING_PROBE, EmbeddingInputType.QUERY
                )
        except TimeoutError:
            return self._timed_out(start)
        except ProviderError as exc:
            return ConnectionTestResult(False, _describe(exc), _elapsed_ms(start))

        dimension = len(vectors[0]) if vectors else 0
        if dimension == 0:
            return ConnectionTestResult(
                False, "The model returned an empty embedding.", _elapsed_ms(start)
            )
        return ConnectionTestResult(
            True,
            f"Connected. Embedding model {settings.model!r} returned "
            f"{dimension}-dimensional vectors.",
            _elapsed_ms(start),
            embedding_dimension=dimension,
        )

    def _timed_out(self, start: float) -> ConnectionTestResult:
        return ConnectionTestResult(
            False,
            f"Timed out after {self._timeout:.0f}s. A local model may still be "
            "loading; try again.",
            _elapsed_ms(start),
        )

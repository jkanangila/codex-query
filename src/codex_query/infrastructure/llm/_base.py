"""Shared HTTP plumbing for every provider adapter."""

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import cast, override

import httpx

from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.domain.errors import (
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from codex_query.domain.models.chat import ChatMessage
from codex_query.domain.models.embedding import EmbeddingInputType
from codex_query.domain.models.provider import (
    AuthType,
    EmbeddingProviderConfig,
    EndpointConfig,
)
from codex_query.domain.models.settings import ServiceSettings
from codex_query.infrastructure.llm._json import (
    JsonObject,
    as_object,
    as_object_or_none,
    get_str_or_none,
    parse_json,
)
from codex_query.infrastructure.logging.factory import create_logger

_MAX_DETAIL_CHARS = 500

logger = create_logger(__name__)


def to_wire_messages(messages: Sequence[ChatMessage]) -> list[JsonObject]:
    """Convert a sequence of chat messages into standard provider wire format.

    Args:
        messages: The chat messages to convert.

    Returns:
        A list of dictionaries containing `role` and `content` keys.
    """
    logger.debug("Converting %d ChatMessages to wire format", len(messages))
    wire_msgs = [{"role": m.role.value, "content": m.content} for m in messages]
    logger.debug("Converted messages wire format result: %s", wire_msgs)
    return cast(list[JsonObject], wire_msgs)


def _build_headers(config: EndpointConfig, api_key: str) -> dict[str, str]:
    """Build the request headers dictionary including authentication headers.

    Args:
        config: The endpoint configuration containing default headers and auth style.
        api_key: The API key for authenticating the request.

    Returns:
        A dictionary of HTTP request headers.
    """
    logger.debug("Building request headers for endpoint configuration")
    headers = dict(config.extra_headers)
    if api_key:
        if config.auth.type is AuthType.BEARER_TOKEN:
            logger.debug(
                "Applying bearer token auth header %r", config.auth.header_name
            )
            headers[config.auth.header_name] = f"Bearer {api_key}"
        else:
            logger.debug("Applying raw API key auth header %r", config.auth.header_name)
            headers[config.auth.header_name] = api_key
    else:
        logger.debug("No API key provided for header generation")
    return headers


def _extract_detail(text: str) -> str:
    """Extract an error detail message or fallback snippet from a response body.

    Args:
        text: Raw response body string.

    Returns:
        Extracted error message string or truncated response snippet.
    """
    snippet = text.strip()[:_MAX_DETAIL_CHARS] or "empty response body"
    logger.debug("Extracting error detail from body snippet: %r", snippet)
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Failed to parse response body as JSON; returning snippet")
        return snippet

    if isinstance(payload, list) and payload:  # Gemini sometimes wraps in a list
        logger.debug("Response payload is a list; extracting first item")
        payload = payload[0]  # pyright: ignore[reportUnknownVariableType]

    body = as_object_or_none(payload)
    if body is None:
        logger.debug("Parsed JSON payload is not an object; returning snippet")
        return snippet

    error = body.get("error")
    nested = as_object_or_none(error)
    message = (
        get_str_or_none(nested, "message")
        if nested is not None
        else error
        if isinstance(error, str)
        else get_str_or_none(body, "message")
    )

    extracted = message or snippet
    logger.debug("Extracted error detail: %r", extracted)
    return extracted


def _retry_after(response: httpx.Response) -> float | None:
    """Parse the `Retry-After` header value from an HTTP response if present.

    Args:
        response: The HTTP response to inspect.

    Returns:
        Retry delay in seconds as a float, or None if missing or unparsable.
    """
    try:
        val = float(response.headers["retry-after"])
        logger.debug("Found Retry-After header: %f seconds", val)
        return val
    except (KeyError, ValueError) as exc:
        logger.debug("Retry-After header missing or unparsable: %exc", exc)
        return None


def _error_from_response(response: httpx.Response) -> ProviderError:
    """Map an HTTP error response to the corresponding ProviderError exception type.

    Args:
        response: The failed HTTP response object.

    Returns:
        An instance of `ProviderError` suited to the response status code.
    """
    status = response.status_code
    detail = _extract_detail(response.text)
    logger.warning("Received HTTP error %d: %s", status, detail)

    if status in (401, 403):
        return ProviderAuthError(detail)
    if status == 429:
        retry_delay = _retry_after(response)
        return ProviderRateLimitError(detail, retry_delay)
    if status >= 500:
        return ProviderUnavailableError(f"HTTP {status}: {detail}")
    return ProviderRequestError(detail, status)


def _unavailable(exc: httpx.RequestError) -> ProviderUnavailableError:
    """Wrap low-level HTTP transport errors into ProviderUnavailableError.

    Args:
        exc: The network request exception.

    Returns:
        An instance of `ProviderUnavailableError`.
    """
    logger.error(
        "HTTP request transport error occurred: %s: %s", type(exc).__name__, exc
    )
    return ProviderUnavailableError(f"{type(exc).__name__}: {exc}")


class HttpAdapter:
    """Resolves URL/model/auth once, then offers JSON, SSE and NDJSON calls.

    The `httpx.AsyncClient` is injected and owned by the composition root, so
    adapters are cheap to rebuild whenever settings change.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: EndpointConfig,
        settings: ServiceSettings,
    ) -> None:
        """Initialize the HTTP adapter with connection client and configurations.

        Args:
            client: Shared async HTTP client instance.
            config: Target endpoint definition and auth rules.
            settings: Runtime credentials and configuration overrides.

        Raises:
            ProviderConfigurationError: If required API keys are missing.
        """
        logger.debug("Initializing HttpAdapter for endpoint config %r", config.name)
        if config.auth.api_key_required and not settings.api_key:
            msg = f"{config.name} requires an API key"
            logger.error("Configuration error: %s", msg)
            raise ProviderConfigurationError(msg)

        self._client = client
        self._model = settings.model or config.default_model
        base_url = (settings.base_url or config.base_url).rstrip("/")
        self._url = f"{base_url}{config.path}"
        self._headers = _build_headers(config, settings.api_key)
        logger.debug(
            "HttpAdapter initialized (URL=%r, Model=%r)", self._url, self._model
        )

    async def _post_json(self, body: JsonObject) -> JsonObject:
        """Send a POST request with a JSON body and return the parsed JSON response.

        Args:
            body: Payload dictionary to serialize to JSON.

        Returns:
            Parsed response JSON object.

        Raises:
            ProviderError: On non-2xx HTTP status codes or request failure.
        """
        logger.debug("Posting JSON request to %r", self._url)
        try:
            response = await self._client.post(
                self._url, json=body, headers=self._headers
            )
        except httpx.RequestError as exc:
            raise _unavailable(exc) from exc

        logger.debug("HTTP POST status code: %d", response.status_code)
        if response.is_error:
            raise _error_from_response(response)

        return as_object(parse_json(response.text), "response body")

    async def _stream_lines(self, body: JsonObject) -> AsyncIterator[str]:
        """Stream response lines asynchronously for a POST request.

        Args:
            body: Payload dictionary to serialize to JSON.

        Yields:
            Individual raw lines from the HTTP response stream.

        Raises:
            ProviderError: On non-2xx HTTP status codes or request failure.
        """
        logger.debug("Opening streaming connection to %r", self._url)
        try:
            async with self._client.stream(
                "POST", self._url, json=body, headers=self._headers
            ) as response:
                logger.debug("Streaming HTTP status code: %d", response.status_code)
                if response.is_error:
                    await response.aread()
                    raise _error_from_response(response)

                line_count = 0
                async for line in response.aiter_lines():
                    line_count += 1
                    yield line
                logger.debug("Streaming finished after receiving %d lines", line_count)
        except httpx.RequestError as exc:
            raise _unavailable(exc) from exc

    async def _stream_sse(self, body: JsonObject) -> AsyncIterator[JsonObject]:
        """Stream parsed JSON events from a Server-Sent Events (SSE) stream.

        Args:
            body: Payload dictionary to serialize to JSON.

        Yields:
            Parsed JSON objects from SSE data lines.
        """
        logger.debug("Parsing SSE stream events")
        event_count = 0
        async for line in self._stream_lines(body):
            if not line.startswith("data:"):
                continue  # "event:" names, comments and blank separators
            data = line.removeprefix("data:").strip()
            if data and data != "[DONE]":
                event_count += 1
                logger.debug("Yielding SSE event #%d", event_count)
                yield as_object(parse_json(data), "stream event")
        logger.debug("SSE stream finished (%d events yielded)", event_count)

    async def _stream_ndjson(self, body: JsonObject) -> AsyncIterator[JsonObject]:
        """Stream parsed JSON objects from a newline-delimited JSON (NDJSON) stream.

        Args:
            body: Payload dictionary to serialize to JSON.

        Yields:
            Parsed JSON objects from stream lines.
        """
        logger.debug("Parsing NDJSON stream lines")
        line_count = 0
        async for line in self._stream_lines(body):
            if line.strip():
                line_count += 1
                logger.debug("Yielding NDJSON line #%d", line_count)
                yield as_object(parse_json(line), "stream line")
        logger.debug("NDJSON stream finished (%d lines processed)", line_count)


class BatchedEmbeddingAdapter(HttpAdapter, ABC, EmbeddingPort):
    """Splits `texts` into provider-sized batches; subclasses embed one batch."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: EmbeddingProviderConfig,
        settings: ServiceSettings,
    ) -> None:
        """Initialize the batched embedding adapter.

        Args:
            client: Shared async HTTP client instance.
            config: Configuration settings specifying max batch size.
            settings: Runtime provider settings and credentials.
        """
        super().__init__(client, config, settings)
        self._batch_size = config.max_batch_size
        logger.debug(
            "BatchedEmbeddingAdapter initialized with max_batch_size=%d",
            self._batch_size,
        )

    @override
    async def embed(
        self,
        texts: Sequence[str],
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> list[list[float]]:
        """Generate embeddings for texts, automatically chunking inputs into batches.

        Args:
            texts: Sequence of input strings to embed.
            input_type: Context type for embedding generation (e.g. document vs query).

        Returns:
            A list of float vector embeddings corresponding to each input text.

        Raises:
            ProviderResponseError: If the returned vector count mismatches input size.
        """
        total_texts = len(texts)
        logger.info(
            "Embedding request received for %d texts (input_type=%s, batch_size=%d)",
            total_texts,
            input_type,
            self._batch_size,
        )
        vectors: list[list[float]] = []
        batch_index = 0

        for start in range(0, total_texts, self._batch_size):
            batch_index += 1
            batch = texts[start : start + self._batch_size]
            logger.debug(
                "Processing embedding batch #%d (%d texts)",
                batch_index,
                len(batch),
            )
            result = await self._embed_batch(batch, input_type)

            if len(result) != len(batch):
                msg = f"Sent {len(batch)} texts but received {len(result)} vectors"
                logger.error("Embedding batch count mismatch: %s", msg)
                raise ProviderResponseError(msg)

            vectors.extend(result)

        logger.info(
            "Embedding complete. Generated %d total vectors across %d batches",
            len(vectors),
            batch_index,
        )
        return vectors

    @abstractmethod
    async def _embed_batch(
        self, texts: Sequence[str], input_type: EmbeddingInputType
    ) -> list[list[float]]:
        """Embed a single batch of texts within provider size limits.

        Args:
            texts: Batch slice of strings to embed.
            input_type: Context type for embedding generation.

        Returns:
            List of float vector embeddings.
        """
        ...

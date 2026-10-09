"""OpenAI dialect: OpenAI, Google Gemini (compat endpoint) and Mistral."""

from collections.abc import AsyncIterator, Sequence
from typing import override

import httpx

from codex_query.application.ports.chat import ChatPort
from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.domain.errors import ProviderResponseError
from codex_query.domain.models.chat import (
    ChatMessage,
    ChatResult,
    GenerationParams,
    TokenUsage,
)
from codex_query.domain.models.embedding import EmbeddingInputType
from codex_query.domain.models.provider import ChatProviderConfig
from codex_query.domain.models.settings import ServiceSettings
from codex_query.infrastructure.llm._base import (
    BatchedEmbeddingAdapter,
    HttpAdapter,
    to_wire_messages,
)
from codex_query.infrastructure.llm._json import (
    JsonObject,
    as_float_vector,
    as_object,
    get_int_or_none,
    get_list,
    get_list_or_empty,
    get_object,
    get_object_or_empty,
    get_str_or_none,
)
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


def _parse_usage(data: JsonObject) -> TokenUsage | None:
    """Extract and parse token usage information from a provider response body.

    Args:
        data: Response body dictionary containing potential usage statistics.

    Returns:
        A `TokenUsage` object if both prompt and completion token counts exist,
        or `None` if missing or incomplete.
    """
    logger.debug("Parsing token usage from response data")
    usage = get_object_or_empty(data, "usage")
    prompt = get_int_or_none(usage, "prompt_tokens")
    completion = get_int_or_none(usage, "completion_tokens")

    if prompt is None or completion is None:
        logger.debug(
            "Token usage incomplete or missing "
            "(prompt_tokens=%s, completion_tokens=%s)",
            prompt,
            completion,
        )
        return None

    logger.debug(
        "Successfully parsed token usage (prompt_tokens=%d, completion_tokens=%d)",
        prompt,
        completion,
    )
    return TokenUsage(prompt, completion)


class OpenAIChatAdapter(HttpAdapter, ChatPort):
    """Adapter for OpenAI-compatible Chat Completions API endpoints."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: ChatProviderConfig,
        settings: ServiceSettings,
    ) -> None:
        """Initialize the OpenAI chat adapter.

        Args:
            client: Shared async HTTP client instance.
            config: Chat provider configuration including max tokens parameter name.
            settings: Runtime provider credentials and setting overrides.
        """
        super().__init__(client, config, settings)
        self._max_tokens_param = config.max_tokens_param
        logger.debug(
            "OpenAIChatAdapter initialized with max_tokens_param=%r",
            self._max_tokens_param,
        )

    def _body(
        self,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
        *,
        stream: bool,
    ) -> JsonObject:
        """Construct the HTTP request payload for OpenAI-compatible chat requests.

        Args:
            messages: Sequence of input chat messages.
            params: Parameters controlling model generation.
            stream: Whether to request a streaming SSE response.

        Returns:
            A JSON object payload dictionary.
        """
        logger.debug(
            "Constructing OpenAI chat payload (model=%r, stream=%s, messages_count=%d)",
            self._model,
            stream,
            len(messages),
        )
        body: JsonObject = {
            "model": self._model,
            "messages": to_wire_messages(messages),
            "temperature": params.temperature,
            self._max_tokens_param: params.max_tokens,
        }
        if stream:
            body["stream"] = True

        logger.debug("Constructed OpenAI chat payload: %s", body)
        return body

    @override
    async def complete(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> ChatResult:
        """Send a non-streaming chat completion request to an OpenAI-compatible API.

        Args:
            messages: Sequence of conversation messages.
            params: Model generation parameters.

        Returns:
            A `ChatResult` containing model output text, usage statistics,
                and finish reason.

        Raises:
            ProviderResponseError: If the API response contains no choices.
        """
        logger.info(
            "Sending non-streaming chat request to OpenAI "
            "(model=%r, messages_count=%d)",
            self._model,
            len(messages),
        )
        body = self._body(messages, params, stream=False)
        data = await self._post_json(body)

        logger.debug("Parsing non-streaming response body: %s", data)
        choices = get_list(data, "choices")
        if not choices:
            msg = "Response contained no choices"
            logger.error("Failed to parse OpenAI chat response: %s", msg)
            raise ProviderResponseError(msg)

        choice = as_object(choices[0], "choices[0]")
        message = get_object(choice, "message")
        text = get_str_or_none(message, "content") or ""
        usage = _parse_usage(data)
        finish_reason = get_str_or_none(choice, "finish_reason")

        logger.info(
            "OpenAI chat completion successful (text_length=%d, finish_reason=%s)",
            len(text),
            finish_reason,
        )

        return ChatResult(
            text=text,
            usage=usage,
            finish_reason=finish_reason,
        )

    @override
    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]:
        """Stream text deltas asynchronously from an OpenAI-compatible SSE endpoint.

        Args:
            messages: Sequence of input conversation messages.
            params: Parameters controlling text generation.

        Yields:
            Individual text chunk strings as they arrive from the stream.
        """
        logger.info(
            "Initiating streaming chat request to OpenAI (model=%r, messages_count=%d)",
            self._model,
            len(messages),
        )
        body = self._body(messages, params, stream=True)
        event_count = 0
        yielded_chunks = 0

        async for event in self._stream_sse(body):
            event_count += 1
            choices = get_list_or_empty(event, "choices")
            if not choices:  # e.g. Gemini's leading/usage-only chunks
                logger.debug(
                    "Skipping SSE event #%d without choices (usage/metadata chunk)",
                    event_count,
                )
                continue

            delta = get_object_or_empty(as_object(choices[0], "choices[0]"), "delta")
            text = get_str_or_none(delta, "content")
            if text:
                yielded_chunks += 1
                logger.debug(
                    "Yielding text chunk #%d (length=%d)",
                    yielded_chunks,
                    len(text),
                )
                yield text

        logger.info(
            "OpenAI stream finished (total_events=%d, chunks_yielded=%d)",
            event_count,
            yielded_chunks,
        )


class OpenAIEmbeddingAdapter(BatchedEmbeddingAdapter, EmbeddingPort):
    """Adapter for OpenAI-compatible Embeddings API endpoints."""

    @override
    async def _embed_batch(
        self,
        texts: Sequence[str],
        input_type: EmbeddingInputType,
    ) -> list[list[float]]:
        """Embed a single batch of texts using an OpenAI-compatible Embeddings API.

        Args:
            texts: Batch sequence of strings to embed.
            input_type: The application input context type (unused by OpenAI dialect).

        Returns:
            A list of float vector embeddings ordered by input index.
        """
        logger.info(
            "Requesting embedding batch from OpenAI (model=%r, count=%d)",
            self._model,
            len(texts),
        )
        payload: JsonObject = {
            "model": self._model,
            "input": list(texts),
            "encoding_format": "float",
        }
        logger.debug("Embedding request payload: %s", payload)

        data = await self._post_json(payload)
        logger.debug("Parsing embedding response body")

        rows: list[tuple[int, list[float]]] = []
        raw_items = get_list(data, "data")

        for position, raw in enumerate(raw_items):
            item = as_object(raw, "data[]")
            index = get_int_or_none(item, "index")
            vector = as_float_vector(item.get("embedding"), "embedding")
            effective_index = position if index is None else index
            rows.append((effective_index, vector))

        rows.sort(key=lambda row: row[0])
        vectors = [vector for _, vector in rows]

        logger.info(
            "Successfully extracted and ordered %d float vectors "
            "from OpenAI batch response",
            len(vectors),
        )
        return vectors

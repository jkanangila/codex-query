"""Cohere v2 chat and embed APIs."""

from collections.abc import AsyncIterator, Sequence
from typing import override

from codex_query.application.ports.chat import ChatPort
from codex_query.domain.models.chat import (
    ChatMessage,
    ChatResult,
    GenerationParams,
    TokenUsage,
)
from codex_query.domain.models.embedding import EmbeddingInputType
from codex_query.infrastructure.llm._base import (
    BatchedEmbeddingAdapter,
    HttpAdapter,
    to_wire_messages,
)
from codex_query.infrastructure.llm._json import (
    JsonObject,
    as_float_vector,
    as_list,
    as_object,
    get_int_or_none,
    get_list,
    get_object,
    get_object_or_empty,
    get_str_or_none,
)
from codex_query.infrastructure.logging.factory import create_logger

_INPUT_TYPES = {
    EmbeddingInputType.DOCUMENT: "search_document",
    EmbeddingInputType.QUERY: "search_query",
}

logger = create_logger(__name__)


class CohereChatAdapter(HttpAdapter, ChatPort):
    """Adapter for Cohere's Chat API v2 supporting completion and streaming."""

    def _body(
        self,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
        *,
        stream: bool,
    ) -> JsonObject:
        """Construct the HTTP request payload for Cohere chat requests.

        Args:
            messages: Sequence of input chat messages.
            params: Parameters controlling model generation.
            stream: Whether to request a streaming response.

        Returns:
            A JSON object payload dictionary.
        """
        logger.debug(
            "Constructing Cohere chat payload (model=%r, stream=%s, messages_count=%d)",
            self._model,
            stream,
            len(messages),
        )
        body: JsonObject = {
            "model": self._model,
            "messages": to_wire_messages(messages),
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
        }
        if stream:
            body["stream"] = True

        logger.debug("Constructed Cohere chat payload: %s", body)
        return body

    @override
    async def complete(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> ChatResult:
        """Send a non-streaming chat completion request to Cohere.

        Args:
            messages: Sequence of conversation messages.
            params: Model generation parameters.

        Returns:
            A `ChatResult` containing model output text, usage statistics,
                and finish reason.
        """
        logger.info(
            (
                "Sending non-streaming chat request to"
                "Cohere (model=%r, messages_count=%d)"
            ),
            self._model,
            len(messages),
        )
        body = self._body(messages, params, stream=False)
        data = await self._post_json(body)

        logger.debug("Parsing non-streaming response body: %s", data)
        message = get_object(data, "message")
        parts: list[str] = []
        for raw in get_list(message, "content"):
            block = as_object(raw, "content[]")
            if block.get("type") == "text":
                text = get_str_or_none(block, "text") or ""
                parts.append(text)

        full_text = "".join(parts)
        tokens = get_object_or_empty(get_object_or_empty(data, "usage"), "tokens")
        tokens_in = get_int_or_none(tokens, "input_tokens")
        tokens_out = get_int_or_none(tokens, "output_tokens")
        finish_reason = get_str_or_none(data, "finish_reason")

        usage = (
            None
            if tokens_in is None or tokens_out is None
            else TokenUsage(tokens_in, tokens_out)
        )
        logger.info(
            (
                "Cohere chat completion successful "
                "(text_length=%d, tokens_in=%s, tokens_out=%s, finish_reason=%s)"
            ),
            len(full_text),
            tokens_in,
            tokens_out,
            finish_reason,
        )

        return ChatResult(
            text=full_text,
            usage=usage,
            finish_reason=finish_reason,
        )

    @override
    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]:
        """Stream text deltas asynchronously from Cohere's Chat API via SSE.

        Args:
            messages: Sequence of input conversation messages.
            params: Parameters controlling text generation.

        Yields:
            Individual text chunk strings as they arrive from the stream.
        """
        logger.info(
            "Initiating streaming chat request to Cohere (model=%r, messages_count=%d)",
            self._model,
            len(messages),
        )
        body = self._body(messages, params, stream=True)
        event_count = 0
        yielded_chunks = 0

        async for event in self._stream_sse(body):
            event_count += 1
            event_type = event.get("type")
            if event_type != "content-delta":
                logger.debug(
                    "Ignoring non-content-delta SSE event #%d (type=%r)",
                    event_count,
                    event_type,
                )
                continue

            delta = get_object_or_empty(event, "delta")
            message = get_object_or_empty(delta, "message")
            content = get_object_or_empty(message, "content")
            text = get_str_or_none(content, "text")

            if text:
                yielded_chunks += 1
                logger.debug(
                    "Yielding text chunk #%d (length=%d)", yielded_chunks, len(text)
                )
                yield text

        logger.info(
            "Cohere stream finished (total_events=%d, chunks_yielded=%d)",
            event_count,
            yielded_chunks,
        )


class CohereEmbeddingAdapter(BatchedEmbeddingAdapter):
    """Adapter for Cohere's Embed API v3."""

    @override
    async def _embed_batch(
        self, texts: Sequence[str], input_type: EmbeddingInputType
    ) -> list[list[float]]:
        """Embed a single batch of texts using Cohere's Embed API.

        Args:
            texts: Batch sequence of strings to embed.
            input_type: The application input context type (e.g. document or query).

        Returns:
            A list of float vector embeddings.
        """
        mapped_input_type = _INPUT_TYPES[input_type]
        logger.info(
            (
                "Requesting embedding batch from Cohere "
                "(model=%r, count=%d, input_type=%s)"
            ),
            self._model,
            len(texts),
            mapped_input_type,
        )
        payload: JsonObject = {
            "model": self._model,
            "texts": list(texts),
            "input_type": mapped_input_type,
            "embedding_types": ["float"],
        }
        logger.debug("Embedding request payload: %s", payload)

        data = await self._post_json(payload)
        logger.debug("Parsing embedding response body")

        embeddings = get_object(data, "embeddings")
        raw_float_list = as_list(embeddings.get("float"), "embeddings.float")

        vectors = [as_float_vector(raw, "embeddings.float[]") for raw in raw_float_list]
        logger.info(
            "Successfully extracted %d float vectors from Cohere batch response",
            len(vectors),
        )
        return vectors

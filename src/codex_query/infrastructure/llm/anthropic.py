"""Anthropic Messages API. Chat only: Anthropic has no embeddings endpoint."""

from collections.abc import AsyncIterator, Sequence
from typing import override

from codex_query.application.ports.chat import ChatPort
from codex_query.domain.errors import ProviderRequestError
from codex_query.domain.models.chat import (
    ChatMessage,
    ChatResult,
    GenerationParams,
    Role,
    TokenUsage,
)
from codex_query.infrastructure.llm._base import HttpAdapter
from codex_query.infrastructure.llm._json import (
    JsonObject,
    as_object,
    get_int_or_none,
    get_list,
    get_object_or_empty,
    get_str_or_none,
)
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class AnthropicChatAdapter(HttpAdapter, ChatPort):
    """Adapter for interacting with Anthropic's Messages API."""

    def _body(
        self,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
        *,
        stream: bool,
    ) -> JsonObject:
        """Construct the JSON payload body for Anthropic Messages API requests.

        Args:
            messages: The sequence of input chat messages.
            params: Parameters governing response generation.
            stream: Whether the request is configured for SSE streaming.

        Returns:
            The structured JSON object payload for the request.
        """
        logger.debug(
            "Constructing request body for model %r (stream=%s)",
            self._model,
            stream,
        )
        # The system prompt is a top-level field, not a message role.
        system = "\n\n".join(m.content for m in messages if m.role is Role.SYSTEM)
        turns: list[JsonObject] = [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role is not Role.SYSTEM
        ]
        body: JsonObject = {
            "model": self._model,
            "max_tokens": params.max_tokens,  # required by this API
            "temperature": params.temperature,
            "messages": turns,
        }
        if system:
            logger.debug("Extracted system prompt with %d characters", len(system))
            body["system"] = system
        if stream:
            body["stream"] = True

        logger.debug(
            "Built body with %d conversation turns (max_tokens=%d, temp=%s)",
            len(turns),
            params.max_tokens,
            params.temperature,
        )
        return body

    @override
    async def complete(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> ChatResult:
        """Send a completion request to Anthropic and return the compiled response.

        Args:
            messages: Conversation message history.
            params: Generation options like temperature and max tokens.

        Returns:
            A `ChatResult` containing generated text, usage stats, and finish reason.
        """
        logger.info(
            "Initiating completion request via Anthropic Messages API (model=%r)",
            self._model,
        )
        body = self._body(messages, params, stream=False)
        data = await self._post_json(body)

        parts: list[str] = []
        raw_content = get_list(data, "content")
        for raw in raw_content:
            block = as_object(raw, "content[]")
            if block.get("type") == "text":
                parts.append(get_str_or_none(block, "text") or "")

        finish_reason = get_str_or_none(data, "stop_reason")
        usage = get_object_or_empty(data, "usage")
        tokens_in = get_int_or_none(usage, "input_tokens")
        tokens_out = get_int_or_none(usage, "output_tokens")

        token_usage = (
            None
            if tokens_in is None or tokens_out is None
            else TokenUsage(tokens_in, tokens_out)
        )

        logger.info(
            "Completed request successfully. Received %d blocks, %d tokens in, "
            "%d tokens out (finish_reason=%r)",
            len(raw_content),
            tokens_in or 0,
            tokens_out or 0,
            finish_reason,
        )

        return ChatResult(
            text="".join(parts),
            usage=token_usage,
            finish_reason=finish_reason,
        )

    @override
    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]:
        """Stream completion text chunks asynchronously as they arrive from Anthropic.

        Args:
            messages: Conversation message history.
            params: Generation options like temperature and max tokens.

        Yields:
            Individual text delta chunks from the stream.

        Raises:
            ProviderRequestError: If an error event is received in the SSE stream.
        """
        logger.info(
            "Initiating streaming completion request via Anthropic Messages API "
            "(model=%r)",
            self._model,
        )
        body = self._body(messages, params, stream=True)
        chunk_count = 0

        async for event in self._stream_sse(body):
            kind = event.get("type")
            if kind == "content_block_delta":
                delta = get_object_or_empty(event, "delta")
                if delta.get("type") == "text_delta":
                    text = get_str_or_none(delta, "text")
                    if text:
                        chunk_count += 1
                        logger.debug(
                            "Yielding chunk %d (%d chars)", chunk_count, len(text)
                        )
                        yield text
            elif kind == "error":
                error = get_object_or_empty(event, "error")
                detail = get_str_or_none(error, "message") or "stream error"
                logger.error(
                    "Received error event from stream after %d chunks: %s",
                    chunk_count,
                    detail,
                )
                raise ProviderRequestError(detail)
            else:
                logger.debug("Received unhandled SSE event type: %r", kind)

        logger.info(
            "Stream finished successfully after yielding %d chunks", chunk_count
        )

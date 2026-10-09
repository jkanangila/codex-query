"""Ollama's native API.

Used instead of its OpenAI-compatible /v1 endpoints because only the native API
lets us set `num_ctx`. Without it Ollama silently truncates long RAG prompts to
its default context window.
"""

from collections.abc import AsyncIterator, Sequence
from typing import override

from codex_query.application.ports.chat import ChatPort
from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.domain.errors import ProviderRequestError
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
    get_int_or_none,
    get_object,
    get_object_or_empty,
    get_str_or_none,
)
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class OllamaChatAdapter(
    HttpAdapter,
    ChatPort,
):
    """Adapter for Ollama's Chat API supporting completion and NDJSON streaming."""

    def _body(
        self,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
        *,
        stream: bool,
    ) -> JsonObject:
        """Construct the HTTP request payload for Ollama chat requests.

        Args:
            messages: Sequence of input chat messages.
            params: Parameters controlling model generation and context window.
            stream: Whether to request a streaming response.

        Returns:
            A JSON object payload dictionary configured for Ollama.
        """
        logger.debug(
            "Constructing Ollama chat payload (model=%r, stream=%s, messages_count=%d)",
            self._model,
            stream,
            len(messages),
        )
        options: JsonObject = {
            "temperature": params.temperature,
            "num_predict": params.max_tokens,
        }
        if params.num_ctx is not None:
            logger.debug("Applying context size override num_ctx=%d", params.num_ctx)
            options["num_ctx"] = params.num_ctx

        body: JsonObject = {
            "model": self._model,
            "messages": to_wire_messages(messages),
            "stream": stream,
            "options": options,
        }
        logger.debug("Constructed Ollama chat payload: %s", body)
        return body

    @override
    async def complete(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> ChatResult:
        """Send a non-streaming chat completion request to Ollama.

        Args:
            messages: Sequence of conversation messages.
            params: Model generation parameters.

        Returns:
            A `ChatResult` containing model output text, usage statistics,
                and finish reason.
        """
        logger.info(
            (
                "Sending non-streaming chat request to Ollama "
                "(model=%r, messages_count=%d)"
            ),
            self._model,
            len(messages),
        )
        body = self._body(messages, params, stream=False)
        data = await self._post_json(body)

        logger.debug("Parsing non-streaming response body: %s", data)
        message = get_object(data, "message")
        text = get_str_or_none(message, "content") or ""

        tokens_in = get_int_or_none(data, "prompt_eval_count")
        tokens_out = get_int_or_none(data, "eval_count")
        finish_reason = get_str_or_none(data, "done_reason")

        usage = (
            None
            if tokens_in is None or tokens_out is None
            else TokenUsage(tokens_in, tokens_out)
        )
        logger.info(
            (
                "Ollama chat completion successful "
                "(text_length=%d, prompt_eval_count=%s, eval_count=%s, done_reason=%s)"
            ),
            len(text),
            tokens_in,
            tokens_out,
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
        """Stream text deltas asynchronously from Ollama's Chat API via NDJSON.

        Args:
            messages: Sequence of input conversation messages.
            params: Parameters controlling text generation.

        Yields:
            Individual text chunk strings as they arrive from the stream.

        Raises:
            ProviderRequestError: If an error field is present in an NDJSON line.
        """
        logger.info(
            "Initiating streaming chat request to Ollama (model=%r, messages_count=%d)",
            self._model,
            len(messages),
        )
        body = self._body(messages, params, stream=True)
        line_count = 0
        yielded_chunks = 0

        async for line in self._stream_ndjson(body):
            line_count += 1
            error = get_str_or_none(line, "error")
            if error is not None:
                logger.error("Ollama stream error on line #%d: %s", line_count, error)
                raise ProviderRequestError(error)

            text = get_str_or_none(get_object_or_empty(line, "message"), "content")
            if text:
                yielded_chunks += 1
                logger.debug(
                    "Yielding text chunk #%d (length=%d)",
                    yielded_chunks,
                    len(text),
                )
                yield text

        logger.info(
            "Ollama stream finished (total_lines=%d, chunks_yielded=%d)",
            line_count,
            yielded_chunks,
        )


class OllamaEmbeddingAdapter(BatchedEmbeddingAdapter, EmbeddingPort):
    """Adapter for Ollama's Embeddings API."""

    @override
    async def _embed_batch(
        self,
        texts: Sequence[str],
        input_type: EmbeddingInputType,
    ) -> list[list[float]]:
        """Embed a single batch of texts using Ollama's Embeddings API.

        Args:
            texts: Batch sequence of strings to embed.
            input_type: The application input context type (unused by Ollama API).

        Returns:
            A list of float vector embeddings.
        """
        logger.info(
            "Requesting embedding batch from Ollama (model=%r, count=%d)",
            self._model,
            len(texts),
        )
        payload: JsonObject = {"model": self._model, "input": list(texts)}
        logger.debug("Embedding request payload: %s", payload)

        data = await self._post_json(payload)
        logger.debug("Parsing embedding response body")

        raw_embeddings = as_list(data.get("embeddings"), "embeddings")
        vectors = [as_float_vector(raw, "embeddings[]") for raw in raw_embeddings]

        logger.info(
            "Successfully extracted %d float vectors from Ollama batch response",
            len(vectors),
        )
        return vectors

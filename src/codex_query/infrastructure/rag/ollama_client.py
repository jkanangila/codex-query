from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import override

from ollama import Client

from codex_query.application.ports.interfaces import IEmbeddingModel, IGenerator
from codex_query.domain.models.document import SearchHit

logger = logging.getLogger(__name__)


class OllamaEmbeddingModel(IEmbeddingModel):
    """Ollama client wrapper for generating dense text vector embeddings."""

    def __init__(self, client: Client, model: str) -> None:
        """Initialize embedding model with Ollama client and model name."""
        self._client, self._model = client, model

    @override
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate dense embedding vectors for input texts.

        Args:
            texts: Sequence of strings to convert to vector embeddings.

        Returns:
            List of float vector embeddings matching input length.
        """
        # Guard clause: return empty list if input sequence is empty
        if not texts:
            return []

        # Request batch vector embeddings from Ollama server
        logger.debug("Ollama embed: model=%s inputs=%d", self._model, len(texts))
        response = self._client.embed(
            model=self._model, input=list(texts), truncate=True
        )

        # Convert output vectors into standard float lists
        return [list(vector) for vector in response.embeddings]


class OllamaGenerator(IGenerator):
    """RAG response generator using Ollama chat models."""

    def __init__(self, client: Client, model: str, temperature: float = 0.1) -> None:
        """Initialize generator with Ollama client, model, and temp setting."""
        self._client, self._model, self._temperature = (
            client,
            model,
            temperature,
        )

    @override
    def answer(self, question: str, context: Sequence[SearchHit]) -> str:
        """Generate a grounded answer using retrieved search hits.

        Args:
            question: User search or factual prompt.
            context: Retrieved book excerpts used as evidence.

        Returns:
            Model response string cited with bracketed references.
        """
        # Build numbered evidence block with book metadata and text
        evidence = "\n\n".join(
            f"[{i}] {hit.metadata.get('book_title', 'Unknown')} — "
            f"{hit.metadata.get('chapter_title', 'Unknown chapter')}\n"
            f"{hit.text}"
            for i, hit in enumerate(context, 1)
        )

        # Construct strict RAG prompt enforcing grounded responses
        prompt = (
            "Answer the question using only the supplied book excerpts. "
            "If the excerpts do not contain enough information, say so. "
            "Cite supporting excerpts as [1], [2], etc.\n\n"
            f"QUESTION:\n{question}\n\nEXCERPTS:\n{evidence}"
        )

        # Execute non-streaming chat request against Ollama
        logger.debug("Ollama chat: model=%s context_hits=%d", self._model, len(context))
        response = self._client.chat(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": ("You are a precise offline book research assistant."),
                },
                {"role": "user", "content": prompt},
            ],
            options={"temperature": self._temperature},
            stream=False,
        )

        # Return generated text content from model response
        return response.message.content or ""

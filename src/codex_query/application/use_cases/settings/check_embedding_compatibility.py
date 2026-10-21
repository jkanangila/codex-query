"""Use case for verifying embedding compatibility and identifying stale books."""

from collections.abc import Sequence
from dataclasses import dataclass

from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.models.document import Book
from codex_query.domain.models.provider import LLMProvider


@dataclass(frozen=True, slots=True)
class StaleBook:
    """Representation of a book that requires reindexing due to model changes."""

    id: int | None
    title: str
    series: str | None


class CheckEmbeddingCompatibility:
    """Use case to scan for books whose embeddings do not match the target model."""

    def __init__(self, read_uow_factory: UnitOfWorkFactory) -> None:
        """Initialize the use case with a read-only unit of work factory."""
        self._uow_factory = read_uow_factory

    async def __call__(self, provider: LLMProvider, model: str) -> Sequence[StaleBook]:
        """Identify and return all books requiring reindexing for a new model
        configuration.

        Args:
            provider: The target LLM embedding provider.
            model: The target embedding model identifier.

        Returns:
            A sequence of stale books that need to be reindexed.
        """
        async with self._uow_factory() as uow:
            books = await uow.books.get_all()

        stale = [
            StaleBook(id=book.id, title=book.title, series=book.series)
            for book in books
            if self._is_stale(book, provider, model)
        ]

        return stale

    @staticmethod
    def _is_stale(book: Book, provider: LLMProvider, model: str) -> bool:
        """Determine if a book's stored embedding metadata differs from the target.

        A book with no recorded provider or model (it never finished its first
        indexing) counts as stale.
        """
        stored_provider = book.meta.embedding_provider
        stored_model = book.meta.embedding_model
        if stored_provider is None or stored_model is None:
            return True
        return (
            provider.lower() != stored_provider.lower()
            or model.lower() != stored_model.lower()
        )

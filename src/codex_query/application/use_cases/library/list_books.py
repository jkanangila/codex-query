"""Use case for listing all books in the catalog.

This module provides the ListBooks use case, which retrieves all book entities
using a read unit of work.
"""

from collections.abc import Sequence

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.application.ports.unit_of_work import UnitOfWorkFactory
from codex_query.domain.models.document import Book


class ListBooks:
    """Use case for retrieving all books from the data store."""

    def __init__(
        self,
        read_uow_factory: UnitOfWorkFactory,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the ListBooks use case.

        Args:
            read_uow_factory (UnitOfWorkFactory): Factory for creating read
                units of work.
            logger_factory (LoggerFactoryPort): Factory for creating loggers.
        """
        self._read_uow_factory = read_uow_factory
        self._logger = logger_factory.create(__name__)

    async def __call__(self) -> Sequence[Book]:
        """Execute the use case to retrieve all books.

        Returns:
            Sequence[Book]: A sequence of all available books.
        """
        self._logger.info("Starting retrieval of all books.")
        async with self._read_uow_factory() as uow:
            books = await uow.books.get_all()
        self._logger.info("Successfully retrieved %d books.", len(books))
        return books

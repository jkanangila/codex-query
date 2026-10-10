import hashlib
import re
from pathlib import Path
from typing import override

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from codex_query.application.ports.indexing import DocumentParserPort
from codex_query.domain.dtos.parsed_epub import ParsedDocumentDTO
from codex_query.domain.models.document import Book, BookMetaData, Chapter
from codex_query.infrastructure.logging.factory import create_logger


class UnsupportedDocumentError(Exception):
    """Raised when the document file extension or format is not supported."""


class InvalidPath(Exception):
    """Raised when the specified file path does not exist or is invalid."""


logger = create_logger(__name__)


class EbookLibDocumentParser(DocumentParserPort):
    """Parser implementation using EbookLib to extract metadata and chapters
    from EPUB files."""

    @override
    async def read(self, path: Path, series: str | None = None) -> ParsedDocumentDTO:
        """Parse a document file and return its structured representation.

        Args:
            path: Path to the target document file.
            series: Optional series name to associate with the book.

        Returns:
            ParsedDocumentDTO containing book metadata and extracted chapters.

        Raises:
            InvalidPath: If the target path does not exist or is not a file.
            UnsupportedDocumentError: If the document format/extension is unsupported.
        """
        logger.debug("Starting document parse process for path: %s", path)

        if not path.is_file():
            logger.error("Path does not exist or is not a valid file: %s", path)
            raise InvalidPath(f"Path does not exist or is not a file: {path}")

        match path.suffix.lower():
            case ".epub":
                return await self._read_epub(path, series)
            case _:
                logger.error(
                    "Unsupported document extension '%s' for path: %s",
                    path.suffix,
                    path,
                )
                raise UnsupportedDocumentError(f"Unsupported extension: {path.suffix}")

    async def _read_epub(
        self, path: Path, series: str | None = None
    ) -> ParsedDocumentDTO:
        """Extract metadata, chapters, and content hashes from an EPUB file.

        Args:
            path: Path to the EPUB file.
            series: Optional series name to attach to the metadata.

        Returns:
            ParsedDocumentDTO with complete book and chapter details.
        """
        logger.info("Parsing EPUB file: %s", path)

        try:
            stat = path.stat()
            file_hash = _sha256_file(path)
        except Exception:
            logger.exception("Failed to access file attributes or hash path: %s", path)
            raise

        try:
            _book = epub.read_epub(str(path), options={"ignore_ncx": True})
        except Exception:
            logger.exception("EbookLib failed to parse EPUB file: %s", path)
            raise

        title = _metadata(_book, "title") or path.stem
        author = _metadata(_book, "creator")
        logger.debug(
            "Extracted EPUB root metadata - Title: %s, Author: %s", title, author
        )

        chapters: list[Chapter] = []
        document_items = list(_book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        logger.debug("Found %d document items in EPUB archive", len(document_items))

        for order, item in enumerate(document_items):
            href = item.get_name()
            try:
                raw = item.get_content()
                text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
            except Exception:
                logger.exception(
                    (
                        "Error parsing HTML content in "
                        "chapter '%s' (index %d) for path: %s"
                    ),
                    href,
                    order,
                    path,
                )
                continue

            if not text:
                logger.debug(
                    "Skipping empty document item '%s' at index %d", href, order
                )
                continue

            chapter_title = _chapter_title(raw) or f"Chapter {order + 1}"
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            chapters.append(
                Chapter(
                    href=href,
                    title=chapter_title,
                    order=order,
                    content=text,
                    content_hash=content_hash,
                )
            )

        meta = BookMetaData(chapter_count=len(chapters), file_type="epub")
        book = Book(
            path=path,
            title=title,
            series=series,
            author=author,
            file_hash=file_hash,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            meta=meta,
        )

        logger.info(
            "Successfully parsed EPUB '%s' (%d chapters extracted)",
            title,
            len(chapters),
        )
        return ParsedDocumentDTO(book=book, chapters=chapters)


def _metadata(book: epub.EpubBook, key: str) -> str:
    """Fetch Dublin Core metadata entry from an EPUB book object.

    Args:
        book: The EPUB book object.
        key: The Dublin Core metadata key to query.

    Returns:
        The string value of the metadata entry, or an empty string if missing.
    """
    try:
        values = book.get_metadata("DC", key)
        if not values:
            return ""
        value = values[0][0]
        return str(value) if value is not None else ""
    except Exception:
        logger.exception("Failed to retrieve Dublin Core metadata for key: %s", key)
        return ""


def _chapter_title(raw: bytes) -> str:
    """Extract the first HTML heading tag text from raw document bytes.

    Args:
        raw: Raw HTML byte content.

    Returns:
        Extracted heading text or an empty string if no heading tag is found.
    """
    try:
        soup = BeautifulSoup(raw, "html.parser")
        heading = soup.find(re.compile(r"^h[1-6]$"))
        return heading.get_text(" ", strip=True) if heading else ""
    except Exception:
        logger.exception("Failed to extract chapter title from raw HTML content")
        return ""


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hash digest of a file in 1MB streaming chunks.

    Args:
        path: Target file path.

    Returns:
        Hexadecimal SHA-256 hash string.
    """
    logger.debug("Calculating SHA-256 digest for: %s", path)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        logger.exception("Failed to compute SHA-256 hash for path: %s", path)
        raise

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any, cast, override

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from codex_query.application.ports.indexing import DocumentParserPort
from codex_query.domain.dtos.parsed_epub import ParsedDocumentDTO
from codex_query.domain.models.document import (
    Book,
    BookMetadata,
    Chapter,
    DocumentType,
)
from codex_query.domain.value_objects import QueueIndexJobRequest
from codex_query.infrastructure.document_parsing.ebook_lib.epub_metadata import (
    extract_metadata,
    toc_titles,
)
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)

_HEADING_RE = re.compile(r"^h[1-6]$")
_HASH_CHUNK = 1024 * 1024


class UnsupportedDocumentError(Exception):
    """Raised when the document file extension or format is not supported."""


class InvalidPath(Exception):
    """Raised when the specified file path does not exist or is invalid."""


class DocumentParseError(Exception):
    """Raised when a supported document is malformed or unreadable."""


class EbookLibDocumentParser(DocumentParserPort):
    """Parser implementation using EbookLib to extract metadata and chapters
    from EPUB files."""

    @override
    async def read(
        self,
        path: Path,
        title: str | None = None,
        series: str | None = None,
        number: int | None = None,
        request: QueueIndexJobRequest | None = None,
    ) -> ParsedDocumentDTO:
        """Parse a document file and return its structured representation.

        Parsing is blocking (zip + HTML), so it runs in a worker thread.

        Args:
            path: Path to the target document file.
            series: Optional series name overriding the one found in the file.

        Raises:
            InvalidPath: If the target path does not exist or is not a file.
            UnsupportedDocumentError: If the document format is unsupported.
            DocumentParseError: If the document cannot be parsed.
        """
        logger.debug("Starting document parse for path: %s", path)

        if not path.is_file():
            logger.error("Path does not exist or is not a file: %s", path)
            raise InvalidPath(f"Path does not exist or is not a file: {path}")

        match path.suffix.lower():
            case ".epub":
                return await asyncio.to_thread(
                    self._read_epub,
                    path=path,
                    book_title=title,
                    series=series,
                    number=number,
                    request=request,
                )
            case _:
                logger.error("Unsupported extension '%s': %s", path.suffix, path)
                raise UnsupportedDocumentError(f"Unsupported extension: {path.suffix}")

    def _read_epub(
        self,
        path: Path,
        book_title: str | None = None,
        series: str | None = None,
        number: int | None = None,
        request: QueueIndexJobRequest | None = None,
    ) -> ParsedDocumentDTO:
        logger.info("Parsing EPUB file: %s", path)

        stat = path.stat()
        file_hash = _sha256_file(path)

        try:
            # NCX is kept (no ignore_ncx) because EPUB 2 TOCs live there and
            # we use the TOC for chapter titles.
            epub_book = epub.read_epub(str(path))
        except Exception as exc:  # ebooklib raises many unrelated types
            logger.exception("EbookLib failed to parse EPUB: %s", path)
            raise DocumentParseError(f"Cannot parse EPUB {path}: {exc}") from exc

        info = extract_metadata(epub_book)
        title = info.title or path.stem
        logger.debug("EPUB metadata - title: %s, authors: %s", title, info.authors)

        chapters = self._extract_chapters(epub_book, path)

        meta = BookMetadata(
            file_type="epub",
            chapter_count=len(chapters),
            language=request.language
            if request and request.language
            else info.language,
            publisher=request.publisher
            if request and request.publisher
            else info.publisher,
            description=request.description
            if request and request.description
            else info.description,
            isbn=request.isbn if request and request.isbn else info.isbn,
            published_year=request.published_year
            if request and request.published_year
            else info.published_year,
            subjects=request.subjects
            if request and request.subjects
            else info.subjects,
            book_number=number or info.book_number,
            # UNKNOWN is a non-empty string enum, so it is truthy: compare it
            # explicitly or it would always override what the file says.
            document_type=request.document_type
            if request and request.document_type is not DocumentType.UNKNOWN
            else info.document_type,
        )
        book = Book(
            path=path,
            title=book_title or title,
            authors=info.authors,
            series=series or info.series,
            file_hash=file_hash,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            meta=meta,
        )

        logger.info("Parsed EPUB '%s' (%d chapters)", title, len(chapters))
        return ParsedDocumentDTO(book=book, chapters=chapters)

    @staticmethod
    def _extract_chapters(epub_book: epub.EpubBook, path: Path) -> list[Chapter]:
        titles = toc_titles(epub_book)
        chapters: list[Chapter] = []

        for item in _documents_in_reading_order(epub_book):
            href = cast("str", item.get_name())
            try:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                for tag in soup(["script", "style", "head"]):
                    tag.decompose()
                text = soup.get_text(" ", strip=True)
            except Exception:
                logger.exception("Bad HTML in '%s' for path: %s", href, path)
                continue

            if not text:
                logger.debug("Skipping empty document '%s'", href)
                continue

            order = len(chapters)  # contiguous, reading order
            title = (
                titles.get(href)
                or titles.get(href.rsplit("/", 1)[-1])
                or _heading(soup)
                or f"Section {order + 1}"
            )
            chapters.append(
                Chapter(
                    href=href,
                    title=title,
                    order=order,
                    content=text,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
        return chapters


def _documents_in_reading_order(epub_book: epub.EpubBook) -> list[Any]:
    """Spine order (what a reader shows), falling back to manifest order."""
    items: list[Any] = []
    seen: set[str] = set()
    spine = cast("list[Any]", epub_book.spine)  # pyright: ignore[reportUnknownMemberType]
    for entry in spine:
        idref = cast("str", entry[0] if isinstance(entry, tuple) else entry)
        item = epub_book.get_item_with_id(idref)
        if (
            item is not None
            and item.get_type() == ebooklib.ITEM_DOCUMENT
            and idref not in seen
        ):
            seen.add(idref)
            items.append(item)

    if items:
        return items
    return list(epub_book.get_items_of_type(ebooklib.ITEM_DOCUMENT))


def _heading(soup: BeautifulSoup) -> str:
    """Text of the first h1-h6 element, or an empty string."""
    tag = soup.find(_HEADING_RE)
    return tag.get_text(" ", strip=True) if tag else ""


def _sha256_file(path: Path) -> str:
    """SHA-256 of a file, streamed in 1 MB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import override

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from codex_query.domain.models import Book, Chapter
from codex_query.domain.ports import BookReader

logger = logging.getLogger(__name__)


class EpubBookReader(BookReader):
    """Reader implementation for parsing EPUB files into domain model instances."""

    @override
    def read(self, path: Path) -> Book:
        """Parse an EPUB file into a domain Book object with extracted chapters.

        Args:
            path: Path to the EPUB file on disk.

        Returns:
            Book: Domain model containing file metadata, identifiers, and chapters.
        """
        # Fetch file system attributes for modification tracking
        logger.debug("Opening EPUB: %s", path)
        stat = path.stat()
        # Calculate SHA256 checksum of the physical file
        file_hash = _sha256_file(path)
        # Parse EPUB document structure using ebooklib
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        # Extract unique identifier metadata from Dublin Core
        identifier = _metadata(book, "identifier")
        # Use metadata ID or absolute file path as fallback key
        stable_key = identifier or str(path.resolve())
        # Derive a 24-character hexadecimal unique book ID
        book_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:24]
        # Extract title and author metadata
        title = _metadata(book, "title") or path.stem
        author = _metadata(book, "creator")
        chapters: list[Chapter] = []
        # Iterate over HTML/XHTML document items in the EPUB
        for order, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):
            href = item.get_name()
            raw = item.get_content()
            # Strip HTML tags and extract plain text content
            text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
            if not text:
                continue
            # Extract heading title or generate default chapter label
            chapter_title = _chapter_title(raw) or f"Chapter {order + 1}"
            # Compute hash of clean chapter text to detect content changes
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chapters.append(
                Chapter(
                    book_id,
                    href,
                    chapter_title,
                    order,
                    text,
                    content_hash,
                )
            )
        logger.debug(
            "Parsed EPUB: %s title=%r chapters=%d", path.name, title, len(chapters)
        )
        # Construct and return immutable Book domain model
        return Book(
            book_id,
            path,
            title,
            author,
            file_hash,
            stat.st_size,
            stat.st_mtime_ns,
            tuple(chapters),
        )


def _metadata(book: epub.EpubBook, key: str) -> str:
    """Extract a Dublin Core metadata field value from an EPUB book.

    Args:
        book: The parsed EPUB book instance.
        key: The Dublin Core metadata key name.

    Returns:
        str: String value of metadata field if found, otherwise empty string.
    """
    # Fetch list of metadata tuples matching the key
    values = book.get_metadata("DC", key)
    if not values:
        return ""
    # Extract raw value from first tuple entry
    value = values[0][0]
    return str(value) if value is not None else ""


def _chapter_title(raw: bytes) -> str:
    """Extract heading text (h1-h6) from raw HTML document content.

    Args:
        raw: Raw HTML bytes of the chapter document.

    Returns:
        str: Text content of first matching heading tag, or empty string.
    """
    soup = BeautifulSoup(raw, "html.parser")
    # Search for the first heading tag in the document
    heading = soup.find(re.compile(r"^h[1-6]$"))
    return heading.get_text(" ", strip=True) if heading else ""


def _sha256_file(path: Path) -> str:
    """Compute the SHA256 checksum of a file by streaming chunks.

    Args:
        path: Path to file on disk.

    Returns:
        str: Full hexadecimal SHA256 hash string.
    """
    digest = hashlib.sha256()
    # Stream file in 1MB chunks to keep memory usage low
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

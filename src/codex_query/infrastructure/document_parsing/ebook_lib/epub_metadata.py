"""EPUB metadata extraction helpers (internal to the EbookLib adapter)."""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

from bs4 import BeautifulSoup
from ebooklib import epub

from codex_query.domain.models.document import DocumentType

type Attrs = dict[str, str]

_BOOK_NUMBER_RE = re.compile(
    r"(?:\b(?:book|volume|vol)\.?|#)\s*[-.:]?\s*(\d+)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:18|19|20|21)\d{2}\b")
_ISBN_RE = re.compile(r"^(?:97[89]\d{10}|\d{9}[\dX])$")
_WORD_RE = re.compile(r"[a-z]+")

_ARTICLE_WORDS = frozenset({"article", "journal"})
_BOOK_WORDS = frozenset({"book", "novel"})
_ARTICLE_TITLE_MARKERS = ("journal article", "research article")

_LANGUAGE_ALIASES = {
    "eng": "en",
    "fra": "fr",
    "fre": "fr",
    "deu": "de",
    "ger": "de",
    "spa": "es",
    "ita": "it",
    "por": "pt",
    "nld": "nl",
    "dut": "nl",
    "rus": "ru",
    "jpn": "ja",
    "zho": "zh",
    "chi": "zh",
}


@dataclass(frozen=True, slots=True)
class ExtractedMetadata:
    """Descriptive metadata read from the EPUB package document."""

    title: str | None
    authors: tuple[str, ...]
    series: str | None
    series_index: int | None
    language: str | None
    publisher: str | None
    description: str | None
    isbn: str | None
    published_year: int | None
    subjects: tuple[str, ...]
    document_type: DocumentType
    book_number: int | None


# --------------------------------------------------------------------------- #
# Low-level access (ebooklib is untyped, so everything is funnelled through   #
# these two functions and cast once)                                          #
# --------------------------------------------------------------------------- #
def _entries(book: epub.EpubBook, namespace: str, name: str) -> list[tuple[str, Attrs]]:
    try:
        raw = cast(
            "list[tuple[str | None, Attrs | None]]",
            book.get_metadata(namespace, name),  # pyright: ignore[reportUnknownMemberType]
        )
    except KeyError:  # ebooklib raises when the namespace is absent
        return []
    return [(value or "", attrs or {}) for value, attrs in raw]


def _dc(book: epub.EpubBook, name: str) -> list[str]:
    """Non-empty, stripped Dublin Core values."""
    return [value.strip() for value, _ in _entries(book, "DC", name) if value.strip()]


def _opf_meta(book: epub.EpubBook) -> list[tuple[str, Attrs]]:
    """All OPF <meta> elements regardless of how ebooklib namespaced them."""
    metadata = cast(
        "dict[str, dict[str, list[tuple[str | None, Attrs | None]]]]",
        book.metadata,  # pyright: ignore[reportUnknownMemberType]
    )
    return [
        (value or "", attrs or {})
        for entries in metadata.values()
        for value, attrs in entries.get("meta", [])
    ]


def _to_int(raw: str | None) -> int | None:
    try:
        return int(float(raw)) if raw else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Individual fields                                                           #
# --------------------------------------------------------------------------- #
def extract_series(book: epub.EpubBook) -> tuple[str | None, int | None]:
    """Return ``(series, index)`` from Calibre or EPUB 3 collection metadata.

    Fractional indexes (e.g. 1.5 for a novella) are truncated to ints.
    """
    metas = _opf_meta(book)

    # Calibre / EPUB 2: <meta name="calibre:series" content="..."/>
    series: str | None = None
    index: int | None = None
    for _, attrs in metas:
        name = attrs.get("name")
        if name == "calibre:series":
            series = attrs.get("content", "").strip() or series
        elif name == "calibre:series_index":
            index = _to_int(attrs.get("content"))
    if series:
        return series, index

    # EPUB 3: <meta property="belongs-to-collection" id="c1">Name</meta>
    # refined by collection-type and group-position.
    for value, attrs in metas:
        if attrs.get("property") != "belongs-to-collection" or not value.strip():
            continue
        collection_id = attrs.get("id")
        refined = (
            {
                a["property"]: v.strip()
                for v, a in metas
                if a.get("refines") == f"#{collection_id}" and "property" in a
            }
            if collection_id
            else {}
        )
        if refined.get("collection-type", "series") != "series":
            continue
        return value.strip(), _to_int(refined.get("group-position"))

    return None, None


def _extract_book_number(
    title: str | None, series: str | None, series_index: int | None
) -> int | None:
    """Prefer structured series index; fall back to the title or series name."""
    if series_index is not None:
        return series_index
    for candidate in (title, series):
        if candidate and (match := _BOOK_NUMBER_RE.search(candidate)):
            return int(match.group(1))
    return None


def _extract_year(book: epub.EpubBook) -> int | None:
    for value in _dc(book, "date"):
        if match := _YEAR_RE.search(value):
            return int(match.group(0))
    return None


def _extract_isbn(book: epub.EpubBook) -> str | None:
    for value in _dc(book, "identifier"):
        cleaned = re.sub(
            r"[\s-]",
            "",
            value.casefold().removeprefix("urn:isbn:").removeprefix("isbn:"),
        ).upper()
        if _ISBN_RE.match(cleaned):
            return cleaned
    return None


def _extract_description(book: epub.EpubBook) -> str | None:
    values = _dc(book, "description")
    if not values:
        return None
    text = BeautifulSoup(values[0], "html.parser").get_text(" ", strip=True)
    return text or None


def _normalize_language(raw: str) -> str:
    """Normalise ``eng`` / ``en_us`` / ``EN-us`` to ``en`` / ``en-US``."""
    primary, _, region = raw.strip().replace("_", "-").lower().partition("-")
    primary = _LANGUAGE_ALIASES.get(primary, primary)
    return f"{primary}-{region.upper()}" if region else primary


def _extract_document_type(book: epub.EpubBook, title: str | None) -> DocumentType:
    """Whole-word match on dc:type (so "audiobook" is not a "book")."""
    for value in _dc(book, "type"):
        words = set(_WORD_RE.findall(value.casefold()))
        if words & _ARTICLE_WORDS:
            return DocumentType.ARTICLE
        if words & _BOOK_WORDS:
            return DocumentType.BOOK

    lowered = (title or "").casefold()
    if any(marker in lowered for marker in _ARTICLE_TITLE_MARKERS):
        return DocumentType.ARTICLE
    return DocumentType.UNKNOWN


def extract_metadata(book: epub.EpubBook) -> ExtractedMetadata:
    """Read all descriptive metadata from an already-opened EPUB."""
    titles = _dc(book, "title")
    languages = _dc(book, "language")
    publishers = _dc(book, "publisher")

    title = titles[0] if titles else None
    series, series_index = extract_series(book)

    return ExtractedMetadata(
        title=title,
        authors=tuple(dict.fromkeys(_dc(book, "creator"))),
        series=series,
        series_index=series_index,
        language=_normalize_language(languages[0]) if languages else None,
        publisher=publishers[0] if publishers else None,
        description=_extract_description(book),
        isbn=_extract_isbn(book),
        published_year=_extract_year(book),
        subjects=tuple(dict.fromkeys(_dc(book, "subject"))),
        document_type=_extract_document_type(book, title),
        book_number=_extract_book_number(title, series, series_index),
    )


# --------------------------------------------------------------------------- #
# Table of contents                                                           #
# --------------------------------------------------------------------------- #
def _toc_link(node: Any) -> Iterator[tuple[str, str]]:
    href = str(getattr(node, "href", "") or "").split("#", 1)[0]
    title = str(getattr(node, "title", "") or "").strip()
    if href and title:
        yield href, title


def _walk_toc(entries: Sequence[Any]) -> Iterator[tuple[str, str]]:
    for entry in entries:
        if isinstance(entry, tuple):  # (Section, [children])
            section, children = cast("tuple[Any, Sequence[Any]]", entry)
            yield from _toc_link(section)
            yield from _walk_toc(children)
        else:
            yield from _toc_link(entry)


def toc_titles(book: epub.EpubBook) -> dict[str, str]:
    """Map document href (no fragment) -> first TOC title that points to it.

    Each entry is also registered under its basename, because TOC hrefs may
    be relative to the OPF directory while ``item.get_name()`` is not.
    """
    titles: dict[str, str] = {}
    toc = cast("Sequence[Any]", book.toc)  # pyright: ignore[reportUnknownMemberType]
    for href, title in _walk_toc(toc):
        titles.setdefault(href, title)
        titles.setdefault(href.rsplit("/", 1)[-1], title)
    return titles

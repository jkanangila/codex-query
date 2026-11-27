"""Validation and request building for the "add a book" form.

Mirrors ``IndexingViewModel._build_request`` so both front ends accept and
reject the same input.
"""

from __future__ import annotations

import re
from pathlib import Path

from codex_query.domain.models.document import DocumentType
from codex_query.domain.value_objects import QueueIndexJobRequest

_ISBN_RE = re.compile(r"^(?:97[89]\d{10}|\d{9}[\dX])$")
_SUBJECT_SPLIT_RE = re.compile(r"[;,]")

DOCUMENT_TYPE_LABELS: list[tuple[DocumentType, str]] = [
    (DocumentType.UNKNOWN, "Auto-detect"),
    (DocumentType.BOOK, "Book"),
    (DocumentType.ARTICLE, "Article"),
]


def validate_number(text: str) -> str | None:
    """Return an error message, or ``None`` when ``text`` is a valid book #."""
    digits = text.strip()
    if digits and not digits.isdigit():
        return "Book # must be a whole number."
    return None


def validate_year(text: str) -> str | None:
    """Return an error message, or ``None`` for an empty or 4-digit year."""
    year = text.strip()
    if year and not (year.isdigit() and len(year) == 4):
        return "Published year must be a four-digit year."
    return None


def normalize_isbn(text: str) -> str:
    """Strip spaces and dashes and upper-case the check digit."""
    return re.sub(r"[\s-]", "", text).upper()


def validate_isbn(text: str) -> str | None:
    """Return an error message, or ``None`` for an empty or valid ISBN."""
    isbn = normalize_isbn(text)
    if isbn and not _ISBN_RE.match(isbn):
        return "ISBN must have 10 or 13 digits."
    return None


def split_subjects(text: str) -> tuple[str, ...]:
    """Split on ``,`` or ``;``, trim, and drop blanks and duplicates."""
    return tuple(
        dict.fromkeys(
            part.strip() for part in _SUBJECT_SPLIT_RE.split(text) if part.strip()
        )
    )


def build_request(
    path: Path,
    *,
    title: str = "",
    series: str = "",
    number: str = "",
    language: str = "",
    publisher: str = "",
    description: str = "",
    isbn: str = "",
    year: str = "",
    subjects: str = "",
    document_type: DocumentType = DocumentType.UNKNOWN,
) -> QueueIndexJobRequest:
    """Turn raw form text into a request.

    Raises:
        ValueError: With a message fit to show the user.
    """
    for error in (validate_number(number), validate_year(year), validate_isbn(isbn)):
        if error:
            raise ValueError(error)
    digits = number.strip()
    year_text = year.strip()
    return QueueIndexJobRequest(
        title=title.strip() or path.stem,
        source=path,
        series=series.strip() or None,
        number=int(digits) if digits else None,
        language=language.strip() or None,
        publisher=publisher.strip() or None,
        description=description.strip() or None,
        isbn=normalize_isbn(isbn) or None,
        published_year=int(year_text) if year_text else None,
        subjects=split_subjects(subjects),
        document_type=document_type,
    )

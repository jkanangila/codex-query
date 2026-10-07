from collections.abc import Sequence
from dataclasses import dataclass

from codex_query.domain.models.document import Book, Chapter


@dataclass
class ParsedDocumentDTO:
    book: Book
    chapters: Sequence[Chapter]

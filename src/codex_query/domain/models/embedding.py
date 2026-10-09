from enum import StrEnum


class EmbeddingInputType(StrEnum):
    """Some providers (Cohere) embed queries and documents differently."""

    DOCUMENT = "document"
    QUERY = "query"

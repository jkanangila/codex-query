class BookAlreadyExistsError(Exception):
    """Raised when attempting to register a book that already exists in storage."""


class ChapterAlreadyExistsError(Exception):
    """Raised when attempting to register a chapter that already exists in storage."""


class JobNotFoundError(Exception):
    """Raised when an indexing job cannot be found by its unique identifier."""


class MissingChapterIDError(Exception):
    """Raised when an operation requires a chapter ID, but none was provided."""


class MissingBookIDError(Exception):
    """Raised when an operation requires a book ID, but none was provided."""


class EmbeddingMismatchError(ValueError):
    """Raised when embeddings mismatch a book's indexed configuration.

    This error indicates a discrepancy in either the embedding model or dimension
    vector size. Re-index the book after changing the embedding model.
    """


class ProviderError(Exception):
    """Base class for every failure raised by an LLM provider adapter."""


class ProviderConfigurationError(ProviderError):
    """Raised when provider/settings selection cannot work (e.g., missing API key)."""


class ProviderAuthError(ProviderError):
    """Raised when the provider rejects credentials (HTTP 401/403)."""


class ProviderRateLimitError(ProviderError):
    """Raised when the provider throttles the request (HTTP 429)."""

    def __init__(self, detail: str, retry_after: float | None = None) -> None:
        """Initialize rate limit error with detail message and optional retry delay.

        Args:
            detail: Descriptive error message explaining the rate limit failure.
            retry_after: Optional duration in seconds to wait before retrying.
        """
        super().__init__(detail)
        self.retry_after = retry_after


class ProviderRequestError(ProviderError):
    """Raised when provider rejects request itself (HTTP 4xx or in-stream error)."""

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        """Initialize request error with detail message and optional HTTP status code.

        Args:
            detail: Descriptive error message explaining the request failure.
            status_code: Optional HTTP status code returned by the provider.
        """
        super().__init__(detail)
        self.status_code = status_code


class ProviderUnavailableError(ProviderError):
    """Raised on network failures, timeouts, or HTTP 5xx errors (worth retrying)."""


class ProviderResponseError(ProviderError):
    """Raised when provider responds but payload is malformed or unexpected."""


class SecureStorageUnavailableError(Exception):
    """Raised when the platform secure storage cannot be used.

    On Linux this means the Secret Service dependencies (libsecret and a running
    keyring such as gnome-keyring or KWallet) are missing or not reachable.
    """


class IndexingError(Exception): ...


class CheckpointMismatchError(IndexingError): ...


class EmbeddingCountError(IndexingError): ...

from dataclasses import dataclass
from typing import Literal

type Endpoint = Literal["chat", "embedding"]


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """Outcome of a connection test, ready to show in the settings UI."""

    ok: bool
    message: str
    latency_ms: float | None = None
    # Embedding tests only: size of the returned vectors. Worth showing, since
    # changing it means the existing index has to be rebuilt.
    embedding_dimension: int | None = None

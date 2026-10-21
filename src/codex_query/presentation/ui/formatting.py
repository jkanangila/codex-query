"""Pure functions that turn domain values into display strings.

No Flet imports here, so they are trivially unit-testable and decoupled from
the UI presentation layer.
"""

from codex_query.domain.models.connection import ConnectionTestResult
from codex_query.domain.models.document import Book
from codex_query.domain.models.job import IndexingJob, JobStatus

NO_SCOPE_TITLE: str = "Pick a book from the library"


def fmt_eta(seconds: float | None) -> str:
    """Format an estimated time of arrival (ETA) as a human-readable string.

    Args:
        seconds: The remaining time in seconds, or None if unknown.

    Returns:
        A formatted string representing the remaining time
        (e.g., "~1 h 5 min left", "~1 min left", "~42s left"), or an empty
        string if seconds is None.
    """
    if seconds is None:
        return ""
    hours, remainder = divmod(max(int(seconds), 0), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"~{hours} h {minutes} min left"
    return f"~{minutes} min left" if minutes else f"~{secs}s left"


def book_subtitle(book: Book) -> str:
    """Generate the subtitle text for a book's row in the library.

    Args:
        book: The Book instance to generate the subtitle for.

    Returns:
        A string describing the book's number and chunk count,
        or just the chunk count if no book number is available.
    """
    if book.meta.book_number:
        return f"Book {book.meta.book_number} · {book.meta.chunks:,} chunks"
    return f"{book.meta.chunks:,} chunks"


def scope_title(selected: list[Book]) -> str:
    """Generate a chat header title based on the currently selected books.

    Args:
        selected: A list of selected Book instances.

    Returns:
        A title string describing the active selection scope: the book's own
        title for one book, the series name when every selected book belongs to
        the same series, or a plain count otherwise.
    """
    if not selected:
        return NO_SCOPE_TITLE
    if len(selected) == 1:
        return selected[0].title
    series = {book.series for book in selected}
    if len(series) == 1 and (name := next(iter(series))):
        return f"{name} series · {len(selected)} books"
    return f"{len(selected)} books selected"


def job_status_text(job: IndexingJob) -> str:
    """Generate a descriptive one-line status string for an indexing job."""
    match job.status:
        case JobStatus.RUNNING:
            return f"Embedding with {job.stage.value.lower()} stage active"
        case JobStatus.QUEUED:
            return "Queued"
        case JobStatus.PAUSED:
            return f"Paused · resumes from chunk {job.checkpoint:,}"
        case JobStatus.FAILED:
            return f"Failed: {job.error}"
        case _:
            return ""


def job_counter_text(job: IndexingJob) -> str:
    """Generate a progress counter string combining chunks and estimated time.

    Args:
        job: The IndexingJob instance being tracked.
        eta: The estimated remaining time in seconds, or None if unknown.

    Returns:
        A formatted progress string (e.g., "Chunk 400 / 1,200 · ~1 min left"),
        or an empty string if the job total is not yet known.
    """
    if not job.total:
        return ""
    counter = f"Chunk {job.done:,} / {job.total:,}"
    remaining = fmt_eta(job.eta)
    return f"{counter} · {remaining}" if remaining else counter


def build_test_result_text(result: ConnectionTestResult | None) -> str:
    """Describe the outcome of a connection test.

    Returns an empty string when no test has been run (or its result went stale
    because the endpoint was edited).
    """
    if result is None:
        return ""
    if result.ok:
        return f"✓ {result.latency_ms:.0f} ms [{result.message}]"
    return f"✗ {result.message}" if result.message else "✗ Unreachable"

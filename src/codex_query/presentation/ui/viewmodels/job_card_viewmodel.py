"""Presentation view models for managing and displaying individual indexing jobs."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from codex_query.application.facade import UseCases
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.job import IndexingJob, JobStatus, Stage
from codex_query.presentation.ui.formatting import (
    job_counter_text,
    job_status_text,
)
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject


@dataclass(frozen=True, slots=True)
class StageIndicator:
    """Represent how one pipeline stage should be drawn in the stepper.

    Attributes:
        label: The name or value of the pipeline stage.
        reached: Whether the stage is current or already passed (highlighted).
        emphasized: Whether this is the active stage being worked on right now (bold).
    """

    label: str
    reached: bool
    """Current stage or one already passed: draw highlighted."""
    emphasized: bool
    """The stage being worked on right now: draw bold."""


class JobCardViewModel(ObservableObject):
    """View model representing an individual indexing job card in the UI.

    Manages job states, display formatting, asynchronous commands (toggle, cancel),
    and observer notifications.
    """

    def __init__(
        self,
        job: IndexingJob,
        book_title: str,
        use_cases: UseCases,
        on_discard: Callable[["JobCardViewModel"], None],
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the job card view model.

        Args:
            job: The indexing job domain model.
            book_title: The title of the book being indexed.
            use_cases: The application use cases facade.
            on_discard: Callback triggered when the job is discarded/cancelled.
            logger_factory: Factory used to create a contextual logger.
        """
        super().__init__()
        self._job = job
        self._book_title = book_title
        self._use_cases = use_cases
        self._on_discard = on_discard
        self._logger = logger_factory.create(__name__)
        self._logger.info(
            "Initialized JobCardViewModel for job %s (book: %s)",
            self._job.id,
            self._book_title,
        )

    # ── display state ─────────────────────────────────────────────────────
    @property
    def job_id(self) -> UUID:
        """Return the unique identifier of the job."""
        return self._job.id

    @property
    def title(self) -> str:
        """Return the title of the book associated with the job."""
        return self._book_title

    @property
    def is_running(self) -> bool:
        """Check if the indexing job is currently running."""
        return self._job.status == JobStatus.RUNNING

    @property
    def status_text(self) -> str:
        """Return the human-readable status text for the job."""
        return job_status_text(self._job)

    @property
    def counter_text(self) -> str:
        """Return the formatted progress counter text for the job."""
        return job_counter_text(self._job)

    @property
    def progress(self) -> float | None:
        """Return the progress fraction or None if indeterminable."""
        job = self._job
        if job.total:
            return job.fraction
        return None if self.is_running else 0.0

    @property
    def stages(self) -> list[StageIndicator]:
        """Return a list of stage indicators representing the pipeline progress."""
        current = list(Stage).index(self._job.stage)
        return [
            StageIndicator(
                label=stage.value,
                reached=i <= current,
                emphasized=i == current and self.is_running,
            )
            for i, stage in enumerate(Stage)
        ]

    @property
    def toggle_label(self) -> str:
        """Return the action label for the toggle button."""
        return "Pause" if self.is_running else "Resume"

    # ── commands ──────────────────────────────────────────────────────────
    async def toggle(self) -> None:
        """Toggle the job state between running and paused."""
        if self.is_running:
            self._logger.info("Pausing indexing job %s", self.job_id)
            await self._use_cases.indexing.pause(self.job_id)
        else:
            self._logger.info("Resuming indexing job %s", self.job_id)
            await self._use_cases.indexing.resume(self.job_id)

    async def cancel(self) -> None:
        """Cancel the indexing job and notify observers to discard."""
        self._logger.info("Canceling indexing job %s", self.job_id)
        await self._use_cases.indexing.cancel(self.job_id)
        self._on_discard(self)

    # ── updates (called by the owner) ─────────────────────────────────────
    def refresh(self) -> None:
        """The underlying job changed; tell the view to redraw."""
        self._logger.debug("Refreshing view model state for job %s", self.job_id)
        self.notify_changed()

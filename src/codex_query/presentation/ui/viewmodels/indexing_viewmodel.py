"""Presentation view model for managing indexing jobs and file selection form state."""

from pathlib import Path
from uuid import UUID, uuid4

from codex_query.application.facade import UseCases
from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.domain.models.document import DocumentType
from codex_query.domain.models.job import IndexingJob
from codex_query.domain.value_objects import QueueIndexJobRequest
from codex_query.application.observable.job_events import JobEvents
from codex_query.presentation.ui.viewmodels.events.ui_events import UiEvents
from codex_query.presentation.ui.viewmodels.job_card_viewmodel import (
    JobCardViewModel,
)
from codex_query.presentation.ui.viewmodels.events.observable import (
    ObservableObject,
    Signal,
)

NO_FILE_TEXT = "No file chosen"


class IndexingViewModel(ObservableObject):
    """View model for the indexing view, handling form inputs and active job cards.

    Manages book metadata fields, file selection state, background job restoration,
    and event subscriptions for job progress updates and completion.
    """

    def __init__(
        self,
        use_cases: UseCases,
        job_events: JobEvents,
        ui_events: UiEvents,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initialize the IndexingViewModel.

        Args:
            use_cases: The application use cases facade.
            job_events: Event emitter for job-related actions and state changes.
            ui_events: Event emitter for general UI notifications and toasts.
            logger_factory: Factory used to create a contextual logger.
        """
        super().__init__()
        self._use_cases = use_cases
        self._job_events = job_events
        self._ui_events = ui_events
        self._logger_factory = logger_factory
        self._logger = logger_factory.create(__name__)

        # ── internal states ───────────────────────────────────────────────────
        self._cards: list[JobCardViewModel] = []
        self._path: Path | None = None
        self._file_name = ""

        # ── form fields ───────────────────────────────────────────────────────
        self.title = ""
        self.series = ""
        self.number_text = ""
        # -- Descriptive metadata --
        # TODO: implement those metadata under a collapsed field grouping called
        # Advanced. the user can fill-in the info or it will be alternatively extracted
        # from the file meta if available.
        self.language = ""
        self.publisher = ""
        self.description = ""
        self.isbn = ""
        self.published_year_str = ""
        self.subjects: tuple[str, ...] = ()
        self.document_type: DocumentType = DocumentType.UNKNOWN

        # ── subscriptions and events ──────────────────────────────────────────
        self.job_completed: Signal[IndexingJob] = Signal()
        job_events.on_job_update.subscribe(self._on_job_updated)
        job_events.on_job_done.subscribe(self._on_job_done)

        self._logger.info("Initialized IndexingViewModel")

    # ── state ─────────────────────────────────────────────────────────────
    @property
    def jobs(self) -> list[JobCardViewModel]:
        """Return a copy of the list of current job card view models."""
        return list(self._cards)

    @property
    def file_label(self) -> str:
        """Return the display name of the selected file or default fallback text."""
        return self._file_name or NO_FILE_TEXT

    # ── commands ──────────────────────────────────────────────────────────
    async def restore(self) -> None:
        """Restore and display interrupted indexing jobs from persistence."""
        self._logger.info("Restoring interrupted indexing jobs...")
        jobs = await self._use_cases.indexing.recover_interrupted_jobs()
        for job, title in jobs:
            if title is not None:
                self._logger.debug("Restoring job card for job %s", job.id)
                self._add_card(job, title)
        self._logger.info("Finished restoring interrupted indexing jobs")

    def choose_file(self, path: Path, display_name: str) -> None:
        """Handle file selection, updating internal paths and default book title.

        Args:
            path: The filesystem path to the selected file.
            display_name: The human-readable file name to display.
        """
        self._logger.info("File chosen: %s (path: %s)", display_name, path)
        self._path = path
        self._file_name = display_name
        if not self.title.strip():
            self.title = Path(display_name).stem
            self._logger.debug("Auto-populated title from file stem: %s", self.title)
        self.notify_changed()

    def start(self) -> None:
        """Queue and start a new indexing job using the current form data."""
        digits = self.number_text.strip()
        try:
            assert self._path is not None
            request = QueueIndexJobRequest(
                title=self.title,
                source=self._path,
                series=self.series,
                number=int(digits) if digits.isdigit() else None,
            )
        except AssertionError:
            self._logger.warning("Attempted to start indexing with no file selected")
            self._ui_events.toast.emit("Please choose a file!")
            return

        job = IndexingJob(id=uuid4(), book_id=-1)
        self._logger.info(
            "Starting new indexing job %s for title '%s'", job.id, self.title
        )

        self._add_card(job, self.title)
        self._use_cases.indexing.start(job, request)
        self._reset_form()

    # ── internals ─────────────────────────────────────────────────────────
    def _reset_form(self) -> None:
        """Reset all form fields and file selection state back to defaults."""
        self._logger.debug("Resetting indexing form state")
        self._path = None
        self._file_name = ""
        self.title = ""
        self.series = ""
        self.number_text = ""
        self.notify_changed()

    def _add_card(self, job: IndexingJob, title: str) -> None:
        """Create and add a new JobCardViewModel to the active list."""
        self._logger.debug("Adding job card view model for job %s", job.id)
        self._cards.append(
            JobCardViewModel(
                job,
                title,
                self._use_cases,
                self._remove_card,
                self._logger_factory,
            )
        )
        self.notify_changed()

    def _remove_card(self, card: JobCardViewModel) -> None:
        """Remove a specified JobCardViewModel from the active list."""
        if card in self._cards:
            self._logger.debug("Removing job card view model for job %s", card.job_id)
            self._cards.remove(card)
            self.notify_changed()

    def _card_for(self, job_id: UUID) -> JobCardViewModel | None:
        """Find and return the JobCardViewModel matching the given job ID."""
        return next((c for c in self._cards if c.job_id == job_id), None)

    def _on_job_updated(self, job: IndexingJob) -> None:
        """Handle job update events by refreshing the corresponding card view model."""
        self._logger.debug("Received job update event for job %s", job.id)
        if card := self._card_for(job.id):
            card.refresh()

    def _on_job_done(self, job: IndexingJob) -> None:
        """Handle job completion events by removing the card and emitting signals."""
        self._logger.info("Job %s marked as done; removing card", job.id)
        if card := self._card_for(job.id):
            self._remove_card(card)
        self.job_completed.emit(job)

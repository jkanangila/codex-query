from codex_query.di.bootstrap import CompositionRoot
from codex_query.domain.models.job import IndexingJob
from codex_query.presentation.ui.viewmodels.events.observable import ObservableObject
from codex_query.presentation.ui.viewmodels.events.ui_events import UiEvents
from codex_query.presentation.ui.viewmodels.indexing_viewmodel import IndexingViewModel
from codex_query.presentation.ui.viewmodels.navigation import Tab
from codex_query.presentation.ui.viewmodels.settings_viewmodel import SettingsViewModel


class AppViewModel(ObservableObject):
    def __init__(self, composition: CompositionRoot) -> None:
        super().__init__()
        self._logger = composition.logger_factory.create(__name__)
        self.composition = composition
        self.events = UiEvents()
        self._tab = Tab.LIBRARY

        # Placeholders (instances, so the attributes are typed) until the real
        # Library / Chat / Index ViewModels exist.
        self.library = ObservableObject()
        self.chat = ObservableObject()
        self.indexing = IndexingViewModel(
            composition.use_cases,
            composition.job_events,
            self.events,
            composition.logger_factory,
        )
        self.settings = SettingsViewModel(
            self.composition.use_cases.settings,
            self.events,
            composition.logger_factory,
            on_reindex=self.indexing.reindex,
        )

        # TODO: uncomment when library view is implemented
        # self.indexing.job_completed.subscribe(self._on_job_completed)

    @property
    def tab(self) -> Tab:
        return self._tab

    # ── Navigation ────────────────────────────────────────────────────────
    def navigate(self, tab: Tab) -> None:
        self._tab = tab
        self.notify_changed()

    def go_to_index(self) -> None:
        self.navigate(Tab.INDEXING)

    # ── coordination ──────────────────────────────────────────────────────
    # TODO: implement together with chat and library views
    def select_books(self, ids: list[str]) -> None:
        raise NotImplementedError

    # TODO: implement when library is ready
    def _on_job_completed(self, job: IndexingJob) -> None:
        raise NotImplementedError

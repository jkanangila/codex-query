from codex_query.di.bootstrap import CompositionRoot
from codex_query.presentation.ui.viewmodels.events import UiEvents
from codex_query.presentation.ui.viewmodels.navigation import Tab
from codex_query.presentation.ui.viewmodels.observable import ObservableObject
from codex_query.presentation.ui.viewmodels.settings_viewmodel import SettingsViewModel


class AppViewModel(ObservableObject):
    def __init__(self, composition: CompositionRoot) -> None:
        super().__init__()
        self._composition = composition
        self.events = UiEvents()
        self._tab = Tab.LIBRARY

        self.library = object
        self.chat = object
        self.index = object
        self.settings = SettingsViewModel(
            self._composition.use_cases.settings, self.events
        )

        # TODO: add subscriptions

    @property
    def tab(self) -> Tab:
        return self._tab

    # ── Navigation ────────────────────────────────────────────────────────
    def navigate(self, tab: Tab) -> None:
        self._tab = tab
        self.notify_changed()

    def go_to_index(self) -> None:
        self.navigate(Tab.INDEX)

    # TODO: add select_books and _on_job_completed

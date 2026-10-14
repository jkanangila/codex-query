from enum import StrEnum

import flet as ft

from codex_query.domain.value_objects import PendingEmbeddingChange, Source
from codex_query.presentation.ui.viewmodels.app_viewmodel import AppViewModel
from codex_query.presentation.ui.viewmodels.navigation import Tab
from codex_query.presentation.ui.views.chat.chat_view import ChatView
from codex_query.presentation.ui.views.index.index_view import IndexView
from codex_query.presentation.ui.views.library.library_view import LibraryView
from codex_query.presentation.ui.views.settings.components.embedding_dialog import (
    build_embedding_dialog,
)
from codex_query.presentation.ui.views.settings.settings_view import SettingsView

COMPACT_MAX_WIDTH = 600
MEDIUM_MAX_WIDTH = 1000
LIBRARY_PANE_WIDTH = 300
DEFAULT_WIDTH = 800  # used until Flet reports the real page width

# (icon, label) for each Tab, in Tab order.
DESTINATIONS = [
    (ft.Icons.LIBRARY_BOOKS_OUTLINED, "Library"),
    (ft.Icons.CHAT_BUBBLE_OUTLINE, "Ask"),
    (ft.Icons.UPLOAD_FILE, "Index"),
    (ft.Icons.SETTINGS_OUTLINED, "Settings"),
]


class SizeClass(StrEnum):
    COMPACT = "compact"
    MEDIUM = "medium"
    EXPANDED = "expanded"


class CodexApp:
    """The shell *view*: builds the screens, lays them out for the current width, and
    carries out the UI requests (toasts, dialogs) that ViewModels emit.

    All state and navigation logic live in :class:`AppViewModel`; this class only
    decides how the current ``vm.tab`` is drawn at the current window size.
    """

    def __init__(self, page: ft.Page, vm: AppViewModel) -> None:
        self.page = page
        self._vm = vm
        self._size_class: SizeClass | None = None
        self._nav_bar: ft.NavigationBar | None = None
        self._rail: ft.NavigationRail | None = None
        self.body = ft.Container(expand=True)

        # ── ViewModels ────────────────────────────────────────────────────────
        self.library = LibraryView()
        self.chat = ChatView()
        self.index = IndexView()
        self.settings = SettingsView(vm.settings)

        # ── Subscriptions ─────────────────────────────────────────────────────
        vm.subscribe(self._show_tab)
        vm.events.toast.subscribe(self._toast)
        vm.events.source_requested.subscribe(self._show_source)
        vm.events.embedding_reindex_requested.subscribe(self._show_stale_books)

        # ──────────────────────────────────────────────────────────────────────
        page.on_resize = self._on_resize
        self._build_layout()

    # ── Layout ────────────────────────────────────────────────────────────
    def _current_size_class(self) -> SizeClass:
        width = self.page.width or DEFAULT_WIDTH
        match width:
            case w if w < COMPACT_MAX_WIDTH:
                return SizeClass.COMPACT
            case w if w < MEDIUM_MAX_WIDTH:
                return SizeClass.MEDIUM
            case _:
                return SizeClass.EXPANDED

    def _on_resize(self, _e: ft.PageResizeEvent) -> None:
        if self._current_size_class() != self._size_class:
            self._build_layout()

    def _build_layout(self) -> None:
        self._size_class = self._current_size_class()
        self.page.clean()
        self._nav_bar = self._rail = None

        match self._size_class:
            case s if s == SizeClass.COMPACT:
                layout = self._compact_layout()
            case _:
                layout = self._wide_layout(
                    with_sources=self._size_class == SizeClass.EXPANDED
                )
        self.page.add(ft.SafeArea(content=layout, expand=True))
        self._show_tab()

    def _compact_layout(self) -> ft.Control:
        bar = ft.NavigationBar(
            selected_index=self._vm.tab,
            destinations=[
                ft.NavigationBarDestination(icon=i, label=t) for i, t in DESTINATIONS
            ],
        )

        def on_bar(_e: ft.Event[ft.NavigationBar]) -> None:
            self._vm.navigate(Tab(bar.selected_index))

        bar.on_change = on_bar
        self._nav_bar = bar
        return ft.Column([self.body, bar], expand=True, spacing=0)

    def _wide_layout(self, with_sources: bool) -> ft.Control:
        rail = ft.NavigationRail(
            # The rail omits "Library" (it has its own pane), so indices shift by one.
            selected_index=max(self._vm.tab, Tab.CHAT) - 1,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=72,
            destinations=[
                ft.NavigationRailDestination(icon=i, label=t)
                for i, t in DESTINATIONS[1:]
            ],
        )

        def on_rail(_e: ft.Event[ft.NavigationRail]) -> None:
            self._vm.navigate(Tab(rail.selected_index or 0 + 1))

        rail.on_change = on_rail
        self._rail = rail

        row: list[ft.Control] = [
            # Navigation
            rail,
            ft.VerticalDivider(width=1),
            # Library
            ft.Container(content=self.library.root, width=LIBRARY_PANE_WIDTH),
            ft.VerticalDivider(width=1),
            # Body
            self.body,
        ]
        if with_sources:
            row.append(self.chat.sources.root)
        return ft.Row(row, expand=True, spacing=0)

    def _show_tab(self) -> None:
        """Mount the screen for ``vm.tab`` and sync the navigation controls."""
        views = [self.library, self.chat, self.index, self.settings]
        # On wide layouts the library is always visible, so "Library" is never the body.
        tab = (
            self._vm.tab
            if self._size_class == SizeClass.COMPACT
            else max(self._vm.tab, Tab.CHAT)
        )
        self.body.content = views[tab].root
        self.chat.sources.root.visible = tab == Tab.CHAT
        if self._nav_bar:
            self._nav_bar.selected_index = tab
        if self._rail:
            self._rail.selected_index = tab - 1
        self.page.update()

    # ── UI requests from ViewModels ───────────────────────────────────────
    def _toast(self, message: str) -> None:
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message)))

    def _show_source(self, source: Source) -> None:
        self.page.show_dialog(
            ft.AlertDialog(title=ft.Text(source.label), content=ft.Text(source.text))
        )

    def _show_stale_books(self, pending: PendingEmbeddingChange | None) -> None:
        if pending is not None:
            self.page.show_dialog(build_embedding_dialog(pending))

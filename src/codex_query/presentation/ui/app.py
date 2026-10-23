from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import flet as ft

from codex_query.domain.value_objects import Source
from codex_query.presentation.ui.viewmodels.app_viewmodel import AppViewModel
from codex_query.presentation.ui.viewmodels.events.ui_events import (
    EmbeddingChangeRequest,
)
from codex_query.presentation.ui.viewmodels.navigation import Tab
from codex_query.presentation.ui.views.chat.chat_view import ChatView
from codex_query.presentation.ui.views.indexing.indexing_view import IndexingView
from codex_query.presentation.ui.views.library.library_view import LibraryView
from codex_query.presentation.ui.views.settings.components.embedding_dialog import (
    build_embedding_dialog,
)
from codex_query.presentation.ui.views.settings.settings_view import SettingsView

COMPACT_MAX_WIDTH = 600
MEDIUM_MAX_WIDTH = 840  # Material 3: the "expanded" window class starts at 840dp
SOURCES_MIN_WIDTH = 1200  # below this there is no room for a sources side panel
LIBRARY_PANE_WIDTH = 300
DEFAULT_WIDTH = 800  # used until Flet reports the real page width

# (icon, label) for each Tab.
DESTINATIONS: dict[Tab, tuple[ft.IconData, str]] = {
    Tab.LIBRARY: (ft.Icons.LIBRARY_BOOKS_OUTLINED, "Library"),
    Tab.CHAT: (ft.Icons.CHAT_BUBBLE_OUTLINE, "Ask"),
    Tab.INDEXING: (ft.Icons.UPLOAD_FILE, "Index"),
    Tab.SETTINGS: (ft.Icons.SETTINGS_OUTLINED, "Settings"),
}


class SizeClass(StrEnum):
    COMPACT = "compact"
    MEDIUM = "medium"
    EXPANDED = "expanded"


class _Screen(Protocol):
    """Anything that can be shown as the body of the shell."""

    @property
    def root(self) -> ft.Control: ...


@dataclass(frozen=True, slots=True)
class _Layout:
    """How the shell is arranged at the current window width."""

    size_class: SizeClass
    with_sources: bool

    @property
    def library_is_pane(self) -> bool:
        """Whether the library is a permanent pane rather than a destination."""
        return self.size_class is SizeClass.EXPANDED

    @property
    def nav_tabs(self) -> tuple[Tab, ...]:
        """The tabs offered by the navigation bar / rail, in display order."""
        if self.library_is_pane:
            return tuple(tab for tab in Tab if tab is not Tab.LIBRARY)
        return tuple(Tab)


class CodexApp:
    """The shell *view*: builds the screens, lays them out for the current width, and
    carries out the UI requests (toasts, dialogs) that ViewModels emit.

    All state and navigation logic live in :class:`AppViewModel`; this class only
    decides how the current ``vm.tab`` is drawn at the current window size.
    """

    def __init__(self, page: ft.Page, vm: AppViewModel) -> None:
        self.page = page
        self._vm = vm
        self._layout = self._current_layout()
        self._nav_bar: ft.NavigationBar | None = None
        self._rail: ft.NavigationRail | None = None
        self.body = ft.Container(expand=True)

        # ── Views ─────────────────────────────────────────────────────────────
        self.library = LibraryView(vm.library, vm.composition.logger_factory)
        self.chat = ChatView()
        self.indexing = IndexingView(vm.indexing, vm.composition.logger_factory)
        self.settings = SettingsView(vm.settings, vm.composition.logger_factory)
        self._screens: dict[Tab, _Screen] = {
            Tab.LIBRARY: self.library,
            Tab.CHAT: self.chat,
            Tab.INDEXING: self.indexing,
            Tab.SETTINGS: self.settings,
        }

        # ── Subscriptions ─────────────────────────────────────────────────────
        vm.subscribe(self._show_tab)
        vm.events.toast.subscribe(self._toast)
        vm.events.source_requested.subscribe(self._show_source)
        vm.events.embedding_reindex_requested.subscribe(self._show_embedding_dialog)

        # ──────────────────────────────────────────────────────────────────────
        page.on_resize = self._on_resize
        self._build_layout()

    # ── Layout ────────────────────────────────────────────────────────────
    def _current_layout(self) -> _Layout:
        width = self.page.width or DEFAULT_WIDTH
        if width < COMPACT_MAX_WIDTH:
            size_class = SizeClass.COMPACT
        elif width < MEDIUM_MAX_WIDTH:
            size_class = SizeClass.MEDIUM
        else:
            size_class = SizeClass.EXPANDED
        return _Layout(size_class, with_sources=width >= SOURCES_MIN_WIDTH)

    def _on_resize(self, _e: ft.PageResizeEvent) -> None:
        if self._current_layout() != self._layout:
            self._build_layout()

    def _build_layout(self) -> None:
        self._layout = self._current_layout()
        self.page.clean()
        self._nav_bar = self._rail = None
        self.settings.set_compact(self._layout.size_class is SizeClass.COMPACT)

        if self._layout.size_class is SizeClass.COMPACT:
            layout = self._compact_layout()
        else:
            layout = self._wide_layout()
        self.page.add(ft.SafeArea(content=layout, expand=True))
        self._show_tab()

    def _effective_tab(self) -> Tab:
        """The tab to show: ``vm.tab``, unless this layout has no such destination."""
        # On expanded layouts the library is always visible as a pane, so it is
        # never the body; show the chat instead.
        tab = self._vm.tab
        return tab if tab in self._layout.nav_tabs else Tab.CHAT

    def _compact_layout(self) -> ft.Control:
        nav_tabs = self._layout.nav_tabs
        bar = ft.NavigationBar(
            selected_index=nav_tabs.index(self._effective_tab()),
            destinations=[
                ft.NavigationBarDestination(icon=icon, label=label)
                for icon, label in (DESTINATIONS[tab] for tab in nav_tabs)
            ],
        )

        def on_bar(_e: ft.Event[ft.NavigationBar]) -> None:
            self._vm.navigate(nav_tabs[bar.selected_index or 0])

        bar.on_change = on_bar
        self._nav_bar = bar
        return ft.Column([self.body, bar], expand=True, spacing=0)

    def _wide_layout(self) -> ft.Control:
        nav_tabs = self._layout.nav_tabs
        rail = ft.NavigationRail(
            selected_index=nav_tabs.index(self._effective_tab()),
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=72,
            destinations=[
                ft.NavigationRailDestination(icon=icon, label=label)
                for icon, label in (DESTINATIONS[tab] for tab in nav_tabs)
            ],
        )

        def on_rail(_e: ft.Event[ft.NavigationRail]) -> None:
            self._vm.navigate(nav_tabs[rail.selected_index or 0])

        rail.on_change = on_rail
        self._rail = rail

        # Navigation, then (expanded only) the library pane, then the body.
        row: list[ft.Control] = [rail, ft.VerticalDivider(width=1)]
        if self._layout.library_is_pane:
            row += [
                ft.Container(content=self.library.root, width=LIBRARY_PANE_WIDTH),
                ft.VerticalDivider(width=1),
            ]
        row.append(self.body)
        # TODO: below SOURCES_MIN_WIDTH the sources need another home (inline under
        # the answer, or a bottom sheet) once ChatView exists.
        if self._layout.with_sources:
            row.append(self.chat.sources.root)
        return ft.Row(row, expand=True, spacing=0)

    def _show_tab(self) -> None:
        """Mount the screen for ``vm.tab`` and sync the navigation controls."""
        tab = self._effective_tab()
        index = self._layout.nav_tabs.index(tab)
        self.body.content = self._screens[tab].root
        self.chat.sources.root.visible = tab == Tab.CHAT
        if self._nav_bar:
            self._nav_bar.selected_index = index
        if self._rail:
            self._rail.selected_index = index
        self.page.update()

    # ── UI requests from ViewModels ───────────────────────────────────────
    def _toast(self, message: str) -> None:
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message)))

    def _show_source(self, source: Source) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(source.label),
                content=ft.Text(source.text),
                scrollable=True,
            )
        )

    def _show_embedding_dialog(self, request: EmbeddingChangeRequest) -> None:
        self.page.show_dialog(build_embedding_dialog(self.page, request))

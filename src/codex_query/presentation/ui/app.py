"""Main application shell view for the Codex Query Flet UI.

This module provides the `CodexApp` class, which handles dynamic responsive layout
arrangements (compact, medium, expanded), screen routing, navigation bars/rails,
and global UI requests such as toasts, source excerpts, and embedding dialogs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import flet as ft

from codex_query.domain.models.rag import SourceRef
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
    """Enumeration representing responsive window size classifications."""

    COMPACT = "compact"
    MEDIUM = "medium"
    EXPANDED = "expanded"


class _Screen(Protocol):
    """Protocol for anything that can be shown as the body of the shell."""

    @property
    def root(self) -> ft.Control:
        """The root control of the screen.

        Returns:
            The root `ft.Control` instance.
        """
        ...


@dataclass(frozen=True, slots=True)
class _Layout:
    """Represents how the shell is arranged at the current window width.

    Attributes:
        size_class: The current window size category.
        with_sources: Whether there is enough room for the sources side panel.
    """

    size_class: SizeClass
    with_sources: bool

    @property
    def library_is_pane(self) -> bool:
        """Whether the library is a permanent pane rather than a destination.

        Returns:
            True if the library is displayed as a pane, False otherwise.
        """
        return self.size_class is SizeClass.EXPANDED

    @property
    def nav_tabs(self) -> tuple[Tab, ...]:
        """Tabs offered by the navigation bar/rail in display order.

        Returns:
            A tuple of available navigation `Tab` values.
        """
        if self.library_is_pane:
            return tuple(tab for tab in Tab if tab is not Tab.LIBRARY)
        return tuple(Tab)


class CodexApp:
    """The shell view: builds screens, lays them out, and carries out UI requests.

    All state and navigation logic live in :class:`AppViewModel`; this class only
    decides how the current ``vm.tab`` is drawn at the current window size.

    Attributes:
        page: The root Flet page instance.
        body: Container hosting the active screen content.
        library: The library view instance.
        chat: The chat view instance.
        indexing: The indexing view instance.
        settings: The settings view instance.
        _logger: Contextual component logger instance.
        _vm: The central application view model.
        _layout: Current window layout configuration parameters.
        _nav_bar: Flet navigation bar for compact screens, if active.
        _rail: Flet navigation rail for wide screens, if active.
        _screens: Mapping of navigation tabs to their respective view components.
    """

    def __init__(self, page: ft.Page, vm: AppViewModel) -> None:
        """Initialize the CodexApp shell view, views, and event subscriptions.

        Args:
            page: The root Flet page instance.
            vm: The central application view model.
        """
        self.page = page
        self._logger = vm.composition.logger_factory.create(__name__)

        self._vm = vm
        self._layout = self._current_layout()
        self._nav_bar: ft.NavigationBar | None = None
        self._rail: ft.NavigationRail | None = None
        self.body = ft.Container(expand=True)

        self._logger.info("Initializing application views...")
        # ── Views ─────────────────────────────────────────────────────────────
        self.library = LibraryView(vm.library, vm.composition.logger_factory)
        self.chat = ChatView(vm.chat, vm.composition.logger_factory)
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
        self._logger.info("CodexApp shell layout successfully built.")

    # ── Layout ────────────────────────────────────────────────────────────
    def _current_layout(self) -> _Layout:
        """Determine the current layout configuration based on window width.

        Returns:
            The evaluated layout parameters including size class and sources visibility.
        """
        width = self.page.width or DEFAULT_WIDTH
        if width < COMPACT_MAX_WIDTH:
            size_class = SizeClass.COMPACT
        elif width < MEDIUM_MAX_WIDTH:
            size_class = SizeClass.MEDIUM
        else:
            size_class = SizeClass.EXPANDED
        return _Layout(size_class, with_sources=width >= SOURCES_MIN_WIDTH)

    def _on_resize(self, _e: ft.PageResizeEvent) -> None:
        """Handle page resize events by rebuilding layout if size class changes.

        Args:
            _e: The Flet page resize event payload.
        """
        new_layout = self._current_layout()
        if new_layout != self._layout:
            self._logger.info(
                f"Window resized. Layout changing from {self._layout.size_class} "
                f"to {new_layout.size_class}."
            )
            self._build_layout()

    def _build_layout(self) -> None:
        """Construct the responsive UI layout according to the current window size."""
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
        """Get the tab to show.

        Returns:
            The active tab, or falls back to Chat if the current layout does not
            support displaying the library destination as a tab.
        """
        tab = self._vm.tab
        return tab if tab in self._layout.nav_tabs else Tab.CHAT

    def _compact_layout(self) -> ft.Control:
        """Build the compact navigation layout for smaller mobile/narrow screens.

        Returns:
            The root control for the compact layout.
        """
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
        """Build the wide navigation layout using a navigation rail and side panes.

        Returns:
            The root control for the wide layout.
        """
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
        if self._layout.with_sources:
            row.append(self.chat.sources.root)
        return ft.Row(row, expand=True, spacing=0)

    def _show_tab(self) -> None:
        """Mount the screen for the active tab and synchronize navigation controls."""
        tab = self._effective_tab()
        self._logger.debug(f"Displaying tab view: {tab}")
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
        """Display a transient toast message via a SnackBar.

        Args:
            message: The text message to display.
        """
        self._logger.info(f"Showing toast notification: '{message}'")
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message)))

    def _show_source(self, source: SourceRef) -> None:
        """Display an AlertDialog showing source reference details and excerpts.

        Args:
            source: The source reference object to display.
        """
        self._logger.info(f"Showing source reference dialog: '{source.label}'")
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(source.label),
                content=ft.Text(source.excerpt),
                scrollable=True,
            )
        )

    def _show_embedding_dialog(self, request: EmbeddingChangeRequest) -> None:
        """Display the embedding configuration dialog.

        Args:
            request: The embedding change request parameters.
        """
        self._logger.info("Opening embedding change dialog.")
        self.page.show_dialog(build_embedding_dialog(self.page, request))

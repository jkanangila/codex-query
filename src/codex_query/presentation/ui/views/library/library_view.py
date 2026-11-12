"""Library view module for rendering the library interface using Flet.

Provides the LibraryView class which constructs and updates the UI components
for the library screen, including search, book lists, series groupings, and
user interactions.
"""

import flet as ft

from codex_query.application.ports.logger import LoggerFactoryPort
from codex_query.presentation.ui.utils.flet_helpers import bind, safe_update
from codex_query.presentation.ui.viewmodels.library_viewmodel import (
    BookItem,
    LibraryViewModel,
)
from codex_query.presentation.ui.views.library.components.cover import cover

type _Signature = tuple[
    tuple[tuple[str, tuple[tuple[int, str, str], ...]], ...],  # series
    tuple[tuple[int, str, str], ...],  # standalone
    bool,  # is_empty
]


class LibraryView:
    """Represents the Flet-based view for the library interface.

    Attributes:
        search: Text field input for searching books.
        list: ListView control displaying book series and standalone books.
        root: Root container holding the complete library layout.
        _vm: The associated LibraryViewModel instance.
        _logger: Contextual component logger instance.
        _tiles: Mapping of book IDs to their corresponding ListTile controls.
        _signature: Cached content signature to optimize re-renders.
    """

    def __init__(
        self,
        vm: LibraryViewModel,
        logger_factory: LoggerFactoryPort,
    ) -> None:
        """Initializes the LibraryView.

        Args:
            vm: The library view model instance.
            logger_factory: Factory to create the module logger.
        """
        self._vm = vm
        self._logger = logger_factory.create(__name__)

        self._tiles: dict[int, ft.ListTile] = {}
        self._signature: _Signature | None = None

        self.search = ft.TextField(
            hint_text="Search books",
            dense=True,
            on_change=self._on_search,
        )
        self.list = ft.ListView(expand=True, spacing=2)
        self.root = ft.Container(
            padding=12,
            expand=True,
            content=ft.Column(
                expand=True,
                spacing=8,
                controls=[
                    ft.Text(
                        "Library",
                        theme_style=ft.TextThemeStyle.HEADLINE_SMALL,
                    ),
                    self.search,
                    self.list,
                    ft.Button(
                        content="Add book",
                        icon=ft.Icons.ADD,
                        on_click=bind(self._vm.add_book),
                    ),
                ],
            ),
        )
        self._vm.subscribe(self.render)
        self.render()
        self._logger.debug("LibraryView initialized.")

    def _on_search(self, _e: ft.Event[ft.TextField]) -> None:
        """Handles search input changes by updating the view model query.

        Args:
            _e: The Flet text field change event payload.
        """
        query_val = self.search.value or ""
        self._logger.debug("Search query changed to: %r", query_val)
        self._vm.query = query_val

    def render(self) -> None:
        """Renders the current library content and updates the UI list."""
        self._logger.debug("Rendering LibraryView content.")

        content = self._vm.content
        items = [i for s in content.series for i in s.items] + list(content.standalone)

        # Everything except `selected` decides whether the rows must be rebuilt.
        signature: _Signature = (
            tuple(
                (s.name, tuple((i.id, i.title, i.subtitle) for i in s.items))
                for s in content.series
            ),
            tuple((i.id, i.title, i.subtitle) for i in content.standalone),
            content.is_empty,
        )

        if signature == self._signature:
            # Selection-only change: mutate the existing tiles in place.
            for item in items:
                tile = self._tiles[item.id]
                tile.selected = item.selected
                safe_update(tile)
            return

        self._signature = signature
        self._tiles = {}
        rows: list[ft.Control] = []

        for section in content.series:
            rows.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(
                            f"Series · {section.name}",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                )
            )
            rows.extend(self._title(item) for item in section.items)

        if content.standalone:
            rows.append(
                ft.Text("Standalone", size=12, weight=ft.FontWeight.BOLD),
            )
            rows.extend(self._title(item) for item in content.standalone)

        if content.is_empty:
            rows.append(ft.Text("No books yet. Add one to get started."))

        self.list.controls = rows
        safe_update(self.list)
        self._logger.debug(
            "LibraryView rendered successfully with %d control rows.",
            len(rows),
        )

    def _title(self, item: BookItem) -> ft.ListTile:
        """Creates and registers a list tile control for a book item.

        Args:
            item: The book item data structure containing display details.

        Returns:
            A configured Flet `ListTile` instance representing the book row.
        """
        tile = ft.ListTile(
            leading=cover(item.title),
            title=ft.Text(item.title, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            subtitle=ft.Text(item.subtitle),
            dense=True,
            selected=item.selected,
            on_click=bind(self._vm.select_book, item.id),
        )
        self._tiles[item.id] = tile
        return tile

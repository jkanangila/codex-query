import flet as ft

from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    StaleBook,
)
from codex_query.presentation.ui.viewmodels.events.ui_events import (
    EmbeddingChangeRequest,
)


def build_embedding_dialog(
    page: ft.Page, request: EmbeddingChangeRequest
) -> ft.AlertDialog:
    """Ask the user to confirm a change that forces books to be re-indexed.

    Both buttons close the dialog themselves; the dialog is modal and would
    otherwise stay open.
    """

    def cancel(_e: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()
        request.cancel()

    async def confirm(_e: ft.Event[ft.Button]) -> None:
        page.pop_dialog()
        await request.confirm()

    return ft.AlertDialog(
        modal=True,
        scrollable=True,
        title=ft.Text("Re-index books?"),
        content=ft.Column(
            tight=True,
            spacing=4,
            controls=[
                ft.Text(
                    "Changing the embedding model or provider means these books "
                    "must be re-indexed before you can ask questions about them. "
                    "Re-indexing starts now and runs in the background:"
                ),
                ft.Container(height=4),
                *_book_rows(request.stale_books),
            ],
        ),
        actions=[
            ft.TextButton("Cancel", on_click=cancel),
            ft.Button("Change and re-index", on_click=confirm),
        ],
    )


def _book_rows(stale_books: list[StaleBook]) -> list[ft.Control]:
    """One row per book, grouped under a bold heading per series.

    Plain ``Text`` controls (not Markdown) so titles containing ``*``, ``_`` or
    ``[`` are shown literally.
    """
    series_groups: dict[str, list[str]] = {}
    standalone_titles: list[str] = []
    for book in stale_books:
        if book.series:
            series_groups.setdefault(book.series, []).append(book.title)
        else:
            standalone_titles.append(book.title)

    rows: list[ft.Control] = []
    for series_name, titles in series_groups.items():
        rows.append(ft.Text(series_name, weight=ft.FontWeight.BOLD))
        rows.extend(
            ft.Container(
                content=ft.Text(f"• {title}"),
                padding=ft.Padding.only(left=16),
            )
            for title in titles
        )
    rows.extend(ft.Text(f"• {title}") for title in standalone_titles)
    return rows

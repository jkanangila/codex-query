from collections import defaultdict

import flet as ft

from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    StaleBook,
)
from codex_query.presentation.ui.viewmodels.settings_viewmodel import (
    PendingEmbeddingChange,
)


def build_embedding_dialog(pending: PendingEmbeddingChange) -> ft.AlertDialog:
    content = _build_dialog_content(pending.stale_books)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Re-index books?"),
        content=ft.Markdown(
            content,
            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        ),
        actions=[
            ft.TextButton("Cancel", on_click=pending.cancel_embedding_change),
            ft.Button("Change anyway", on_click=pending.confirm_embedding_change),
        ],
    )
    return dialog


def _build_dialog_content(stale_books: list[StaleBook]) -> str:
    standalone_books = []
    series_groups = defaultdict(list)

    # Group books by series or categorize as standalone
    for book in stale_books:
        if book.series:
            series_groups[book.series].append(book.title)
        else:
            standalone_books.append(book.title)

    markdown_lines = []

    # Format series and their books
    for series_name, titles in series_groups.items():
        markdown_lines.append(f"- {series_name}")
        for title in titles:
            markdown_lines.append(f"  * {title}")

    # Format standalone books
    for title in standalone_books:
        markdown_lines.append(f"- {title}")

    return "\n".join(markdown_lines)

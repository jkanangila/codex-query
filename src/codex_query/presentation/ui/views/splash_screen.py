import flet as ft

from codex_query.presentation.ui.utils.set_page_alignment import set_page_alignment


class SplashScreen:
    def __init__(self, page: ft.Page) -> None:
        loading_text = ft.Text("Loading, please wait...", size=20)
        progress_ring = ft.ProgressRing()

        layout = ft.Column(
            controls=[progress_ring, loading_text],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        set_page_alignment(page, "center")
        page.add(layout)

import flet as ft


class SplashScreen(ft.Column):
    def __init__(self) -> None:
        loading_text = ft.Text("Loading, please wait...", size=20)
        progress_ring = ft.ProgressRing()

        super().__init__(
            controls=[progress_ring, loading_text],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

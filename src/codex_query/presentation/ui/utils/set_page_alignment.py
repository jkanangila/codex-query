from typing import Literal

import flet as ft

Align = Literal["center", "start"]


def set_page_alignment(page: ft.Page, align: Align) -> None:
    match align:
        case "center":
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        case "start":
            page.vertical_alignment = ft.MainAxisAlignment.START
            page.horizontal_alignment = ft.CrossAxisAlignment.START

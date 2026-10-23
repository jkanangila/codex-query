"""Placeholder book cover."""

import flet as ft

# Muted colours; a title always maps to the same one so covers are stable.
PALETTE = ["#2f5d50", "#8a4b3a", "#3c4f7a", "#7a6a2f", "#5b3f7a"]


def cover(title: str) -> ft.Container:
    """A small coloured tile showing the title's first letter."""
    color = PALETTE[sum(map(ord, title)) % len(PALETTE)]
    return ft.Container(
        content=ft.Text(title[:1].upper(), color="white", weight=ft.FontWeight.BOLD),
        width=34,
        height=46,
        bgcolor=color,
        border_radius=4,
        alignment=ft.Alignment(0, 0),
    )

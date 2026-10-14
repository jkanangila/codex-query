"""Page-level configuration (title, padding, color scheme)."""

import flet as ft

SEED_COLOR = "teal"


def configure_page(page: ft.Page) -> None:
    """Apply Codex-Query's title and Material 3 theme
    (follows the system light/dark mode)."""
    page.title = "Folio"
    page.padding = 0  # the shell manages its own spacing
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.theme = ft.Theme(color_scheme_seed=SEED_COLOR)
    page.dark_theme = ft.Theme(color_scheme_seed=SEED_COLOR)

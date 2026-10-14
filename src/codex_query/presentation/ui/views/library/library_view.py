from flet import Text, TextThemeStyle


class LibraryView:
    def __init__(self) -> None:
        self.root = Text("Library View", theme_style=TextThemeStyle.DISPLAY_LARGE)

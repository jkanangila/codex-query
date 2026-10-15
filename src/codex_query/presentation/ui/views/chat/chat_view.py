from flet import Text, TextThemeStyle


class ChatSource:
    def __init__(self) -> None:
        self.root = Text("Sources", theme_style=TextThemeStyle.HEADLINE_SMALL)


class ChatView:
    def __init__(self) -> None:
        self.root = Text("Chat View", theme_style=TextThemeStyle.HEADLINE_SMALL)
        self.sources = ChatSource()

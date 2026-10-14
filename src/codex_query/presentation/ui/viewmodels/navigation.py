"""Top-level destinations of the app."""

from enum import IntEnum


class Tab(IntEnum):
    """The screens reachable from the navigation bar / rail."""

    LIBRARY = 0
    CHAT = 1
    INDEX = 2
    SETTINGS = 3

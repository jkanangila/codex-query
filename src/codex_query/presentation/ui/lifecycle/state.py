"""Application lifecycle state definitions."""

from enum import StrEnum, auto


class ApplicationState(StrEnum):
    """States traversed by the desktop application's lifecycle."""

    NEW = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()

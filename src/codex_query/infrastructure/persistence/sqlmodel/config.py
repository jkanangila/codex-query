import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    timeout: float = 30.0
    db_engine_echo: bool = False
    session_expire_on_commit = False

    @property
    def app_name(self) -> str:
        return os.getenv("APP_NAME", "codex_query")

    @property
    def db_path(self) -> Path:
        base = os.getenv("FLET_APP_STORAGE_DATA", user_data_dir(self.app_name))
        root = Path(base)
        path = root / "db"
        path.mkdir(parents=True, exist_ok=True)

        return path / "codex.db"

    @property
    def sync_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def async_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"


db_config = DatabaseConfig()

from dataclasses import dataclass
from pathlib import Path

from codex_query.infrastructure.paths import AppPaths

_IN_BATCH = 500


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """Configuration settings and URL resolvers for database connections."""

    timeout: float = 30.0
    db_engine_echo: bool = False
    session_expire_on_commit: bool = False

    @property
    def app_name(self) -> str:
        """Return application name identifier.

        Returns:
            str: Application name string.
        """
        return AppPaths.APP_NAME

    @property
    def db_dir(self) -> Path:
        """Resolve directory path where database file resides.

        Returns:
            Path: Absolute path to the database parent directory.
        """
        return AppPaths.app_storage_data_dir() / "db"

    @property
    def db_path(self) -> Path:
        """Resolve full filesystem path to database SQLite file.

        Returns:
            Path: Absolute path to database file.
        """
        return self.db_dir / "codex.db"

    @property
    def sync_url(self) -> str:
        """Construct synchronous SQLite connection URL.

        Returns:
            str: Synchronous SQLAlchemy database URL.
        """
        return f"sqlite:///{self.db_path}"

    @property
    def async_url(self) -> str:
        """Construct asynchronous SQLite connection URL using aiosqlite.

        Returns:
            str: Asynchronous SQLAlchemy database URL.
        """
        return f"sqlite+aiosqlite:///{self.db_path}"

    def ensure_directories(self) -> None:
        """Create database parent directories if they do not exist."""
        self.db_dir.mkdir(parents=True, exist_ok=True)


db_config = DatabaseConfig()
db_config.ensure_directories()

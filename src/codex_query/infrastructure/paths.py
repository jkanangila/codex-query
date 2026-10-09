import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir


# TODO: wire into logger and databases
class AppPaths:
    """Provides path resolution using Flet environment variables with fallbacks."""

    APP_NAME: str = "codex_query"

    @staticmethod
    def _get_path(env_key: str, fallback_factory: Callable[[], str | Path]) -> Path:
        """Resolve a directory path from an environment variable or fallback factory.

        Args:
            env_key: Environment variable name to query.
            fallback_factory: Callable producing a fallback directory path.

        Returns:
            Path: Resolved Path instance.
        """
        val = os.getenv(env_key)
        return Path(val) if val else Path(fallback_factory())

    @classmethod
    def app_storage_data_dir(cls) -> Path:
        """Directory for persistent app data (FLET_APP_STORAGE_DATA).

        Returns:
            Path: Absolute directory path for persistent application storage.
        """
        return cls._get_path(
            "FLET_APP_STORAGE_DATA",
            lambda: user_data_dir(appname=cls.APP_NAME),
        )

    @classmethod
    def app_cache_dir(cls) -> Path:
        """Directory for cache files (FLET_APP_STORAGE_CACHE).

        Returns:
            Path: Absolute directory path for application cache files.
        """
        return cls._get_path(
            "FLET_APP_STORAGE_CACHE",
            lambda: user_cache_dir(appname=cls.APP_NAME),
        )

    @classmethod
    def app_temp_dir(cls) -> Path:
        """Directory for temporary files (FLET_APP_STORAGE_TEMP).

        Returns:
            Path: Absolute directory path for application temporary files.
        """
        return cls._get_path(
            "FLET_APP_STORAGE_TEMP",
            tempfile.gettempdir,
        )

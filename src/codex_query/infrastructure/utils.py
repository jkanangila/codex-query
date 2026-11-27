from dotenv import load_dotenv

from codex_query.infrastructure.paths import AppPaths


def load_env() -> None:
    env_file = AppPaths.app_storage_data_dir() / ".env"
    if env_file.is_file():
        # Existing process environment variables intentionally take precedence.
        load_dotenv(env_file, override=False)

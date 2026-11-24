"""Programmatic runner for applying Alembic database migrations."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


def run_migrations() -> None:
    """Apply database migrations to the latest revision."""
    script_location = Path(__file__).resolve().parent / "migrations"

    if not script_location.is_dir():
        raise FileNotFoundError(
            f"Alembic migration directory not found: {script_location}"
        )

    logger.debug("Running Alembic migrations from %s", script_location)

    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))

    try:
        command.upgrade(cfg, "head")
    except Exception:
        logger.exception("Failed to run Alembic migrations to head")
        raise

    logger.info("Alembic migrations upgraded to head")

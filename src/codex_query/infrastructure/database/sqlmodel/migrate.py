"""Programmatic runner for applying Alembic database migrations."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


def run_migrations() -> None:
    """Apply database migrations to the latest revision."""
    script_location = Path(__file__).resolve().parent / "migrations"

    if not script_location.is_dir():
        raise FileNotFoundError(
            f"Alembic migration directory not found: {script_location}"
        )

    cfg = Config()
    cfg.set_main_option(
        "script_location",
        str(script_location).replace("%", "%%"),
    )
    cfg.set_main_option("sourceless", "true")

    logger.info("Applying database migrations from %s", script_location)

    try:
        script = ScriptDirectory.from_config(cfg)

        revisions = list(script.walk_revisions())
        heads = script.get_heads()

        if not revisions:
            raise RuntimeError(f"No Alembic revisions discovered in {script_location}")

        if not heads:
            raise RuntimeError(
                f"No Alembic migration heads discovered in {script_location}"
            )

        if len(heads) != 1:
            raise RuntimeError(
                f"Multiple Alembic migration heads detected: {heads}. "
                "A merge migration is required."
            )

        logger.info(
            "Discovered %d migration revisions.",
            len(revisions),
        )
        logger.info("Migration head: %s", heads[0])

        command.upgrade(cfg, "head")

    except Exception:
        logger.exception("Database migration failed.")
        raise

    logger.info("Database migrations successfully applied.")

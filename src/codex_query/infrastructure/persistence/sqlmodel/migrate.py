from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations() -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(cfg, "head")

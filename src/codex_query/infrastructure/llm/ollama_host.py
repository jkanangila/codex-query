"""Reach a Windows-hosted Ollama from inside WSL2 (opt-in)."""

import os
import subprocess
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)

_LOOPBACK = frozenset({"127.0.0.1", "localhost"})
_OPT_IN_ENV = "CODEX_OLLAMA_USE_WSL_HOST"


@cache
def _is_wsl() -> bool:
    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "microsoft" in version.lower()


@cache
def _wsl_host_ip() -> str | None:
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError) as err:
        logger.warning("Could not read WSL default route: %s", err)
        return None
    tokens = out.split()
    try:
        return tokens[tokens.index("via") + 1]
    except (ValueError, IndexError):
        logger.warning("No gateway found in 'ip route show default' output")
        return None


def resolve_ollama_url(url: str) -> str:
    """Swap a loopback host for the WSL gateway IP, only when opted in."""
    parts = urlsplit(url)
    if (
        parts.hostname not in _LOOPBACK
        or os.environ.get(_OPT_IN_ENV) != "1"
        or not _is_wsl()
    ):
        return url
    host_ip = _wsl_host_ip()
    if host_ip is None:
        return url
    netloc = f"{host_ip}:{parts.port}" if parts.port else host_ip
    logger.info("Using WSL host %s for Ollama", host_ip)
    return urlunsplit(parts._replace(netloc=netloc))

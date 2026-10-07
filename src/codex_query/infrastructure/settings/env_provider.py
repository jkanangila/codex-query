import os
import platform
import subprocess
from functools import cache, cached_property
from typing import override

from codex_query.domain.models.provider import PROVIDER_CONFIGS, LLMProvider
from codex_query.domain.models.settings import ProviderUrlResolver
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class EnvironmentUrlResolver(ProviderUrlResolver):
    """Resolves base URLs for LLM providers based on environment configuration.

    Handles environment-specific adjustments, such as detecting WSL (Windows
    Subsystem for Linux) to map host loopback addresses appropriately for Ollama.
    """

    @override
    def get_default_url(self, provider: LLMProvider) -> str:
        """Resolves the default base URL for the given LLM provider.

        Args:
            provider: The target LLM provider.

        Returns:
            The resolved base URL string.
        """
        logger.debug("Resolving default URL for provider: %s", provider)
        if provider == LLMProvider.OLLAMA:
            url = self._get_ollama_base_url
            logger.info("Resolved default URL for %s: %s", provider, url)
            return url

        config = PROVIDER_CONFIGS.get(provider)
        url = config.get("base_url", "") if config else ""
        logger.info("Resolved default URL for %s: %s", provider, url)
        return url

    @cached_property
    def _get_ollama_base_url(self) -> str:
        """Computes and caches the default Ollama base URL.

        If running within WSL, attempts to replace loopback references
        (localhost / 127.0.0.1) with the WSL host IP address.

        Returns:
            The resolved base URL string for Ollama.
        """
        default_config = PROVIDER_CONFIGS.get(LLMProvider.OLLAMA, {})
        base_url = default_config.get("base_url", "http://localhost:11434")

        if self._is_wsl():
            logger.debug("WSL environment detected for Ollama URL resolution.")
            host_ip = self._get_wsl_host_ip()
            if host_ip:
                resolved_url = base_url.replace("localhost", host_ip).replace(
                    "127.0.0.1", host_ip
                )
                logger.info(
                    "Replaced loopback with WSL host IP (%s): %s",
                    host_ip,
                    resolved_url,
                )
                return resolved_url
            logger.warning(
                "WSL detected, but host IP could not be resolved. "
                "Falling back to default URL."
            )

        return base_url

    @staticmethod
    def _get_wsl_host_ip() -> str | None:
        """Parses the default gateway IP in WSL without external shell pipelines.

        Returns:
            The default gateway IP string if successfully retrieved, otherwise None.
        """
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True,
                text=True,
                check=True,
            )
            # Output format: "default via 172.25.160.1 dev eth0 proto kernel"
            tokens = result.stdout.split()
            if "via" in tokens:
                host_ip = tokens[tokens.index("via") + 1]
                logger.debug("Extracted WSL host IP: %s", host_ip)
                return host_ip
            logger.warning(
                "Could not find 'via' token in 'ip route show default' output."
            )
        except (
            subprocess.SubprocessError,
            ValueError,
            IndexError,
            FileNotFoundError,
        ) as err:
            logger.exception("Failed to extract WSL host IP: %s", err)
        return None

    @staticmethod
    @cache
    def _is_wsl() -> bool:
        """Determines whether the current execution environment is WSL.

        Checks environment variables (WSL_DISTRO_NAME, WSL_INTEROP) and
        procfs (/proc/version).

        Returns:
            True if running inside WSL, False otherwise.
        """
        if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
            logger.debug("WSL detected via environment variables.")
            return True

        if platform.system() == "Linux":
            try:
                with open("/proc/version", encoding="utf-8", errors="ignore") as f:
                    is_wsl = "microsoft" in f.read().lower()
                    if is_wsl:
                        logger.debug("WSL detected via /proc/version.")
                    return is_wsl
            except OSError as err:
                logger.exception(
                    "Failed to read /proc/version during WSL check: %s", err
                )
                return False

        return False

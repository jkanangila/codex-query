import os
from typing import Literal

from codex_query.domain.models.provider import (
    PROVIDER_CONFIGS,
    AuthType,
    LLMProvider,
    ProviderConfig,
)
from codex_query.domain.models.settings import Settings
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class RAGEndpointResolver:
    """Resolves dynamic API URLs, endpoints, and authentication headers for
    LLM and Embedding requests.

    Attributes:
        settings (Settings): Application settings containing configuration overrides.
        provider (LLMProvider): The target provider name/enum derived from settings.
        config (ProviderConfig): Provider specification containing base URLs,
        endpoints, and auth schemas.
    """

    def __init__(self, settings: Settings) -> None:
        """Initializes the endpoint resolver for the specified LLM provider.

        Args:
            settings (Settings): Application settings containing provider, API keys,
            and URL overrides.

        Raises:
            ValueError: If the specified provider is not configured in
            `PROVIDER_CONFIGS`.
        """
        self.settings = settings
        self.provider = settings.provider

        logger.debug(
            "Initializing RAGEndpointResolver for provider: '%s'", self.provider
        )

        config = PROVIDER_CONFIGS.get(self.provider)
        if not config:
            err_msg = f"Unsupported or unconfigured provider: '{self.provider}'"
            logger.error("RAGEndpointResolver initialization failed: %s", err_msg)
            raise ValueError(err_msg)

        self.config: ProviderConfig = config
        logger.info(
            "RAGEndpointResolver initialized successfully for provider: '%s'",
            self.provider,
        )

    @property
    def api_key(self) -> str:
        """Resolves the API key for the configured provider.

        Checks explicit `settings.api_key` first, falling back to environment variable
        `{PROVIDER}_API_KEY` (e.g., `OPENAI_API_KEY`).

        Returns:
            str: Resolved API key or an empty string if unconfigured.
        """
        if self.settings.api_key:
            logger.debug(
                "Resolved API key from application settings for provider '%s'",
                self.provider,
            )
            return self.settings.api_key

        env_var_name = f"{str(self.provider).upper()}_API_KEY"
        key = os.getenv(env_var_name, "")

        if key:
            logger.debug(
                "Resolved API key from environment variable '%s' for provider '%s'",
                env_var_name,
                self.provider,
            )
        else:
            logger.warning(
                (
                    "No API key found in settings or "
                    "environment variable '%s' for provider '%s'"
                ),
                env_var_name,
                self.provider,
            )

        return key

    @property
    def base_url(self) -> str:
        """Resolves the base URL for API calls.

        Prefers custom `settings.base_url` over default provider configuration base URL.

        Returns:
            str: Normalized base URL with trailing slashes removed.
        """
        if self.settings.base_url:
            resolved_url = self.settings.base_url.rstrip("/")
            logger.debug(
                "Using custom base URL from settings for provider '%s': %s",
                self.provider,
                resolved_url,
            )
            return resolved_url

        default_url = self.config.get("base_url", "").rstrip("/")
        logger.debug(
            "Using default base URL for provider '%s': %s", self.provider, default_url
        )
        return default_url

    def get_headers(self) -> dict[str, str]:
        """Constructs HTTP request headers including standard Content-Type
        and auth headers.

        Returns:
            dict[str, str]: Map of HTTP header names and their corresponding values.
        """
        logger.debug("Constructing request headers for provider '%s'", self.provider)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        auth_cfg = self.config.get("auth", {})

        header_name = auth_cfg.get("header_name")
        auth_type = auth_cfg.get("type")
        key = self.api_key

        if key and header_name:
            if auth_type == AuthType.BEARER_TOKEN:
                headers[header_name] = f"Bearer {key}"
                logger.debug(
                    "Added Bearer token header '%s' for provider '%s'",
                    header_name,
                    self.provider,
                )
            elif auth_type == AuthType.CUSTOM_HEADER:
                headers[header_name] = key
                logger.debug(
                    "Added custom header '%s' for provider '%s'",
                    header_name,
                    self.provider,
                )
            else:
                logger.warning(
                    "Unrecognized or missing AuthType '%s' for provider '%s'",
                    auth_type,
                    self.provider,
                )
        elif not key:
            logger.warning(
                "API key is empty; proceeding without authentication "
                "header for provider '%s'",
                self.provider,
            )
        elif not header_name:
            logger.warning(
                "Auth header name not configured in "
                "provider settings for provider '%s'",
                self.provider,
            )

        if self.provider == LLMProvider.ANTHROPIC:
            headers["anthropic-version"] = "2023-06-01"
            logger.debug(
                "Added required Anthropic version header "
                "('anthropic-version: 2023-06-01')"
            )

        return headers

    def get_url(self, endpoint_type: Literal["chat", "embeddings"]) -> str:
        """Constructs the full target URL for the specified endpoint type.

        Args:
            endpoint_type (Literal["chat", "embeddings"]): Target endpoint category.

        Returns:
            str: Fully qualified URL.

        Raises:
            ValueError: If the requested endpoint type is unsupported by the provider.
        """
        logger.debug(
            "Resolving endpoint URL for provider '%s' and type '%s'",
            self.provider,
            endpoint_type,
        )

        endpoints = self.config.get("endpoints", {})
        path = endpoints.get(endpoint_type, "")

        if not path:
            err_msg = (
                f"Provider '{self.provider}' "
                "does not support '{endpoint_type}' natively."
            )
            logger.error("URL resolution failed: %s", err_msg)
            raise ValueError(err_msg)

        full_url = f"{self.base_url}{path}"
        logger.info(
            "Resolved URL for provider '%s' [%s]: %s",
            self.provider,
            endpoint_type,
            full_url,
        )
        return full_url

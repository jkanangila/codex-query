from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from codex_query.application.config import Settings
from codex_query.infrastructure.rag.utils import get_ollama_base_url


def _get_installed_ollama_models(base_url: str) -> set[str]:
    """Fetch installed model tags and base names from Ollama REST API.

    Normalizes tags so that both exact names (e.g. 'nomic-embed-text:latest')
    and untagged base names (e.g. 'nomic-embed-text') are matchable.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    req = Request(url=url, headers={"User-Agent": "pytest-ollama-check"})

    try:
        with urlopen(req, timeout=5.0) as response:
            if response.status != 200:
                pytest.fail(f"Ollama API returned status code: {response.status}")

            data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            models_list: list[dict[str, Any]] = data.get("models", [])

            installed_tags: set[str] = set()
            for item in models_list:
                for key in ("name", "model"):
                    if tag := item.get(key):
                        tag_str = str(tag)
                        installed_tags.add(tag_str)
                        # If tag ends with :latest or contains a tag, also add base name
                        if ":" in tag_str:
                            base_name, suffix = tag_str.split(":", 1)
                            installed_tags.add(base_name)
                            if suffix == "latest":
                                installed_tags.add(base_name)

            return installed_tags

    except URLError as err:
        pytest.fail(f"Failed to connect to Ollama server at {base_url}: {err.reason}")


def test_configured_models_are_present_in_ollama(tmp_path: Path) -> None:
    """Test that configured LLM and Embedding models are present in Ollama."""
    resolved_ollama_host = get_ollama_base_url()

    settings = Settings.from_data_dir(
        data_dir=tmp_path / "test_data",
        ollama_host=resolved_ollama_host,
    )

    installed_models = _get_installed_ollama_models(settings.ollama_host)

    assert settings.generation_model in installed_models, (
        f"LLM model '{settings.generation_model}' is missing from Ollama instance at "
        f"{settings.ollama_host}. Available models: {sorted(installed_models)}"
    )

    assert settings.embedding_model in installed_models, (
        f"Embedding model '{
            settings.embedding_model
        }' is missing from Ollama instance at "
        f"{settings.ollama_host}. Available models: {sorted(installed_models)}"
    )

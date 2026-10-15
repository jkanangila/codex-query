"""Titles and subtitles for the settings screen.

Every entry is a `SettingText`, passed to a tile component as its ``text``:

    TextFieldTile(text=TEXT.chat_base_url, value=vm.chat_base_url, on_change=...)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SettingText:
    """Title and helper text for one setting."""

    title: str
    subtitle: str


@dataclass(frozen=True, slots=True)
class SectionText:
    """Section header labels."""

    chat: str = "Chat service"
    embedding: str = "Embedding service"
    tuning: str = "Tuning"


def _default_tuning() -> dict[str, SettingText]:
    return {
        "temperature": SettingText(
            "Temperature",
            "Lower is focused and consistent, higher is more creative and varied.",
        ),
        "max_tokens": SettingText(
            "Max answer tokens",
            "Upper limit on answer length. Longer answers use more tokens.",
        ),
        "top_k": SettingText(
            "Passages retrieved (top-k)",
            "How many book passages are sent with each question. More gives "
            "richer context but costs more tokens.",
        ),
        "num_ctx": SettingText(
            "Context window",
            "How much text the model can read at once: question, passages and "
            "answer together. Larger values need more memory.",
        ),
        "chunk_size": SettingText(
            "Chunk size (new books only)",
            "Size of each text piece when indexing. Only applies to books you "
            "add afterwards; existing books keep their current size.",
        ),
    }


@dataclass(frozen=True, slots=True)
class SettingsText:
    """All user-facing copy for the settings screen, keyed by view-model property."""

    sections: SectionText = field(default_factory=SectionText)

    # Text fields -----------------------------------------------------------
    chat_base_url: SettingText = SettingText(
        "Chat base URL",
        "Address of the server that answers your questions, "
        "e.g. http://localhost:11434 for Ollama.",
    )
    embedding_base_url: SettingText = SettingText(
        "Embedding base URL",
        "Address of the server that turns book text into searchable vectors. "
        "Can differ from the chat server.",
    )
    chat_api_key: SettingText = SettingText(
        "Chat API key",
        "Secret key for the chat provider. Leave empty for local models.",
    )
    embedding_api_key: SettingText = SettingText(
        "Embedding API key",
        "Secret key for the embedding provider. Leave empty for local models.",
    )
    chat_model: SettingText = SettingText(
        "Chat model",
        "Model that writes the answers, e.g. llama3.1 or gpt-4o-mini.",
    )
    embedding_model: SettingText = SettingText(
        "Embedding model",
        "Model that indexes your books. Changing it means existing books "
        "must be re-indexed.",
    )

    # Select fields ---------------------------------------------------------
    chat_provider: SettingText = SettingText(
        "Chat provider",
        "Service that hosts the chat model. Selecting one fills in sensible defaults.",
    )
    embedding_provider: SettingText = SettingText(
        "Embedding provider",
        "Service that hosts the embedding model. Changing it may require "
        "re-indexing your books.",
    )

    # Choices ---------------------------------------------------------------
    preset: SettingText = SettingText(
        "Preset",
        "Quick starting points for the tuning options below. Adjusting any "
        "slider switches to Custom.",
    )

    # Tuning (keyed by the slider key used in the view model) --------------
    tuning: dict[str, SettingText] = field(default_factory=_default_tuning)

    def tuning_text(self, key: str) -> SettingText:
        """Copy for a tuning slider.

        Raises:
            KeyError: For an unknown slider key.
        """
        return self.tuning[key]


TEXT = SettingsText()

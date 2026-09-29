from __future__ import annotations

from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base inputs required or configurable
    data_dir: Path
    books_dir: str | None = Field(default=None, validation_alias="BOOKS_DIR")
    ollama_host: str = "http://127.0.0.1:11434"

    # Settings with defaults matching env.example or class defaults
    embedding_model: str = Field(
        default="embeddinggemma",
        validation_alias="EMBEDDING_MODEL",
    )
    generation_model: str = Field(
        default="gemma3:4b",
        validation_alias="LLM_MODEL",
    )
    chunk_chars: int = Field(default=1800, validation_alias="CHUNK_CHARS")
    chunk_overlap: int = Field(default=250, validation_alias="CHUNK_OVERLAP")
    batch_size: int = Field(default=8, validation_alias="BATCH_SIZE")
    retrieval_k: int = Field(default=6, validation_alias="RETRIEVAL_K")

    # Computed fields derived from data_dir
    @computed_field
    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @computed_field
    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "index.sqlite3"

    @classmethod
    def from_data_dir(
        cls, data_dir: Path | str, ollama_host: str | None = None
    ) -> Settings:
        """Construct Settings explicitly using a target data_dir."""
        if ollama_host is not None:
            return cls(data_dir=Path(data_dir), ollama_host=ollama_host)
        return cls(data_dir=Path(data_dir))

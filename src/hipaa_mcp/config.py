from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIPAA_MCP_", env_file=".env", extra="ignore")

    ollama_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e4b"
    use_llm_for_query_understanding: bool = True
    data_dir: Path = Field(default_factory=lambda: Path(user_data_dir("hipaa-mcp")))
    top_k_default: int = 5
    rrf_k: int = 60

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def bm25_index_path(self) -> Path:
        return self.data_dir / "bm25_index.pkl"

    @property
    def glossary_path(self) -> Path:
        return self.data_dir / "glossary.yaml"

    @property
    def corpus_dir(self) -> Path:
        return self.data_dir / "corpus"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

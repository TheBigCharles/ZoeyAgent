"""Application configuration loaded from environment variables.

Use `.env` for local secrets.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    postgres_url: str | None = Field(default=None, alias="POSTGRES_URL")

    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4.1-mini", alias="LLM_MODEL")

    embedding_base_url: str = Field(default="http://localhost:8000/v1", alias="EMBEDDING_BASE_URL")
    embedding_api_key: str = Field(default="dummy", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_dims: int = Field(default=1024, alias="EMBEDDING_DIMS")

    amap_api_key: str | None = Field(default=None, alias="AMAP_API_KEY")
    amap_mcp_command: str = Field(default="npx", alias="AMAP_MCP_COMMAND")
    amap_mcp_args: str = Field(default="-y @sugarforever/amap-mcp-server", alias="AMAP_MCP_ARGS")

    enable_image_enrichment: bool = Field(default=False, alias="ENABLE_IMAGE_ENRICHMENT")
    unsplash_access_key: str | None = Field(default=None, alias="UNSPLASH_ACCESS_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()

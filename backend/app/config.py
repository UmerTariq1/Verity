from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql://verity:verity@localhost:5432/verity",
        description="PostgreSQL connection string",
    )

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")

    # ── Pinecone ──────────────────────────────────────────────────────────────
    pinecone_api_key: str = Field(default="", description="Pinecone API key")
    pinecone_index_name: str = Field(default="verity", description="Pinecone index name")
    pinecone_environment: str = Field(default="gcp-starter", description="Pinecone environment")

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        default="changeme-use-a-32-byte-random-string-in-production",
        description="Secret key for signing JWTs — must be 32+ random bytes in production",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60, description="Token lifetime in minutes")

    # ── LangSmith ─────────────────────────────────────────────────────────────
    langsmith_api_key: str = Field(default="", description="LangSmith API key")
    langchain_tracing_v2: bool = Field(default=False)
    langchain_project: str = Field(default="verity")

    # ── Vector store ──────────────────────────────────────────────────────────
    vector_store: Literal["chroma", "pinecone"] = Field(
        default="chroma",
        description="Use 'chroma' for local dev, 'pinecone' for production",
    )
    chroma_persist_dir: str = Field(default="./chroma_db")

    # ── Chunking ──────────────────────────────────────────────────────────────
    chunking_strategy: Literal["fixed", "recursive"] = Field(
        default="recursive",
        description="'fixed' uses CharacterTextSplitter; 'recursive' uses RecursiveCharacterTextSplitter",
    )
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=512)

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:5500,http://127.0.0.1:5500",
        description="Comma-separated list of allowed CORS origins",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

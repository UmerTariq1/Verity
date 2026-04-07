from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal

# Resolve .env relative to THIS package, not the shell cwd — otherwise
# `uvicorn` from `backend/` never sees repo-root `.env` and CORS_* edits there
# are silently ignored.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _dotenv_files() -> tuple[str, ...] | None:
    paths: list[Path] = []
    primary = _BACKEND_ROOT / ".env"
    secondary = _BACKEND_ROOT.parent / ".env"
    if primary.is_file():
        paths.append(primary)
    if secondary.is_file() and secondary.resolve() != primary.resolve():
        paths.append(secondary)
    return tuple(str(p) for p in paths) if paths else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_dotenv_files(),
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

    # ── Startup tasks (demo-friendly defaults) ────────────────────────────────
    startup_ingestion_enabled: bool = Field(
        default=True,
        description="If true, ingest PDFs from data/ on startup when needed",
    )
    bm25_enabled: bool = Field(
        default=True,
        description="If true, enable BM25 sparse retrieval (hybrid mode)",
    )
    bm25_build_on_startup: bool = Field(
        default=True,
        description="If true, build the BM25 index during app startup",
    )

    # ── Chunking ──────────────────────────────────────────────────────────────
    chunking_strategy: Literal["fixed", "recursive"] = Field(
        default="recursive",
        description="'fixed' uses CharacterTextSplitter; 'recursive' uses RecursiveCharacterTextSplitter",
    )
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=512)

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default=(
            "http://localhost:5500,http://127.0.0.1:5500,"
            "http://localhost:8080,http://127.0.0.1:8080"
        ),
        description="Comma-separated list of allowed CORS origins",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

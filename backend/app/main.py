"""FastAPI application entry point.

Startup sequence (order matters):
  1. run_startup_ingestion() , ingest any un-indexed PDFs from data/
  2. build_bm25_index()      , build sparse index from the now-complete Chroma collection

BM25 must be built after ingestion so it sees all chunks.
"""
import logging
import sys
from contextlib import asynccontextmanager

_LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def _configure_logging() -> None:
    """Ensure application logs reach stderr under uvicorn.

    Uvicorn applies ``dictConfig`` before importing this module; it does not give
    the root logger a handler. ``basicConfig`` is then often a no-op. Some
    setups only show uvicorn's own loggers unless we attach handlers here.
    """
    formatter = logging.Formatter(_LOG_FMT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(formatter)
        h.setLevel(logging.INFO)
        root.addHandler(h)
    app_log = logging.getLogger("app")
    app_log.setLevel(logging.INFO)
    if not app_log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(formatter)
        h.setLevel(logging.INFO)
        app_log.addHandler(h)
    app_log.propagate = False


_configure_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.ingestion.startup_ingestor import run_startup_ingestion
from app.retrieval.bm25_index import build_bm25_index

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before the first request is served."""
    if settings.startup_ingestion_enabled:
        logger.info("Verity starting , running startup ingestion…")
        try:
            run_startup_ingestion()
        except Exception as exc:
            logger.error("Startup ingestion failed: %s", exc, exc_info=True)
    else:
        logger.info("Startup ingestion skipped (disabled by config).")

    if settings.bm25_enabled and settings.bm25_build_on_startup:
        logger.info("Building BM25 index…")
        try:
            build_bm25_index()
        except Exception as exc:
            logger.error("BM25 index build failed: %s", exc, exc_info=True)
    else:
        logger.info("BM25 index build skipped (disabled by config).")

    logger.info("Verity ready.")
    yield
    logger.info("Verity shutting down.")


# ── App factory ────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Verity , HR Policy Knowledge Retrieval",
    description=(
        "Production-grade RAG system for HR policy queries. "
        "Hybrid BM25 + dense retrieval with cross-encoder re-ranking."
    ),
    version="0.5.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception handlers ────────────────────────────────────────────────────────

register_exception_handlers(app)

# ── Routers ───────────────────────────────────────────────────────────────────

from app.api.auth import router as auth_router
from app.api.query import router as query_router
from app.api.documents import router as documents_router
from app.api.users import router as users_router
from app.api.logs import router as logs_router
from app.api.health import router as health_router

_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=_PREFIX)
app.include_router(query_router, prefix=_PREFIX)
app.include_router(documents_router, prefix=_PREFIX)
app.include_router(users_router, prefix=_PREFIX)
app.include_router(logs_router, prefix=_PREFIX)
app.include_router(health_router, prefix=_PREFIX)


# ── Root ping ─────────────────────────────────────────────────────────────────


@app.get("/", tags=["meta"])
def root() -> dict:
    """Health-check endpoint , no authentication required."""
    return {"status": "ok", "service": "verity"}

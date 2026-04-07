"""Startup auto-ingestor , runs once on FastAPI container startup.

Reads data/manifest.json and, for each entry, ingests the PDF into the
vector store and marks the DB row as "indexed" if it has not been already.

Idempotency contract:
  - A document whose DB row has status="indexed" is always skipped.
  - A document whose row is in "queued", "processing", or "failed" state
    (e.g. from a previous crashed run) is re-ingested: the row is reset to
    "queued" and the pipeline is rerun from scratch.
  - If no row exists yet, a new row is inserted.

This makes container restarts safe at any point in the pipeline.

Status lifecycle enforced here:
    (no row)  →  queued  →  processing  →  indexed
                                         ↘  failed
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PolicyDocument
from app.ingestion.chunker import get_splitter
from app.ingestion.embedder import embed_and_store
from app.ingestion.pdf_extractor import IngestionError, extract_pages

logger = logging.getLogger(__name__)


# ── Path resolution ───────────────────────────────────────────────────────────


def _resolve_data_dir() -> Path:
    """Return the data/ directory for either Docker or local-dev layout.

    Docker layout (WORKDIR=/app, data volume at /app/data):
        /app/app/ingestion/startup_ingestor.py → parents[2] = /app

    Local dev layout (project root three levels above the backend package):
        .../Verity/backend/app/ingestion/startup_ingestor.py → parents[3] = .../Verity
    """
    here = Path(__file__).resolve().parents

    docker_candidate = here[2] / "data"
    local_candidate = here[3] / "data"

    for candidate in (docker_candidate, local_candidate):
        if (candidate / "manifest.json").exists():
            return candidate

    return local_candidate


DATA_DIR = _resolve_data_dir()
MANIFEST_PATH = DATA_DIR / "manifest.json"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_manifest() -> list[dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        logger.warning(
            "manifest.json not found at %s , startup ingestion skipped", MANIFEST_PATH
        )
        return []
    with MANIFEST_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _get_existing_row(db: Session, file_name: str) -> PolicyDocument | None:
    return db.execute(
        select(PolicyDocument).where(PolicyDocument.file_name == file_name)
    ).scalar_one_or_none()


def _build_chunks(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split extracted pages into chunks, preserving page_number metadata."""
    splitter = get_splitter()
    chunks: list[dict[str, Any]] = []
    for page in pages:
        if not page["text"]:
            continue
        for chunk_text in splitter.split_text(page["text"]):
            stripped = chunk_text.strip()
            if stripped:
                chunks.append({"text": stripped, "page_number": page["page_number"]})
    return chunks


# ── Core ingestion logic ──────────────────────────────────────────────────────


def _ingest_one(db: Session, entry: dict[str, Any]) -> None:
    """Run the full ingestion pipeline for a single manifest entry.

    Skips silently if the document is already indexed.
    Transitions status: queued → processing → indexed | failed.
    uploaded_by_user_id is always None for system-seeded documents.
    """
    file_name: str = entry["filename"]
    pdf_path = DATA_DIR / file_name

    if not pdf_path.exists():
        logger.warning("PDF file not found on disk, skipping: %s", pdf_path)
        return

    # ── Check existing DB row ────────────────────────────────────────────────
    existing = _get_existing_row(db, file_name)

    if existing and existing.status == "indexed":
        logger.info("Already indexed , skipping: %s", file_name)
        return

    effective_date = date.fromisoformat(entry["effective_date"])

    if existing:
        # Reset a failed / zombie row so we can re-ingest it
        logger.info(
            "Resetting %s row from status=%s for re-ingestion",
            file_name,
            existing.status,
        )
        doc_id = existing.id
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="queued", chunk_count=0)
        )
        db.commit()
    else:
        # Create a new row , uploaded_by_user_id=None marks it as system-seeded
        doc = PolicyDocument(
            file_name=file_name,
            category=entry["category"],
            # manifest key "department" maps to DB column "owner_department"
            owner_department=entry["department"],
            effective_date=effective_date,
            uploaded_by_user_id=None,
            status="queued",
            chunk_count=0,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id

    # ── queued → processing ──────────────────────────────────────────────────
    db.execute(
        update(PolicyDocument)
        .where(PolicyDocument.id == doc_id)
        .values(status="processing")
    )
    db.commit()

    # ── Extract → chunk → embed → store ─────────────────────────────────────
    try:
        pages = extract_pages(pdf_path)
        chunks = _build_chunks(pages)

        if not chunks:
            raise IngestionError(
                f"No non-empty chunks produced from {file_name} , check PDF content"
            )

        doc_metadata = {
            "file_name": file_name,
            "category": entry["category"],
            "owner_department": entry["department"],
            "effective_date": effective_date,
        }

        chunk_count = embed_and_store(doc_id, chunks, doc_metadata, db)

        # ── processing → indexed ─────────────────────────────────────────────
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="indexed", chunk_count=chunk_count)
        )
        db.commit()
        logger.info("Indexed '%s' , %d chunks stored", file_name, chunk_count)

    except IngestionError as exc:
        logger.error("Ingestion error for '%s': %s", file_name, exc)
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="failed")
        )
        db.commit()

    except Exception as exc:
        logger.error("Unexpected error ingesting '%s': %s", file_name, exc, exc_info=True)
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="failed")
        )
        db.commit()
        raise


# ── Public entry point ────────────────────────────────────────────────────────


def run_startup_ingestion() -> None:
    """Entry point called from the FastAPI lifespan hook on container startup.

    Opens its own DB session so the lifespan context does not need to manage
    one.  Each document is ingested in a separate try/except so a single
    failure does not abort the remaining documents.
    """
    manifest = _load_manifest()
    if not manifest:
        return

    logger.info(
        "Startup ingestion: checking %d manifest entries against data dir %s",
        len(manifest),
        DATA_DIR,
    )

    db: Session = SessionLocal()
    try:
        for entry in manifest:
            try:
                _ingest_one(db, entry)
            except Exception:
                # Already logged inside _ingest_one; continue with the rest
                logger.warning(
                    "Startup ingestion: skipping '%s' after unrecoverable error",
                    entry.get("filename"),
                )
    finally:
        db.close()

    logger.info("Startup ingestion complete.")

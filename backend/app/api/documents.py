"""Document management routes.

GET    /api/v1/documents                — list (all authenticated users)
POST   /api/v1/documents/upload         — upload PDF (admin only)
DELETE /api/v1/documents/{id}           — delete + remove from vector store (admin only)
POST   /api/v1/documents/{id}/reindex   — re-embed a single document (admin only)
"""
import asyncio
import logging
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_admin
from app.database import get_db, SessionLocal
from app.ingestion.chunker import get_splitter
from app.ingestion.embedder import delete_chunks, embed_and_store
from app.ingestion.pdf_extractor import IngestionError, extract_pages
from app.models import PolicyDocument, User
from app.retrieval import bm25_index as _bm25
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_PDF_MIME = "application/pdf"


# ── Background ingestion task ─────────────────────────────────────────────────


def _ingest_uploaded_pdf(
    doc_id: uuid.UUID,
    tmp_bytes: bytes,
    file_name: str,
    category: str,
    owner_department: str,
    effective_date: date,
    splitter_overrides: dict | None = None,
) -> None:
    """Run ingestion pipeline in a background thread-pool task.

    Opens its own DB session because the route's session is already closed.
    Status transitions: queued → processing → indexed | failed.
    Rebuilds BM25 index after successful ingestion.
    """
    db: Session = SessionLocal()
    try:
        logger.info("Ingestion starting: %s (%s)", file_name, doc_id)
        # queued → processing
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="processing")
        )
        db.commit()

        # Write bytes to a temp file so pdf_extractor can use pdfplumber (needs path)
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(tmp_bytes)
            tmp_path = Path(tmp.name)

        try:
            pages = extract_pages(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        splitter_overrides = splitter_overrides or {}
        splitter = get_splitter(
            strategy=splitter_overrides.get("strategy"),
            chunk_size=splitter_overrides.get("chunk_size"),
            chunk_overlap=splitter_overrides.get("chunk_overlap"),
        )
        chunks: list[dict] = []
        for page in pages:
            if not page["text"]:
                continue
            for chunk_text in splitter.split_text(page["text"]):
                stripped = chunk_text.strip()
                if stripped:
                    chunks.append({"text": stripped, "page_number": page["page_number"]})

        if not chunks:
            raise IngestionError(f"No non-empty chunks produced from {file_name}")

        doc_metadata = {
            "file_name": file_name,
            "category": category,
            "owner_department": owner_department,
            "effective_date": effective_date,
        }

        chunk_count = embed_and_store(doc_id, chunks, doc_metadata, db)

        # processing → indexed
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="indexed", chunk_count=chunk_count)
        )
        db.commit()
        logger.info("Background ingestion complete: %s — %d chunks", file_name, chunk_count)

        # Rebuild BM25 so the new document is immediately searchable
        _bm25.build_bm25_index()

    except IngestionError as exc:
        logger.error("Ingestion failed for %s: %s", file_name, exc)
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="failed")
        )
        db.commit()
    except Exception as exc:
        logger.error("Unexpected ingestion error for %s: %s", file_name, exc, exc_info=True)
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="failed")
        )
        db.commit()
    finally:
        db.close()


async def _run_ingestion_async(
    doc_id: uuid.UUID,
    tmp_bytes: bytes,
    file_name: str,
    category: str,
    owner_department: str,
    effective_date: date,
    splitter_overrides: dict | None = None,
) -> None:
    """Wrap the blocking ingestion call so it runs in the default thread pool."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        _ingest_uploaded_pdf,
        doc_id,
        tmp_bytes,
        file_name,
        category,
        owner_department,
        effective_date,
        splitter_overrides,
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=DocumentListResponse)
def list_documents(
    search: str = "",
    category: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    """Return a paginated list of policy documents."""
    stmt = select(PolicyDocument)
    if search:
        stmt = stmt.where(PolicyDocument.file_name.ilike(f"%{search}%"))
    if category:
        stmt = stmt.where(PolicyDocument.category == category)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    items = db.execute(
        stmt.order_by(PolicyDocument.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().all()

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in items],
        total=total,
        page=page,
        size=size,
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(...),
    owner_department: str = Form(...),
    effective_date: str = Form(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload a PDF, create a DB record, and trigger background ingestion.

    Returns immediately with doc_id and status="queued".
    Ingestion status can be polled via GET /documents/{id}.
    """
    # MIME type validation
    if file.content_type not in (_PDF_MIME, "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only PDF files are accepted (application/pdf)",
        )
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must have a .pdf extension",
        )

    try:
        parsed_date = date.fromisoformat(effective_date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="effective_date must be in YYYY-MM-DD format",
        )

    file_bytes = await file.read()
    file_name = file.filename or f"upload_{uuid.uuid4()}.pdf"
    logger.info(
        "Upload received: %s | bytes=%d | category=%s | owner_department=%s | effective_date=%s | user=%s",
        file_name,
        len(file_bytes or b""),
        category,
        owner_department,
        effective_date,
        getattr(current_user, "id", "unknown"),
    )

    # Prevent duplicate filenames (case-insensitive) to avoid ambiguous policies.
    existing = db.execute(
        select(PolicyDocument.id).where(func.lower(PolicyDocument.file_name) == file_name.lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A document named '{file_name}' already exists.",
        )

    doc = PolicyDocument(
        file_name=file_name,
        category=category,
        owner_department=owner_department,
        effective_date=parsed_date,
        uploaded_by_user_id=current_user.id,
        status="queued",
        chunk_count=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Fire-and-forget background task
    asyncio.create_task(
        _run_ingestion_async(
            doc.id, file_bytes, file_name, category, owner_department, parsed_date, None
        )
    )

    return DocumentUploadResponse(
        doc_id=doc.id,
        status="queued",
        message=f"'{file_name}' queued for ingestion. Poll GET /documents to check status.",
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Return the current status and metadata for a single document."""
    doc = db.execute(
        select(PolicyDocument).where(PolicyDocument.id == doc_id)
    ).scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return DocumentResponse.model_validate(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Delete a document from the DB and remove its chunks from the vector store."""
    doc = db.execute(
        select(PolicyDocument).where(PolicyDocument.id == doc_id)
    ).scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    delete_chunks(doc_id)

    db.delete(doc)
    db.commit()

    # Rebuild BM25 after removal
    _bm25.build_bm25_index()


@router.post("/{doc_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document(
    doc_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    chunking_strategy: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
) -> dict:
    """Delete existing chunks and re-embed the document from the stored file bytes.

    Note: re-ingestion requires the original PDF to still be in the data/ folder.
    For admin-uploaded files, re-index is only possible if the file was from data/.
    The route removes existing vectors and marks the document as queued.
    """
    doc = db.execute(
        select(PolicyDocument).where(PolicyDocument.id == doc_id)
    ).scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Remove existing vectors before re-ingesting
    delete_chunks(doc_id)

    db.execute(
        update(PolicyDocument)
        .where(PolicyDocument.id == doc_id)
        .values(status="queued", chunk_count=0)
    )
    db.commit()

    # Re-ingest from the data/ directory
    from app.ingestion.startup_ingestor import DATA_DIR

    pdf_path = DATA_DIR / doc.file_name
    if not pdf_path.exists():
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.id == doc_id)
            .values(status="failed")
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Original PDF '{doc.file_name}' not found in data/ directory. "
                "Re-index is only supported for documents in the data/ folder."
            ),
        )

    file_bytes = pdf_path.read_bytes()

    splitter_overrides = {
        "strategy": chunking_strategy,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }

    asyncio.create_task(
        _run_ingestion_async(
            doc_id,
            file_bytes,
            doc.file_name,
            doc.category,
            doc.owner_department,
            doc.effective_date,
            splitter_overrides,
        )
    )

    return {"message": f"Re-index of '{doc.file_name}' queued.", "doc_id": str(doc_id)}

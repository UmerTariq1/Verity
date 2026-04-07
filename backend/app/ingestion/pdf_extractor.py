"""Extract text from PDF files page-by-page using pdfplumber.

Rejects non-PDF files, encrypted/password-protected PDFs, and
image-only PDFs that produce no extractable text.
"""
from pathlib import Path
from typing import Any


class IngestionError(Exception):
    """Raised for unrecoverable ingestion problems (bad file, encryption, empty text)."""


def extract_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Extract text from every page of a PDF.

    Returns a list of page dicts:
        [{"text": str, "page_number": int}, ...]

    Raises IngestionError for:
    - File not found or wrong extension
    - Encrypted / password-protected PDF
    - PDF that produces no extractable text (scanned / image-only)
    """
    import pdfplumber  # deferred , avoids import cost when module is imported without extracting

    path = Path(pdf_path)

    if not path.exists():
        raise IngestionError(f"File not found: {path}")

    if path.suffix.lower() != ".pdf":
        raise IngestionError(
            f"Expected a .pdf file, got '{path.suffix}' for file: {path.name}"
        )

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise IngestionError(f"PDF has no pages: {path.name}")

            pages: list[dict[str, Any]] = []
            for page in pdf.pages:
                raw = page.extract_text() or ""
                pages.append(
                    {
                        "text": raw.strip(),
                        "page_number": page.page_number,
                    }
                )

            all_text = "".join(p["text"] for p in pages)
            if not all_text.strip():
                raise IngestionError(
                    f"PDF produced no extractable text , "
                    f"it may be scanned or image-only: {path.name}"
                )

            return pages

    except IngestionError:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("password", "encrypt", "permission", "not allowed")):
            raise IngestionError(
                f"PDF is password-protected or encrypted: {path.name}"
            ) from exc
        raise IngestionError(
            f"Failed to extract text from {path.name}: {exc}"
        ) from exc

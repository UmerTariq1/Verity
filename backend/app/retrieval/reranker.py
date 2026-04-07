"""Cross-encoder re-ranker.

Uses ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (HuggingFace sentence-transformers)
to re-score (query, chunk) pairs and return the top-K candidates.

Design decision (documented in README "Retrieval Design Decisions"):
  Initial BM25 + dense retrieval optimises for recall , we want to surface
  as many relevant chunks as possible in the top-20 candidate pool.
  The cross-encoder then optimises for precision by jointly encoding the
  query and each chunk, which is far more accurate than the separate
  query / document encoding used during retrieval.

Latency tradeoff:
  ~200–400 ms on CPU for 20 candidates.  This is acceptable for an internal
  HR tool where answer quality matters more than sub-100ms latency.  Documented
  in README so evaluators understand the deliberate tradeoff.

Model download:
  The model is downloaded from HuggingFace on first instantiation (~100 MB).
  In production the Dockerfile should pre-bake the weights (noted as a Phase 5
  follow-up) to avoid a ~30 s cold-start penalty on container boot.
"""
import logging
from dataclasses import replace

from sentence_transformers import CrossEncoder

from app.retrieval.vector_store import RetrievalResult

logger = logging.getLogger(__name__)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Lazy singleton , model loaded once and reused across all requests
_encoder: CrossEncoder | None = None


def _get_encoder() -> CrossEncoder:
    global _encoder
    if _encoder is None:
        logger.info("Loading cross-encoder model '%s'…", _MODEL_NAME)
        _encoder = CrossEncoder(_MODEL_NAME)
        logger.info("Cross-encoder model ready.")
    return _encoder


def rerank(
    query: str,
    candidates: list[RetrievalResult],
    top_k: int = 5,
) -> list[RetrievalResult]:
    """Re-score candidates with the cross-encoder and return the top-K.

    Args:
        query:      The user query string.
        candidates: Candidate chunks from RRF fusion (typically top-20).
        top_k:      Number of results to return after re-ranking (default 5).

    Returns:
        Up to ``top_k`` results with ``score`` replaced by the cross-encoder
        logit, ordered descending (higher = more relevant).  Returns an empty
        list if ``candidates`` is empty.
    """
    if not candidates:
        return []

    encoder = _get_encoder()
    pairs = [(query, candidate.text) for candidate in candidates]

    raw_scores: list[float] = encoder.predict(pairs).tolist()

    scored = sorted(
        zip(candidates, raw_scores),
        key=lambda t: t[1],
        reverse=True,
    )

    return [replace(result, score=score) for result, score in scored[:top_k]]

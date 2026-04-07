"""Hybrid retrieval pipeline: BM25 + dense → RRF fusion → cross-encoder re-ranking.

Pipeline overview:
  1. BM25 sparse retrieval  — top-20 from the in-memory BM25Okapi index
  2. Dense retrieval        — top-20 from Chroma / Pinecone via cosine similarity
  3. RRF fusion             — merge both ranked lists; de-duplicate by chunk_id
  4. Cross-encoder rerank   — re-score top-20 RRF candidates with ms-marco
  5. Return top-K           — typically 5 chunks with cross-encoder scores

Why Reciprocal Rank Fusion over weighted-sum score fusion (documented in README):
  BM25 scores and cosine similarities live on different scales and follow
  different distributions depending on query length and corpus size.  Calibrating
  a weighted sum requires empirical tuning per deployment — brittle and not
  generalisable.  RRF operates on ordinal ranks which are stable across query
  types and vector store implementations.  The k=60 constant smooths out the
  contribution of lower-ranked results without needing any tuning.

LangSmith tracing:
  The ``@traceable`` decorator wraps ``retrieve()`` so every call appears as a
  named span in LangSmith with the query text, filters, intermediate hit counts,
  and final chunk IDs.  If LangSmith is not installed or tracing is disabled the
  decorator is a transparent no-op.

  RRF formula:  score(d) = Σ  1 / (k + rank(d))   where k = 60
"""
import logging
from dataclasses import dataclass
from typing import Any

from app.retrieval import bm25_index as _bm25
from app.retrieval.reranker import rerank
from app.retrieval.vector_store import RetrievalResult, get_vector_store

logger = logging.getLogger(__name__)

_RRF_K = 60          # standard smoothing constant — no need to tune
_CANDIDATE_POOL = 20  # size of each retrieval list fed into RRF and re-ranker
_TOP_K_DEFAULT = 5   # final chunks returned to the caller


# ── LangSmith tracing (optional dependency) ───────────────────────────────────

try:
    from langsmith import traceable as _traceable  # type: ignore[import]
except ImportError:  # langsmith not installed — wrap with a no-op
    def _traceable(func=None, **_kwargs):  # type: ignore[misc]
        if func is not None:
            return func

        def _decorator(f):
            return f

        return _decorator


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class HybridRetrievalResult:
    """Full output of the hybrid retrieval pipeline.

    ``chunks`` are the final top-K results ordered by cross-encoder score
    (descending).  The intermediate score dicts let Phase 5 log the full
    pipeline trace to ``query_logs.relevance_scores``.
    """

    chunks: list[RetrievalResult]
    rrf_scores: dict[str, float]      # chunk_id → RRF score (pre-rerank)
    reranker_scores: dict[str, float]  # chunk_id → cross-encoder logit


# ── Internal helpers ──────────────────────────────────────────────────────────


def _reciprocal_rank_fusion(
    bm25_hits: list[tuple[str, float, str, dict]],
    dense_hits: list[RetrievalResult],
    k: int = _RRF_K,
) -> list[tuple[str, float]]:
    """Merge BM25 and dense ranked lists into a single RRF-scored list.

    Returns a de-duplicated list of ``(chunk_id, rrf_score)`` sorted descending.
    A chunk that appears in both lists gets contributions from both ranks,
    naturally boosting precision without requiring score calibration.
    """
    rrf: dict[str, float] = {}

    for rank, (chunk_id, _score, _text, _meta) in enumerate(bm25_hits, start=1):
        rrf[chunk_id] = rrf.get(chunk_id, 0.0) + 1.0 / (k + rank)

    for rank, result in enumerate(dense_hits, start=1):
        rrf[result.chunk_id] = rrf.get(result.chunk_id, 0.0) + 1.0 / (k + rank)

    return sorted(rrf.items(), key=lambda t: t[1], reverse=True)


def _build_result_map(
    bm25_hits: list[tuple[str, float, str, dict]],
    dense_hits: list[RetrievalResult],
) -> dict[str, RetrievalResult]:
    """Build a chunk_id → RetrievalResult lookup from both retrieval sources.

    Dense hits take priority when the same chunk appears in both lists because
    they already carry a ``RetrievalResult`` with a pre-computed score.
    """
    result_map: dict[str, RetrievalResult] = {}

    for chunk_id, bm25_score, text, meta in bm25_hits:
        result_map[chunk_id] = RetrievalResult(
            chunk_id=chunk_id,
            doc_id=meta.get("doc_id", ""),
            text=text,
            file_name=meta.get("file_name", ""),
            page_number=int(meta.get("page_number", 0)),
            category=meta.get("category", ""),
            owner_department=meta.get("owner_department", ""),
            effective_date=meta.get("effective_date", ""),
            score=bm25_score,
        )

    # Dense results overwrite BM25-only entries so scores reflect cosine similarity
    for result in dense_hits:
        result_map[result.chunk_id] = result

    return result_map


# ── Public entry point ────────────────────────────────────────────────────────


@_traceable(name="hybrid_retriever.retrieve")
def retrieve(
    query: str,
    top_k: int = _TOP_K_DEFAULT,
    filters: dict[str, Any] | None = None,
) -> HybridRetrievalResult:
    """Run the full hybrid retrieval pipeline.

    Args:
        query:   User query string (natural language).
        top_k:   Number of final chunks to return (default 5).
        filters: Optional metadata pre-filters forwarded to the vector store.
                 Recognised keys: ``category``, ``owner_department``,
                 ``date_from`` (ISO str), ``date_to`` (ISO str).
                 Unknown keys are silently ignored.

    Returns:
        ``HybridRetrievalResult`` containing the final chunks plus the
        intermediate RRF and cross-encoder score dicts for logging.
    """
    logger.debug("Hybrid retrieve | query=%r | filters=%s", query, filters)

    # ── 1. BM25 sparse retrieval ──────────────────────────────────────────────
    bm25_hits = _bm25.search(query, top_n=_CANDIDATE_POOL)
    logger.debug("BM25 → %d candidates", len(bm25_hits))

    # ── 2. Dense semantic retrieval ───────────────────────────────────────────
    vector_store = get_vector_store()
    dense_hits = vector_store.search(query, top_n=_CANDIDATE_POOL, filters=filters)
    logger.debug("Dense → %d candidates", len(dense_hits))

    if not bm25_hits and not dense_hits:
        logger.warning("Hybrid retrieval: both BM25 and dense returned 0 results")
        return HybridRetrievalResult(chunks=[], rrf_scores={}, reranker_scores={})

    # ── 3. Reciprocal Rank Fusion ─────────────────────────────────────────────
    fused = _reciprocal_rank_fusion(bm25_hits, dense_hits)
    rrf_scores: dict[str, float] = dict(fused)

    result_map = _build_result_map(bm25_hits, dense_hits)

    # Feed the top-CANDIDATE_POOL RRF results into the cross-encoder
    rrf_top_ids = [chunk_id for chunk_id, _ in fused[:_CANDIDATE_POOL]]
    rrf_candidates = [result_map[cid] for cid in rrf_top_ids if cid in result_map]

    if not rrf_candidates:
        logger.warning("Hybrid retrieval: RRF produced no candidates — empty result")
        return HybridRetrievalResult(chunks=[], rrf_scores=rrf_scores, reranker_scores={})

    # ── 4. Cross-encoder re-ranking ───────────────────────────────────────────
    reranked = rerank(query, rrf_candidates, top_k=top_k)
    reranker_scores: dict[str, float] = {r.chunk_id: r.score for r in reranked}

    logger.info(
        "Hybrid retrieve complete | final=%d | bm25_pool=%d | dense_pool=%d | rrf_pool=%d",
        len(reranked),
        len(bm25_hits),
        len(dense_hits),
        len(rrf_candidates),
    )

    return HybridRetrievalResult(
        chunks=reranked,
        rrf_scores=rrf_scores,
        reranker_scores=reranker_scores,
    )

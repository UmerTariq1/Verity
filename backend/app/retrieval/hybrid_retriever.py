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
from dataclasses import dataclass, field
from typing import Any

from app.retrieval import bm25_index as _bm25
from app.retrieval.reranker import rerank
from app.retrieval.vector_store import RetrievalResult, _parse_chunk_index, get_vector_store

logger = logging.getLogger(__name__)

_RRF_K = 60          # standard smoothing constant — no need to tune
_CANDIDATE_POOL = 20  # size of each retrieval list fed into RRF and re-ranker
_TOP_K_DEFAULT = 5   # final chunks returned to the caller

# Minimum rank improvement for the re-ranker to claim "top_ranked" method.
# A chunk promoted ≥5 positions vs its RRF rank is considered re-ranker-boosted.
_RERANK_BOOST_THRESHOLD = 5


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
class TraceEntry:
    """Per-chunk retrieval trace entry stored in query_logs.retrieval_trace."""

    chunk_id: str
    doc_id: str
    file_name: str
    page_number: int
    chunk_index: int           # 1-based position within the parent document
    chunk_total: int | None    # total chunks for this document (None for legacy chunks)
    preview: str               # first 120 chars of chunk text
    bm25_score: float | None
    dense_score: float | None
    rrf_score: float
    rerank_score: float
    method: str                # "keyword_match" | "semantic_match" | "top_ranked"
    selected: bool             # True iff included in LLM context (top-K)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "file_name": self.file_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "chunk_total": self.chunk_total,
            "preview": self.preview,
            "scores": {
                "bm25": self.bm25_score,
                "dense": self.dense_score,
                "rrf": round(self.rrf_score, 6),
                "rerank": round(self.rerank_score, 4),
            },
            "method": self.method,
            "selected": self.selected,
        }


@dataclass
class HybridRetrievalResult:
    """Full output of the hybrid retrieval pipeline.

    ``chunks`` are the final top-K results ordered by cross-encoder score
    (descending).  The intermediate score dicts let Phase 5 log the full
    pipeline trace to ``query_logs.relevance_scores``.
    """

    chunks: list[RetrievalResult]
    rrf_scores: dict[str, float]       # chunk_id → RRF score (pre-rerank)
    reranker_scores: dict[str, float]  # chunk_id → cross-encoder logit
    trace: list[TraceEntry] = field(default_factory=list)  # full pipeline trace


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
        raw_index = meta.get("chunk_index")
        raw_total = meta.get("chunk_total")

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
            chunk_index=int(raw_index) if raw_index is not None else _parse_chunk_index(chunk_id),
            chunk_total=int(raw_total) if raw_total is not None else None,
        )

    # Dense results overwrite BM25-only entries so scores reflect cosine similarity
    for result in dense_hits:
        result_map[result.chunk_id] = result

    return result_map


def _assign_method(
    chunk_id: str,
    rrf_rank: int,
    rerank_rank: int,
    bm25_rank: int | None,
    dense_rank: int | None,
) -> str:
    """Assign a human-readable method label for a chunk based on rank deltas."""
    # Re-ranker significantly promoted this chunk vs its RRF position.
    if (rrf_rank - rerank_rank) >= _RERANK_BOOST_THRESHOLD:
        return "top_ranked"
    # Only in BM25 or BM25 rank clearly better than dense rank.
    if bm25_rank is not None and (dense_rank is None or bm25_rank < dense_rank):
        return "keyword_match"
    return "semantic_match"


def _build_trace(
    rrf_ordered: list[tuple[str, float]],
    all_reranked: list[RetrievalResult],  # full candidate pool, reranked
    result_map: dict[str, RetrievalResult],
    bm25_ranks: dict[str, int],          # chunk_id → 0-based BM25 rank
    dense_ranks: dict[str, int],         # chunk_id → 0-based dense rank
    rrf_scores: dict[str, float],
    top_k: int,
) -> list[TraceEntry]:
    """Build ordered TraceEntry list (selected first, then rejected)."""
    selected_ids = {r.chunk_id for r in all_reranked[:top_k]}
    rrf_rank_map = {cid: i for i, (cid, _) in enumerate(rrf_ordered)}

    entries: list[TraceEntry] = []
    for rerank_rank, result in enumerate(all_reranked):
        cid = result.chunk_id
        base = result_map.get(cid, result)
        bm25_r = bm25_ranks.get(cid)
        dense_r = dense_ranks.get(cid)
        rrf_r = rrf_rank_map.get(cid, rerank_rank)

        # Retrieve per-source raw scores from the original maps
        bm25_score: float | None = None
        if cid in bm25_ranks:
            # re-retrieve score value; map only has rank, so use bm25 result order
            bm25_score = None  # filled below via _bm25_scores map passed in

        entries.append(TraceEntry(
            chunk_id=cid,
            doc_id=base.doc_id,
            file_name=base.file_name,
            page_number=base.page_number,
            chunk_index=base.chunk_index,
            chunk_total=base.chunk_total,
            preview=(base.text or "")[:120],
            bm25_score=bm25_score,
            dense_score=base.score if dense_r is not None else None,
            rrf_score=rrf_scores.get(cid, 0.0),
            rerank_score=result.score,
            method=_assign_method(cid, rrf_r, rerank_rank, bm25_r, dense_r),
            selected=cid in selected_ids,
        ))

    return entries


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
        intermediate RRF and cross-encoder score dicts for logging, and a
        full ``trace`` list with method attribution for every candidate.
    """
    logger.debug("Hybrid retrieve | query=%r | filters=%s", query, filters)

    # ── 1. BM25 sparse retrieval ──────────────────────────────────────────────
    bm25_hits = _bm25.search(query, top_n=_CANDIDATE_POOL)
    logger.debug("BM25 → %d candidates", len(bm25_hits))

    # Build rank and score lookups for BM25 results
    bm25_ranks: dict[str, int] = {cid: i for i, (cid, *_) in enumerate(bm25_hits)}
    bm25_scores: dict[str, float] = {cid: score for cid, score, *_ in bm25_hits}

    # ── 2. Dense semantic retrieval ───────────────────────────────────────────
    vector_store = get_vector_store()
    dense_hits = vector_store.search(query, top_n=_CANDIDATE_POOL, filters=filters)
    logger.debug("Dense → %d candidates", len(dense_hits))

    dense_ranks: dict[str, int] = {r.chunk_id: i for i, r in enumerate(dense_hits)}

    if not bm25_hits and not dense_hits:
        logger.warning("Hybrid retrieval: both BM25 and dense returned 0 results")
        return HybridRetrievalResult(chunks=[], rrf_scores={}, reranker_scores={}, trace=[])

    # ── 3. Reciprocal Rank Fusion ─────────────────────────────────────────────
    fused = _reciprocal_rank_fusion(bm25_hits, dense_hits)
    rrf_scores: dict[str, float] = dict(fused)

    result_map = _build_result_map(bm25_hits, dense_hits)

    # Feed the top-CANDIDATE_POOL RRF results into the cross-encoder
    rrf_top_ids = [chunk_id for chunk_id, _ in fused[:_CANDIDATE_POOL]]
    rrf_candidates = [result_map[cid] for cid in rrf_top_ids if cid in result_map]

    if not rrf_candidates:
        logger.warning("Hybrid retrieval: RRF produced no candidates — empty result")
        return HybridRetrievalResult(chunks=[], rrf_scores=rrf_scores, reranker_scores={}, trace=[])

    # ── 4. Cross-encoder re-ranking (full candidate pool) ────────────────────
    # Pass the whole pool so we keep rejected chunks in the trace.
    all_reranked = rerank(query, rrf_candidates, top_k=len(rrf_candidates))
    reranker_scores: dict[str, float] = {r.chunk_id: r.score for r in all_reranked}

    # ── 5. Build trace with method attribution ────────────────────────────────
    trace = _build_trace(
        rrf_ordered=fused,
        all_reranked=all_reranked,
        result_map=result_map,
        bm25_ranks=bm25_ranks,
        dense_ranks=dense_ranks,
        rrf_scores=rrf_scores,
        top_k=top_k,
    )

    # Backfill actual BM25 score values into trace entries
    for entry in trace:
        if entry.chunk_id in bm25_scores:
            entry.bm25_score = round(bm25_scores[entry.chunk_id], 4)
        if entry.chunk_id in dense_ranks:
            # score is on the RetrievalResult from result_map
            r = result_map.get(entry.chunk_id)
            if r:
                entry.dense_score = round(r.score, 4)

    final_chunks = all_reranked[:top_k]

    logger.info(
        "Hybrid retrieve complete | final=%d | bm25_pool=%d | dense_pool=%d | rrf_pool=%d",
        len(final_chunks),
        len(bm25_hits),
        len(dense_hits),
        len(rrf_candidates),
    )

    return HybridRetrievalResult(
        chunks=final_chunks,
        rrf_scores=rrf_scores,
        reranker_scores=reranker_scores,
        trace=trace,
    )

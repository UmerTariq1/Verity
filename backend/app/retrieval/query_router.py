"""Query router — decides between PostgreSQL metadata lookup and hybrid RAG retrieval.

Routing strategy (keyword heuristic, no LLM call needed):
  Queries that begin with list / show / find all / how many + "document"
  keyword → ``"metadata"`` route (returns a filtered document list from
  PostgreSQL, not a RAG answer).

  All other queries → ``"hybrid"`` route (BM25 + dense + reranker).

This heuristic is intentionally simple and transparent:
  - Zero latency overhead (no embedding or LLM call)
  - Easily debuggable — the routing decision is logged at DEBUG level
  - Covers the main admin use-case of listing documents by category/date
  - Documented in README "Retrieval Design Decisions"

Date filter extraction (applied to both routes):
  Priority order:
    1. Two ISO dates in the same query → used as [date_from, date_to] range
    2. Single ISO date               → used as exact date (date_from = date_to)
    3. Quarter notation (Q1 2024)    → expanded to [YYYY-MM-DD, YYYY-MM-DD]
    4. Four-digit year alone         → expanded to [YYYY-01-01, YYYY-12-31]

Category filter extraction:
  Case-insensitive substring search against the provided ``known_categories``
  list (typically fetched from the ``policy_documents`` table by Phase 5 routes).
  Falls back to a static default set if no list is provided.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ── Routing heuristic ─────────────────────────────────────────────────────────

_METADATA_PREFIX_RE = re.compile(
    r"^(list|show|find\s+all|how\s+many)\b",
    re.IGNORECASE,
)

# "document" must also appear somewhere in the query to avoid false positives
# like "list the steps in the disciplinary procedure"
_DOCUMENT_WORD_RE = re.compile(r"\bdocuments?\b", re.IGNORECASE)


# ── Date extraction patterns ──────────────────────────────────────────────────

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_YEAR_ONLY_RE = re.compile(r"\b(20\d{2})\b")
_QUARTER_RE = re.compile(r"\b(Q[1-4])\s+(20\d{2})\b", re.IGNORECASE)

_QUARTER_RANGES: dict[str, tuple[str, str]] = {
    "Q1": ("01-01", "03-31"),
    "Q2": ("04-01", "06-30"),
    "Q3": ("07-01", "09-30"),
    "Q4": ("10-01", "12-31"),
}


# ── Default categories (used when caller does not pass known_categories) ──────

_DEFAULT_CATEGORIES: list[str] = [
    "HR Policy",
    "Finance Policy",
    "Technical Policy",
    "IT & Security",
]


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class RouteResult:
    """Output of ``route_query()``.

    ``route`` is ``"metadata"`` (PostgreSQL document list) or ``"hybrid"``
    (BM25 + dense + reranker pipeline).

    ``filters`` contains any extracted date/category constraints.  Phase 5
    routes pass this dict directly to ``hybrid_retriever.retrieve()`` and
    to the metadata-query SQL builder.

    Keys present in ``filters``:
      category          — matched category string (may be absent)
      owner_department  — not extracted at this layer; Phase 5 can extend
      date_from         — ISO date string (may be absent)
      date_to           — ISO date string (may be absent)
    """

    route: Literal["metadata", "hybrid"]
    filters: dict[str, Any] = field(default_factory=dict)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _extract_dates(query: str) -> dict[str, str]:
    """Return a ``{date_from, date_to}`` dict extracted from the query text."""
    iso_matches = _ISO_DATE_RE.findall(query)
    if len(iso_matches) >= 2:
        sorted_dates = sorted(iso_matches)
        return {"date_from": sorted_dates[0], "date_to": sorted_dates[-1]}
    if len(iso_matches) == 1:
        return {"date_from": iso_matches[0], "date_to": iso_matches[0]}

    quarter_match = _QUARTER_RE.search(query)
    if quarter_match:
        quarter = quarter_match.group(1).upper()
        year = quarter_match.group(2)
        start, end = _QUARTER_RANGES[quarter]
        return {"date_from": f"{year}-{start}", "date_to": f"{year}-{end}"}

    year_match = _YEAR_ONLY_RE.search(query)
    if year_match:
        year = year_match.group(1)
        return {"date_from": f"{year}-01-01", "date_to": f"{year}-12-31"}

    return {}


def _extract_category(query: str, known_categories: list[str]) -> str | None:
    """Return the first known category found as a substring of the query, or None."""
    query_lower = query.lower()
    for cat in known_categories:
        if cat.lower() in query_lower:
            return cat
    return None


# ── Public API ────────────────────────────────────────────────────────────────


def route_query(
    query: str,
    known_categories: list[str] | None = None,
) -> RouteResult:
    """Determine routing and extract filters from the user query.

    Args:
        query:             Raw user query text (may contain leading/trailing whitespace).
        known_categories:  Category values from ``policy_documents.category`` column.
                           If ``None``, falls back to ``_DEFAULT_CATEGORIES``.

    Returns:
        ``RouteResult`` with ``route`` and ``filters`` ready to pass to the
        appropriate handler in Phase 5.
    """
    categories = known_categories or _DEFAULT_CATEGORIES
    query_stripped = query.strip()

    filters: dict[str, Any] = {}

    # Always attempt to extract dates and category regardless of route
    filters.update(_extract_dates(query_stripped))

    category = _extract_category(query_stripped, categories)
    if category:
        filters["category"] = category

    is_metadata_prefix = bool(_METADATA_PREFIX_RE.match(query_stripped))
    has_document_keyword = bool(_DOCUMENT_WORD_RE.search(query_stripped))

    if is_metadata_prefix and has_document_keyword:
        logger.debug("Router → metadata | query=%r", query_stripped)
        return RouteResult(route="metadata", filters=filters)

    logger.debug("Router → hybrid | query=%r", query_stripped)
    return RouteResult(route="hybrid", filters=filters)

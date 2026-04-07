"""Hybrid retrieval layer — Phase 4.

Public surface:
  bm25_index.build_bm25_index()   — called once from FastAPI lifespan
  hybrid_retriever.retrieve()     — main retrieval entry point for Phase 5 routes
  query_router.route_query()      — determines metadata vs hybrid path
  vector_store.get_vector_store() — returns configured VectorStoreBase instance
  reranker.rerank()               — cross-encoder re-ranking helper
"""

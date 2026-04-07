# Changelog

All notable changes to Verity are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Fixed
- `backend/app/ingestion/chunker.py` — updated import from `langchain.text_splitter`
  to `langchain_text_splitters` (LangChain 0.2+ moved splitters to a dedicated package);
  added `langchain-text-splitters>=0.2.0` to `requirements.txt` as an explicit dependency

### Fixed (pre-existing)
- `migrations/versions/0001_initial_schema.py` — create enum types only when missing (`pg_catalog`); use `postgresql.ENUM(..., create_type=False)` on all enum columns so SQLAlchemy does not emit a second `CREATE TYPE` (fixes `DuplicateObject` on `userrole`); enum `server_default` values use explicit `::typename` casts; `EXECUTE` string doubles inner quotes (`''label''`) so PostgreSQL parses `CREATE TYPE … AS ENUM (...)` correctly
- `backend/seed.py` — hash passwords with the `bcrypt` package directly (passlib 1.7 + bcrypt 4.1+ is incompatible); `requirements.txt` pins `bcrypt<4.1` so future `passlib` login code keeps working

---

## [Phase 1] — Project Structure and Environment

### Added
- Full folder scaffold: `backend/app/{models,schemas,api,core,ingestion,retrieval}/`, `backend/migrations/`, `ui/js/`, `data/`
- `backend/app/__init__.py` and package `__init__.py` files for all sub-packages
- `backend/requirements.txt` — pinned dependencies for FastAPI, SQLAlchemy, LangChain, ChromaDB, Pinecone, BM25, sentence-transformers, LangSmith, and supporting libraries
- `backend/app/config.py` — Pydantic `Settings` class loading all env vars with typed fields, defaults, and a `cors_origins_list` property
- `.env.example` — complete environment variable reference with inline documentation
- `backend/Dockerfile` — Python 3.11-slim image with system deps for psycopg2 and pdfplumber
- `docker-compose.yml` — skeleton with `db` (postgres:15) and `backend` services, healthcheck, named volumes for PostgreSQL data and ChromaDB
- `README.md` — skeleton with all section headers stubbed (Overview, Quick Start, Retrieval Design Decisions, Architecture, API Reference, Data Model, Security Notes, Deployment)
- `CHANGELOG.md` — this file

---

## [Phase 2] — Database Setup

### Added
- `backend/app/database.py` — SQLAlchemy `engine` (pool_pre_ping, pool_size=5) + `SessionLocal` + `get_db()` FastAPI dependency; reads from `settings.database_url`
- `backend/app/models/base.py` — `DeclarativeBase` subclass (`Base`) shared by all ORM models
- `backend/app/models/user.py` — `User` model: UUID PK, email (unique+indexed), bcrypt password_hash, `userrole` enum (admin/user), `userstatus` enum (active/suspended), nullable `last_active_at`
- `backend/app/models/document.py` — `PolicyDocument` model: UUID PK, file_name, category, owner_department, effective_date, chunk_count, `documentstatus` enum (queued/processing/indexed/failed), created_at (server default now()), nullable FK `uploaded_by_user_id → users.id`
- `backend/app/models/query_log.py` — `QueryLog` model: UUID PK, FK `user_id → users.id`, query_text (Text), JSON `retrieved_chunk_ids` + `relevance_scores`, date filter fields, `feedbacktype` enum (positive/negative), `response_latency_ms`, `created_at`
- `backend/app/models/__init__.py` — re-exports `Base`, `User`, `PolicyDocument`, `QueryLog` so Alembic only needs one import to discover all metadata
- `backend/alembic.ini` — Alembic config pointing to `migrations/`; sqlalchemy.url is overridden at runtime from `settings.database_url`
- `backend/migrations/env.py` — Alembic env; sets DB URL from `settings`, imports `Base` from `app.models` for autogenerate support
- `backend/migrations/script.py.mako` — standard migration template
- `backend/migrations/versions/0001_initial_schema.py` — initial migration: creates all four PostgreSQL enum types and all three tables with indexes; fully reversible `downgrade()`
- `backend/seed.py` — idempotent seed using `INSERT ... ON CONFLICT DO NOTHING`; creates `admin@verity.internal` (Admin1234!) and `user@verity.internal` (User1234!) with fixed UUIDs

---

## [Phase 3] — Document Ingestion Pipeline

### Added
- `data/manifest.json` — metadata for all 10 Nexora HR policy PDFs:
  filename, category, department (→ `owner_department`), and effective_date
- `backend/app/ingestion/pdf_extractor.py` — `extract_pages()` using pdfplumber;
  raises `IngestionError` for missing files, wrong extension, encrypted PDFs,
  and image-only PDFs that produce no extractable text; page_number attached
  as metadata to every page dict
- `backend/app/ingestion/chunker.py` — `get_splitter()` factory; returns
  `CharacterTextSplitter` (fixed) or `RecursiveCharacterTextSplitter` (recursive,
  default) based on `CHUNKING_STRATEGY` env var; reads `CHUNK_SIZE` and
  `CHUNK_OVERLAP` from settings; tradeoffs documented in module docstring
- `backend/app/ingestion/embedder.py` — `embed_and_store()` using OpenAI
  `text-embedding-3-small`; stores chunks in Chroma (local) or Pinecone (prod)
  switched via `VECTOR_STORE` env var; every chunk carries `doc_id`, `file_name`,
  `category`, `owner_department`, `effective_date`, `page_number` metadata;
  writes `chunk_count` back to `policy_documents` via SQLAlchemy update after
  successful storage; `delete_chunks()` helper exposed for Phase 5 document
  deletion and re-index routes
- `backend/app/ingestion/startup_ingestor.py` — `run_startup_ingestion()`
  called from FastAPI lifespan; reads manifest, skips already-indexed documents
  (`status = 'indexed'`), resets zombie rows (queued/processing/failed from
  crashed runs), enforces `queued → processing → indexed | failed` lifecycle;
  `uploaded_by_user_id = None` for all system-seeded documents; fully idempotent

### Design decisions recorded
- Chunking strategy tradeoff (fixed vs recursive) documented in `chunker.py`
  docstring; referenced from README "Retrieval Design Decisions" section
- `doc_id` included in every chunk's vector-store metadata so Phase 4 retrieval
  can join chunk results back to `policy_documents` rows without a full scan

---

## [Phase 4] — Hybrid Retrieval Layer

### Added
- `backend/app/retrieval/__init__.py` — package init; documents the public surface
  of the retrieval layer for Phase 5 callers
- `backend/app/retrieval/bm25_index.py` — module-level `_BM25State` singleton;
  `build_bm25_index()` fetches all chunks from the Chroma "policy_documents"
  collection via `collection.get(include=["documents","metadatas"])` and builds a
  `BM25Okapi` index using whitespace tokenisation; `search(query, top_n)` returns
  `(chunk_id, bm25_score, text, metadata)` tuples ordered descending; `is_ready()`
  and `chunk_count()` helpers for Phase 5 health endpoint
- `backend/app/retrieval/vector_store.py` — `RetrievalResult` dataclass (shared
  type across the whole retrieval layer); `VectorStoreBase` ABC; `ChromaVectorStore`
  with `_build_where()` for `$and`-composed Chroma filter clauses; `PineconeVectorStore`
  with matching Pinecone metadata filter builder; `get_vector_store()` factory;
  Chroma cosine distances converted to similarities (`1.0 − distance`)
- `backend/app/retrieval/reranker.py` — lazy `CrossEncoder` singleton
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`); `rerank(query, candidates, top_k)`
  returns candidates with `score` replaced by cross-encoder logit; model downloaded
  on first call (~100 MB — Dockerfile pre-bake noted as Phase 5 follow-up)
- `backend/app/retrieval/hybrid_retriever.py` — `HybridRetrievalResult` dataclass;
  `_reciprocal_rank_fusion()` with k=60; `_build_result_map()` merges BM25 and
  dense hits; `retrieve(query, top_k, filters)` decorated with `@_traceable` for
  LangSmith; graceful no-op if `langsmith` is not installed; returns final chunks
  plus `rrf_scores` and `reranker_scores` dicts for query-log persistence
- `backend/app/retrieval/query_router.py` — `RouteResult` dataclass; `route_query()`
  heuristic (no LLM call); routes to `"metadata"` only when query starts with
  list/show/find all/how many **and** contains the word "document"; `_extract_dates()`
  handles ISO, quarter (Q1–Q4 YYYY), and year-only patterns; `_extract_category()`
  case-insensitive substring match against `known_categories`; falls back to static
  default category list when caller passes `None`

### Design decisions recorded
- RRF over weighted-sum fusion: ranks are scale-invariant across BM25 and cosine
  similarity; no per-deployment calibration needed; documented in module docstring
  (referenced from README "Retrieval Design Decisions")
- Cross-encoder adds ~200–400 ms CPU latency for a meaningful precision gain over
  the bi-encoder retrieval stage; latency tradeoff documented in `reranker.py`
- Query router uses zero-latency keyword heuristic; routing decision is always
  logged at DEBUG level for auditability

---

## [Phase 5] — FastAPI Backend
*(to be completed)*

---

## [Phase 6] — Frontend Wiring
*(to be completed)*

---

## [Phase 7] — Evaluation and README
*(to be completed)*

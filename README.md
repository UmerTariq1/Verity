# Verity — Intelligent HR Policy Knowledge Retrieval

> A production-grade Retrieval-Augmented Generation (RAG) system for querying HR policy documents using natural language.

Built as a portfolio project demonstrating real-world hybrid retrieval engineering for Nexora GmbH (internal demo).

---

## Overview

<!-- TODO (Phase 7): Fill in — what Verity is, the domain choice, the tech stack summary -->

Verity combines:
- **Unstructured retrieval** over PDF policy documents (via vector embeddings + BM25)
- **Structured querying** of document metadata (via PostgreSQL + SQLAlchemy)
- **Hybrid re-ranking** using Reciprocal Rank Fusion and a cross-encoder model

---

## Quick Start

**First-time local setup (venv, Docker DB, migrations, ingest, BM25):** see **[docs/DEV_SETUP.md](docs/DEV_SETUP.md)** — step-by-step commands for Windows PowerShell.

### Current development workflow (pre–Phase 5 API)

The FastAPI app and `docker compose` backend service are completed in **Phase 5**. Until then, run the backend from a virtual environment:

1. Copy **`.env.example`** → **`backend/.env`**, set `OPENAI_API_KEY` and `DATABASE_URL=postgresql://verity:verity@localhost:5432/verity` for host-side Python.
2. Start only PostgreSQL: `docker compose up -d db` (from the repo root).
3. In **`backend/`**: create/activate a venv, `pip install -r requirements.txt`, `alembic upgrade head`, `python seed.py`.
4. Run ingestion and BM25 build as in **DEV_SETUP.md** (Chroma persists under `backend/chroma_db/` by default).

### After Phase 5 (full stack)

```bash
# 1. Copy environment and fill in keys (repo root or as documented in DEV_SETUP)
cp .env.example .env

# 2. Start PostgreSQL + FastAPI backend
docker compose up --build

# 3. Seed default accounts (inside the backend container)
docker compose exec backend python seed.py

# 4. Open the frontend — serve ui/ with any static server (e.g. VS Code Live Server)
#    Default credentials:
#      Admin:  admin@verity.internal / Admin1234!
#      User:   user@verity.internal  / User1234!
```

> **Note:** The `data/` folder contains Nexora HR policy PDFs and `manifest.json`. Ingestion requires a valid `OPENAI_API_KEY`. After ingest, **`build_bm25_index()`** must run (manually until Phase 5 wires it into app startup) so BM25 participates in hybrid retrieval alongside dense search and the cross-encoder re-ranker.

---

## Retrieval Design Decisions

<!-- TODO (Phase 7): This is the primary portfolio signal. Fill in with measured results. -->

### Why Hybrid Retrieval Over Pure Vector Search

### Chunking Strategy Tradeoffs

### What the Cross-Encoder Re-Ranker Adds

After BM25 and dense retrieval are fused with **Reciprocal Rank Fusion (RRF)**, a **cross-encoder** (`cross-encoder/ms-marco-MiniLM-L-6-v2`, loaded via `sentence-transformers`) scores each **(query, chunk text)** pair jointly. That improves **precision** versus bi-encoder similarity alone. The model is downloaded once on first use (~100 MB) and cached locally; expect extra CPU latency (on the order of hundreds of milliseconds) when re-ranking the candidate pool.

### What Was Tried and Dropped

---

## Architecture

<!-- TODO (Phase 7): Insert Mermaid diagram of the full retrieval pipeline -->

```
User Query → Query Router → Hybrid Retrieval → GPT-4o → Answer
                                │
                    ┌───────────┴──────────────┐
                    ▼                          ▼
              BM25 (sparse)           Dense (Chroma/Pinecone)
                    └──────── RRF Fusion ──────┘
                                    │
                           Cross-Encoder Re-Rank
```

---

## API Reference

<!-- TODO (Phase 7): Table of all endpoints -->

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/login` | None | Get JWT token |
| GET | `/api/v1/auth/me` | User | Current user info |
| POST | `/api/v1/query` | User | Submit a query |
| GET | `/api/v1/documents` | User | List documents |
| POST | `/api/v1/documents/upload` | Admin | Upload PDF |
| DELETE | `/api/v1/documents/{id}` | Admin | Delete document |
| GET | `/api/v1/users` | Admin | List users |
| GET | `/api/v1/logs` | Admin | Query logs |
| GET | `/api/v1/health` | Admin | System metrics |

---

## Data Model

<!-- TODO (Phase 7): Column descriptions for all three tables -->

| Table | Key Columns |
|-------|-------------|
| `users` | id, name, email, password_hash, role, status, last_active_at |
| `policy_documents` | id, file_name, category, owner_department, effective_date, chunk_count, status, created_at |
| `query_logs` | id, user_id, query_text, retrieved_chunk_ids, relevance_scores, feedback, response_latency_ms, created_at |

---

## Security Notes

<!-- TODO (Phase 7): localStorage JWT tradeoff, role enforcement model -->

- JWT stored in `localStorage` — documented tradeoff (XSS risk vs. simplicity for demo)
- Role enforcement is **server-side only** — frontend role checks are UX convenience, never trusted
- All admin routes require `role == "admin"` verified from JWT claim in `core/dependencies.py`

---

## Deployment

<!-- TODO (Phase 7): Render + Pinecone production setup notes -->

| Component | Platform |
|-----------|----------|
| Backend | Render (Docker) |
| PostgreSQL | Render (managed) |
| Vector Store | Pinecone |
| Frontend | Netlify / GitHub Pages |

> Render free tier has a ~30s cold start. Render PostgreSQL expires after 90 days — run `python seed.py` to restore default accounts after re-provisioning.

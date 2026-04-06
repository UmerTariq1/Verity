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

<!-- TODO (Phase 7): Fill in with final commands -->

```bash
# 1. Copy environment file and fill in your keys
cp .env.example .env

# 2. Start the full stack (PostgreSQL + FastAPI backend)
docker compose up --build

# 3. Seed default accounts
docker compose exec backend python seed.py

# 4. Open the frontend
#    Serve the ui/ folder with any static server, e.g. VS Code Live Server
#    Default credentials:
#      Admin:  admin@verity.internal / Admin1234!
#      User:   user@verity.internal  / User1234!
```

> **Note:** The `data/` folder contains 10 Nexora HR policy PDFs. On first startup, the backend auto-ingests them via `startup_ingestor.py`. This requires a valid `OPENAI_API_KEY`.

---

## Retrieval Design Decisions

<!-- TODO (Phase 7): This is the primary portfolio signal. Fill in with measured results. -->

### Why Hybrid Retrieval Over Pure Vector Search

### Chunking Strategy Tradeoffs

### What the Cross-Encoder Re-Ranker Adds

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

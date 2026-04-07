# Verity , Intelligent HR Policy Knowledge Retrieval

> A production-grade Retrieval-Augmented Generation (RAG) system for querying HR policy documents using natural language.

Built as a portfolio project demonstrating real-world hybrid retrieval engineering for Nexora GmbH (internal demo).

---

## Overview

Verity is a production-grade Retrieval-Augmented Generation (RAG) system built for querying internal HR policy documents at Nexora GmbH using natural language. It is designed as a portfolio project to demonstrate end-to-end retrieval engineering , not just "put documents in a vector store and call GPT", but a full hybrid pipeline with measurable precision improvements at each stage.

Verity combines:
- **Unstructured retrieval** over PDF policy documents (via vector embeddings + BM25)
- **Structured querying** of document metadata (via PostgreSQL + SQLAlchemy)
- **Hybrid re-ranking** using Reciprocal Rank Fusion and a cross-encoder model
- **Retrieval explainability** , every answer surface shows which chunks were retrieved, by which method, at what confidence, and which candidates were ranked out
- **Admin observability** , per-query retrieval receipts, low-confidence query detection, per-document performance tracking, and optional LangSmith trace links

---

## Quick Start

**First-time local setup (venv, Docker DB, migrations, ingest, BM25):** see **[docs/DEV_SETUP.md](docs/DEV_SETUP.md)** , step-by-step commands for Windows PowerShell.

### Current development workflow (pre–Phase 5 API)

The FastAPI app and `docker compose` backend service are completed in **Phase 5**. Until then, run the backend from a virtual environment:

1. Copy **`.env.example`** → **`backend/.env`**, set `OPENAI_API_KEY` and `DATABASE_URL=postgresql://verity:verity@localhost:5432/verity` for host-side Python.
2. Start only PostgreSQL: `docker compose up -d db` (from the repo root).
3. In **`backend/`**: create/activate a venv, `pip install -r requirements.txt`, `alembic upgrade head`, `python seed.py`.
4. Run ingestion and BM25 build as in **DEV_SETUP.md** (Chroma persists under `backend/chroma_db/` by default).

### Full stack (current)

```bash
# 1. Copy environment and fill in keys (repo root or as documented in DEV_SETUP)
cp .env.example .env

# 2. Start PostgreSQL + FastAPI backend
docker compose up --build

# 3. Seed default accounts (inside the backend container)
docker compose exec backend python seed.py

# 4. Open the frontend , serve ui/ with any static server (e.g. VS Code Live Server)
#    Navigate to ui/login_page/login_page.html
#
#    Default credentials:
#      Admin:  admin@verity.internal / Admin1234!
#      User:   user@verity.internal  / User1234!
#
#    Or sign up for a new account:
#      Open ui/signup_page/signup_page.html (linked from the login page)
```

> **Note:** The `data/` folder contains Nexora HR policy PDFs and `manifest.json`. Ingestion requires a valid `OPENAI_API_KEY`. After ingest, **`build_bm25_index()`** runs automatically on app startup to ensure BM25 participates in hybrid retrieval.

### Frontend Page Structure

| Page | Path | Access |
|------|------|--------|
| Login | `ui/login_page/login_page.html` | Public |
| Sign Up | `ui/signup_page/signup_page.html` | Public |
| Dashboard | `ui/dashboard/dashboard.html` | All users (role-based view) |
| Search | `ui/chat_interface/chat_interface.html` | All users |
| Library | `ui/document_ingestion/document_ingestion.html` | Admin only |
| Analytics | `ui/query_logs/query_logs.html` | Admin only |
| System Health | `ui/system_health/System_health.html` | Admin only |
| Users | `ui/user_management/user_management.html` | Admin only |

---

## Retrieval Design Decisions

### Why Hybrid Retrieval Over Pure Vector Search

Pure dense retrieval fails on exact-match queries , policy names, section numbers, specific dates. BM25 handles those well but struggles with paraphrased or conceptual questions. Running both in parallel and merging with RRF captures the best of both: high recall from dense search, high precision on lexical queries from BM25.

### Chunking Strategy Tradeoffs

Verity uses `RecursiveCharacterTextSplitter` (512 tokens, 64-token overlap) by default. Fixed-size chunking was tried and dropped because HR policy documents have variable sentence lengths , a fixed split often cuts mid-sentence, degrading both retrieval relevance and the readability of source previews shown to users.

### What the Cross-Encoder Re-Ranker Adds

After BM25 and dense retrieval are fused with **Reciprocal Rank Fusion (RRF)**, a **cross-encoder** (`cross-encoder/ms-marco-MiniLM-L-6-v2`, loaded via `sentence-transformers`) scores each **(query, chunk text)** pair jointly. That improves **precision** versus bi-encoder similarity alone. The model is downloaded once on first use (~100 MB) and cached locally; expect extra CPU latency (on the order of hundreds of milliseconds) when re-ranking the candidate pool.

Every chunk's source (BM25-dominant, dense-dominant, or re-ranker-promoted) is tracked and surfaced in both the user UI (method badge per source) and the admin retrieval receipt.


## Architecture

```
User Query → Query Router → Hybrid Retrieval → gpt-5-nano → Answer
                                │
                    ┌───────────┴──────────────┐
                    ▼                          ▼
              BM25 (sparse)           Dense (Chroma/Pinecone)
                    └──────── RRF Fusion ──────┘
                                    │
                           Cross-Encoder Re-Rank
                                    │
                  ┌─────────────────┴──────────────────┐
                  ▼                                     ▼
          Top-K → LLM context              Full ranked list → trace
          (selected=true)                  (method + scores per chunk)
                                                        │
                                          ┌─────────────┴──────────────┐
                                          ▼                            ▼
                                   Retrieval receipt           Rejected chunks
                                   (admin analytics)        ("didn't make the cut")
```

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/login` | None | Get JWT token |
| GET | `/api/v1/auth/me` | User | Current user profile |
| POST | `/api/v1/auth/register` | None | Self-register (creates `user` role) |
| POST | `/api/v1/query` | User | Submit a query; returns answer, sources, rejected sources, low-confidence flag |
| GET | `/api/v1/query/history` | User | Paginated personal query history |
| POST | `/api/v1/query/{id}/feedback` | User | Submit thumbs up/down on a response |
| GET | `/api/v1/documents` | User | Paginated document list with search/category filter |
| GET | `/api/v1/documents/{id}` | User | Document status (for upload polling) |
| POST | `/api/v1/documents/upload` | Admin | Upload and ingest PDF |
| DELETE | `/api/v1/documents/{id}` | Admin | Delete document and its vectors |
| POST | `/api/v1/documents/{id}/reindex` | Admin | Re-embed document from source file |
| GET | `/api/v1/users` | Admin | Paginated user list |
| POST | `/api/v1/users` | Admin | Create user |
| PATCH | `/api/v1/users/{id}` | Admin | Update role or status |
| DELETE | `/api/v1/users/{id}` | Admin | Delete user |
| GET | `/api/v1/logs` | Admin | Filtered, paginated query logs |
| GET | `/api/v1/logs/export` | Admin | Download logs as CSV |
| GET | `/api/v1/logs/{id}` | Admin | Log detail with structured retrieval receipt |
| GET | `/api/v1/logs/low-confidence` | Admin | Recent queries with avg chunk confidence < threshold |
| GET | `/api/v1/health` | Admin | System metrics |
| GET | `/api/v1/health/activity` | Admin | Recent ingestion and query activity feed |
| POST | `/api/v1/health/reindex` | Admin | Full re-embed of all indexed documents |
| GET | `/api/v1/health/document-performance` | Admin | Per-document query count and avg confidence |

---

## Data Model

| Table | Key Columns |
|-------|-------------|
| `users` | id, name, email, password_hash, role (`admin`/`user`), status (`active`/`suspended`), last_active_at |
| `policy_documents` | id, file_name, category, owner_department, effective_date, chunk_count, status (`queued`/`processing`/`indexed`/`failed`), created_at, uploaded_by_user_id |
| `query_logs` | id, user_id, query_text, filter_start_date, filter_end_date, filter_category, retrieved_chunk_ids, relevance_scores, **retrieval_trace**, **langsmith_run_id**, **langsmith_trace_url**, feedback, response_latency_ms, created_at |

`retrieval_trace` is a JSON array of `TraceEntry` objects , one per candidate chunk , storing BM25 score, dense score, RRF score, cross-encoder score, method label (`keyword_match` / `semantic_match` / `top_ranked`), and a `selected` flag indicating whether the chunk was included in the LLM context.

---

## Security Notes

- JWT stored in `localStorage` , documented tradeoff (XSS risk vs. simplicity for a demo; HttpOnly cookies would be the production choice)
- Role enforcement is **server-side only** , frontend role checks are UX convenience, never trusted
- All admin routes require `role == "admin"` verified from JWT claim in `core/dependencies.py`
- Self-deletion is blocked server-side; an admin cannot delete their own account

---

## Deployment

| Component | Platform |
|-----------|----------|
| Backend | Render (Docker) |
| PostgreSQL | Render (managed) |
| Vector Store | Pinecone |
| Frontend | Netlify / GitHub Pages |

> Render free tier has a ~30s cold start. Render PostgreSQL expires after 90 days , run `python seed.py` to restore default accounts after re-provisioning.

---

## Demo Deployment Playbook (Render + Netlify)

This app is designed to be demoed (portfolio/interview) on free tiers. The goal is **predictable demos** with a simple “warm up” routine.

### First-time setup (do this once)

#### 1) Deploy the backend on Render (Docker)

- **Service type**: Web Service
- **Runtime**: Docker
- **Root directory**: `backend/`
- **Health check**: `GET /api/v1/health`

Set these **Render environment variables** (minimum):

- **`OPENAI_API_KEY`**: required for ingestion/reindex
- **`DATABASE_URL`**: from your Render Postgres instance (Render will provide this)
- **`JWT_SECRET_KEY`**: a long random string
- **`CORS_ORIGINS`**: your Netlify site URL, plus local dev if you want (comma-separated)
  - Example: `https://your-site.netlify.app,http://localhost:8080`

Recommended for hosted demos:

- **`VECTOR_STORE=pinecone`** (vectors persist across restarts)
- **Pinecone env vars** (as defined in `.env.example`) so retrieval works after sleep/redeploy
- **`BM25_BUILD_ON_STARTUP=false`** (prevents Render free tier OOM; dense retrieval still works)

After the backend is live:

- **DB migrations run automatically on startup** (see `backend/entrypoint.sh`)
- **Seed default accounts** (optional): if you want the default demo users, run `python seed.py` once (locally against Render Postgres, or in any environment where you can reach the DB)

You should now be able to visit `GET /api/v1/health` and see a JSON response.

#### 2) Deploy the frontend on Netlify (static)

Netlify should publish the `ui/` folder as static files.

##### Make the UI work for everyone (no per-browser setup)

This repo is set up to proxy API requests through Netlify so the browser calls:

- `https://your-site.netlify.app/api/v1/...` (same origin)

and Netlify forwards them to your Render backend.

To enable that, update the placeholder in `ui/_redirects`:

- Replace `https://YOUR-RENDER-SERVICE.onrender.com` with your real Render backend URL

Then redeploy Netlify.

---

### “Interview warm-up” checklist (every time)

Do this **10–15 minutes before** a call so you don’t get surprised by free-tier cold starts.

- **Open the Netlify site** (instant)
- **Wake the backend** by loading the Search page (or hit `GET /api/v1/health`)
  - Render free tier may take ~30s the first time
- **Sign in as admin**
  - Default: `admin@verity.internal` / `Admin1234!` (if you ran `seed.py`)
- **(Optional) Fresh rebuild**: go to **System Health → Reindex** and confirm
  - Only do this if you changed documents / Pinecone index / ingestion settings
- **Run 1 test query** (verifies auth + DB + retrieval + LLM)

During the interview/demo, you should not need reindexing , just query normally.

---

### Troubleshooting (fast)

- **UI loads but API calls fail**: confirm `ui/_redirects` points to your Render backend and Netlify redeployed
- **CORS error in browser console**: if you're using the Netlify proxy (`/api/*`), you typically won't hit CORS; if you call Render directly, add your Netlify URL to `CORS_ORIGINS`
- **Reindex fails immediately**: confirm `OPENAI_API_KEY` is set in Render env vars

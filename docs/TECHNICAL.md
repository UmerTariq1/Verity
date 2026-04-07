# Verity , Technical Reference

---

## Retrieval Design

### Why Hybrid Retrieval

Pure dense (vector) retrieval fails on exact-match queries , policy names, section numbers, specific dates. BM25 handles those well but struggles with paraphrased or conceptual questions. Running both in parallel and merging with **Reciprocal Rank Fusion (RRF)** captures the best of both.

### Chunking Strategy

Uses `RecursiveCharacterTextSplitter` (512 tokens, 64-token overlap). Fixed-size chunking was dropped because HR policy documents have variable sentence lengths , a fixed split often cuts mid-sentence, degrading both retrieval relevance and source preview readability.

### Cross-Encoder Re-Ranker

After BM25 + dense retrieval are fused with RRF, a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) scores each **(query, chunk)** pair jointly. This improves precision versus bi-encoder similarity alone. The model is downloaded once on first use (~100 MB) and cached locally. Expect ~hundreds of milliseconds of extra CPU latency when re-ranking.

Every chunk's source (`keyword_match` / `semantic_match` / `top_ranked`) is tracked and surfaced in the UI and in admin retrieval receipts.

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
| `query_logs` | id, user_id, query_text, filter_start_date, filter_end_date, filter_category, retrieved_chunk_ids, relevance_scores, retrieval_trace, langsmith_run_id, langsmith_trace_url, feedback, response_latency_ms, created_at |

`retrieval_trace` is a JSON array of `TraceEntry` objects , one per candidate chunk , storing BM25 score, dense score, RRF score, cross-encoder score, method label, and a `selected` flag indicating whether the chunk was passed to the LLM.

---

## Frontend Pages

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

## Security Notes

- JWT is stored in `localStorage` , documented tradeoff (XSS risk vs. simplicity for a demo; HttpOnly cookies would be the production choice)
- Role enforcement is **server-side only** , frontend role checks are UX convenience only, never trusted
- All admin routes require `role == "admin"` verified from JWT claim in `core/dependencies.py`
- Self-deletion is blocked server-side; an admin cannot delete their own account

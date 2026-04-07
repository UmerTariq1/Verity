# Verity , first-time developer setup (local)

Commands below assume **Windows** and **PowerShell**. Adjust paths if your clone lives elsewhere.

**What this gets you:** PostgreSQL running in Docker, Python virtualenv with dependencies, database schema + seed users, PDFs ingested into Chroma, BM25 index built , ready to run retrieval smoke tests or future FastAPI (Phase 5).

---

## 1. Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for PostgreSQL)
- Python **3.11+**
- An [OpenAI API key](https://platform.openai.com/) (embeddings; required for ingestion and dense retrieval)

---

## 2. Environment file

1. Copy the template:

   ```powershell
   cd "c:\side projects\Verity"
   copy .env.example backend\.env
   ```

2. Edit **`backend\.env`** (Pydantic loads `.env` from the **current working directory** when you run Python from `backend\`):

   | Variable | Local dev value |
   |----------|------------------|
   | `OPENAI_API_KEY` | Your key |
   | `DATABASE_URL` | `postgresql://verity:verity@localhost:5432/verity` |
   | `VECTOR_STORE` | `chroma` (default) |
   | `CHROMA_PERSIST_DIR` | `./chroma_db` (default; folder is created on first ingest) |

Keep other vars as in `.env.example` unless you know you need to change them.

---

## 3. Start PostgreSQL only

From the **repository root** (where `docker-compose.yml` lives):

```powershell
cd "c:\side projects\Verity"
docker compose up -d db
```

Wait until the `db` container is healthy (`docker compose ps`).

---

## 4. Python virtual environment

```powershell
cd "c:\side projects\Verity\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

Activate the venv in **every new terminal** before backend commands:

```powershell
cd "c:\side projects\Verity\backend"
.\.venv\Scripts\Activate.ps1
```

---

## 5. Database migrations and seed users

Still in **`backend`** with the venv activated:

```powershell
$env:PYTHONPATH = "."
alembic upgrade head
python seed.py
```

Default accounts (from `seed.py`):

- **Admin:** `admin@verity.internal` / `Admin1234!`
- **User:** `user@verity.internal` / `User1234!`

---

## 6. Ingest PDFs (creates `chroma_db/`)

Ingestion writes vectors under **`backend\chroma_db`** when `CHROMA_PERSIST_DIR=./chroma_db` and you run commands from `backend\`.

```powershell
$env:PYTHONPATH = "."
python -c "from app.ingestion.startup_ingestor import run_startup_ingestion; run_startup_ingestion()"
```

Requires `data\manifest.json` and the PDFs under **`data\`** (paths are resolved relative to the repo layout).

---

## 7. Build the BM25 index (sparse retrieval)

Hybrid retrieval expects this after Chroma has chunks. **Phase 5** will call it from the app lifespan; until then, run it manually after ingest:

```powershell
$env:PYTHONPATH = "."
python -c "from app.retrieval.bm25_index import build_bm25_index, chunk_count; build_bm25_index(); print('BM25 chunks:', chunk_count())"
```

`chunk_count()` should be **greater than zero** before you rely on the BM25 leg.

---

## 8. Optional: hybrid retrieval smoke test

First run downloads the cross-encoder (~100 MB, cached afterward):

```powershell
$env:PYTHONPATH = "."
python -c @"
from app.retrieval.bm25_index import build_bm25_index, is_ready
from app.retrieval.hybrid_retriever import retrieve
from app.retrieval.query_router import route_query

build_bm25_index()
print('BM25 ready:', is_ready())

q = 'What is the probation period?'
r = route_query(q)
print('route:', r.route, 'filters:', r.filters)
out = retrieve(q, top_k=3, filters=r.filters)
for c in out.chunks:
    print(c.file_name, 'page', c.page_number, round(c.score, 4))
"@
```

If you see `BM25 search called but index is not ready`, you skipped step 7 in **this** shell or ingest produced no chunks.

---

## 9. Full Docker stack (when Phase 5 ships the API)

When `backend/app/main.py` and the Docker image entrypoint exist, the root **README** quick start will apply: `docker compose up --build`, then seed inside the backend container. Until then, use **sections 3–8** for local development.

---

## Troubleshooting

| Symptom | Check |
|--------|--------|
| `ModuleNotFoundError` | Venv activated? `pip install -r requirements.txt` from `backend`? |
| DB connection errors | `docker compose ps` , is `db` up? `DATABASE_URL` uses `localhost` (not `db`) when Python runs on the host |
| Empty Chroma / BM25 zero chunks | Ingestion errors in logs; confirm PDF paths and `OPENAI_API_KEY` |
| `.env` ignored | Run Python from **`backend`** with **`backend\.env`** present, or export variables explicitly |

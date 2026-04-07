# Verity

> AI-powered HR policy knowledge retrieval , ask questions in plain English, get answers backed by your actual policy documents.

Designed for mid-size organisations like "Nexora KR", a persona company, where HR policy lives in PDFs nobody reads.

---

## What it does

Verity lets employees ask natural-language questions against internal HR policy documents. Instead of keyword search or digging through shared drives, it uses a hybrid retrieval pipeline, combining BM25, vector embeddings, and a cross-encoder re-ranker , so every answer is grounded in the actual source documents, with citations shown for every response.

Admins get a full observability layer: per-query retrieval traces, confidence monitoring, per-document performance stats, and complete user management.

---

## Architecture

![System Architecture and Deployment](data/assets/imgs/architecture%20and%20deployment%20diagram.png)
*Figure 1 , End-to-end system and Deployment architecture*

![Retrieval Pipeline](data/assets/imgs/architecture.png)
*Figure 2 , Hybrid retrieval pipeline (BM25 + Dense → RRF → Cross-Encoder)*

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python) |
| Database | PostgreSQL (SQLAlchemy + Alembic) |
| Vector Store | Pinecone |
| Embeddings + LLM | OpenAI |
| Re-Ranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Frontend | Vanilla HTML/CSS/JS |
| Hosting | Render (backend) · Netlify (frontend) |

---

## Getting Started

**Local development setup:** [docs/DEV_SETUP.md](docs/DEV_SETUP.md)

**Deploying to Render + Netlify:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

**Restarting after free-tier sleep/expiry:** [docs/RESTART_GUIDE.md](docs/RESTART_GUIDE.md)

---

## Default Demo Credentials

| Role | Name | Email | Password |
|------|------|-------|----------|
| Admin | Albus | `albus@verity.internal` | `Admin1234!` |
| User | Alice | `alice@verity.internal` | `User1234!` |
| User | Bob | `bob@verity.internal` | `User1234!` |

> These are created by `seed.py` (idempotent — safe to run multiple times). See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for setup.

---

## Docs

| Document | Contents |
|----------|----------|
| [DEV_SETUP.md](docs/DEV_SETUP.md) | Local setup, migrations, ingestion |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Render + Netlify deploy guide |
| [RESTART_GUIDE.md](docs/RESTART_GUIDE.md) | Restarting after free-tier shutdown |
| [TECHNICAL.md](docs/TECHNICAL.md) | API reference, data model, retrieval design, security |

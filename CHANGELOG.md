# Changelog

All notable changes to Verity are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

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
*(to be completed)*

---

## [Phase 3] — Document Ingestion Pipeline
*(to be completed)*

---

## [Phase 4] — Hybrid Retrieval Layer
*(to be completed)*

---

## [Phase 5] — FastAPI Backend
*(to be completed)*

---

## [Phase 6] — Frontend Wiring
*(to be completed)*

---

## [Phase 7] — Evaluation and README
*(to be completed)*

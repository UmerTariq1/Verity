# Intelligent Knowledge Retrieval System
**Business Requirements Document (BRD)**  
Version: 1.0  
Date: April 2026  
Purpose: Portfolio Build (Upwork Primary)

---

## 1. What We Are Building

A production-grade Retrieval-Augmented Generation (RAG) application that enables users to query a document knowledge base using natural language.

### Key Idea
- Combines **unstructured retrieval (PDFs)** with **structured querying (metadata via SQL)**
- Designed as a **portfolio project demonstrating real engineering decisions**, not a tutorial

---

## 2. Domain Choice: HR Policy & Compliance

### Why this domain?

- **Relatable**
  - Every company has HR policies
- **Hybrid data**
  - Mix of PDFs + structured metadata
- **Germany-relevant**
  - Works councils, GDPR, labour laws

---

## 3. Tech Stack

### Ingestion
- Python
- PyPDF2 / pdfplumber
- LangChain text splitters

### Embeddings
- OpenAI `text-embedding-3-small`
- Optional: sentence-transformers (local)

### Vector Store
- Chroma (local)
- Pinecone (hosted)

### Structured Data
- PostgreSQL + SQLAlchemy

### Retrieval
- Hybrid:
  - BM25 (sparse)
  - Dense embeddings
  - Cross-encoder re-ranking

### LLM
- gpt-5-nano

### Backend
- FastAPI (Dockerised)

### Frontend
- Vanilla HTML/CSS/JS
- Tailwind (CDN)

### Auth
- JWT + bcrypt

### Observability
- LangSmith
- Retrieval logging

---

## 4. Key Architectural Decisions

### Why NOT no-code tools?
- n8n targets lower-budget clients
- Python stack signals senior engineering

### Why NOT React/Next.js?
- Slower setup
- More overhead
- Vanilla JS keeps demo lightweight and readable

### Auth Choice
- Username/password + JWT
- No OAuth (avoids setup overhead for demo)

---

## 5. Stakeholders

| Role | Description |
|------|------------|
| Knowledge Manager | Admin managing documents |
| Employee / User | Queries system |
| Portfolio Owner | Builder (Umer) |
| Client / Recruiter | Evaluates project |

---

## 6. Features

### Admin
- Upload PDFs (single/batch)
- Delete/update documents
- View query logs
- Trigger re-indexing

### User
- Natural language queries
- View cited sources
- Filter by category/date
- Export answers

### Both
- JWT login/logout
- Feedback on answers

---

## 7. Data Model

### Users
- id (UUID)
- name
- email (unique)
- password_hash (bcrypt)
- role (admin/user)
- status
- last_active_at

### Policy Documents
- id
- file_name
- category
- owner_department
- effective_date
- chunk_count
- status

### Query Logs
- id
- user_id
- query_text
- retrieved_chunk_ids
- relevance_scores
- date filters
- feedback
- created_at

### Important Decision
- **AI response text is NOT stored**
  - Avoids database bloat
  - Focuses on retrieval evaluation

---

## 8. Build Phases

1. Data ingestion + chunking strategies
2. Embedding + vector store
3. Hybrid retrieval (BM25 + dense + reranking)
4. Structured data integration (PostgreSQL)
5. Backend + auth (FastAPI)
6. Custom frontend
7. Evaluation + README

---

## 9. Critical Portfolio Signal

### Retrieval Design Decisions

The README must clearly explain:
- Why hybrid retrieval over pure vector search
- Chunking strategy tradeoffs
- Measured performance differences

**This is the key differentiator of the project.**

---

## 10. Deployment

| Component | Platform |
|----------|---------|
| Backend | Render |
| PostgreSQL | Render |
| Vector Store | Pinecone |
| Frontend | Netlify / GitHub Pages |

### Notes
- Render backend sleeps (cold start ~30s)
- PostgreSQL expires after 90 days
- Seed script required for restoration

---

## Final Note

This project is designed to demonstrate:
- Real-world RAG architecture
- Thoughtful engineering tradeoffs
- Production-grade system design

The README is the primary portfolio artifact — the code supports it.

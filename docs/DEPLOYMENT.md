# Deployment Guide , Render + Netlify

This is a one-time setup. Once done, you only need [RESTART_GUIDE.md](RESTART_GUIDE.md) for day-to-day use.

---

## 1. Deploy the backend on Render

- **Service type**: Web Service
- **Runtime**: Docker
- **Root directory**: `backend/`
- **Health check path**: `/api/v1/health`

### Required environment variables

| Variable | Value |
|----------|-------|
| `OPENAI_API_KEY` | Your OpenAI key |
| `DATABASE_URL` | Provided by Render Postgres |
| `JWT_SECRET_KEY` | Any long random string |
| `CORS_ORIGINS` | Your Netlify URL (e.g. `https://your-site.netlify.app`) |

### Recommended for free-tier demos

| Variable | Value | Why |
|----------|-------|-----|
| `VECTOR_STORE` | `pinecone` | Vectors persist across restarts |
| `PINECONE_API_KEY` | Your Pinecone key | Required if using Pinecone |
| `PINECONE_INDEX_NAME` | Your index name | Required if using Pinecone |
| `BM25_BUILD_ON_STARTUP` | `false` | Prevents OOM on Render free tier |
| `SEED_ON_STARTUP` | `true` | Creates default demo users on deploy |

> **Security note:** `SEED_ON_STARTUP=true` creates accounts with known credentials (`admin@verity.internal` / `Admin1234!`). Use only for portfolio demos.

### What happens on first deploy

- DB migrations run automatically via `entrypoint.sh`
- Default accounts are seeded if `SEED_ON_STARTUP=true`
- Visit `GET /api/v1/health` to confirm the backend is live

---

## 2. Deploy the frontend on Netlify

- **Publish directory**: `ui/`
- No build command needed (pure static files)

### Point the frontend at your backend

Open `ui/_redirects` and replace the placeholder URL with your actual Render backend URL:

```
/api/*  https://YOUR-RENDER-SERVICE.onrender.com/api/:splat  200
```

Redeploy Netlify after saving. This proxy setup means the browser always calls your Netlify domain , no CORS issues.

---

## 3. Verify everything works

1. Open your Netlify site
2. Hit `GET /api/v1/health` (allow ~30s for Render cold start)
3. Log in as `admin@verity.internal` / `Admin1234!`
4. Run a test query

---

## Pre-demo checklist (10–15 min before a call)

- [ ] Open the Netlify site
- [ ] Hit the Search page or `/api/v1/health` to wake Render (~30s cold start)
- [ ] Sign in as admin and confirm the dashboard loads
- [ ] Run 1 test query end-to-end
- [ ] Only reindex (System Health → Reindex) if you changed documents or Pinecone settings

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| UI loads but API calls fail | Check `ui/_redirects` points to the correct Render URL; redeploy Netlify |
| CORS error in browser console | If calling Render directly (not via Netlify proxy), add your Netlify URL to `CORS_ORIGINS` |
| Reindex fails immediately | Confirm `OPENAI_API_KEY` is set in Render env vars |
| Login fails after Postgres expiry | Re-provision Postgres on Render; run `python seed.py` to restore accounts |

## Quick Run
If you have render and netlify running then just run this command : from backend folder :
`$env:DATABASE_URL="<external database url from render db service>"; python .\seed.py`
It will create the seed users.
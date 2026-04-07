# Restarting Verity After Free-Tier Shutdown

Verity runs on three free-tier services that can go to sleep or expire. This guide covers how to bring everything back up.

---

## Know Your Services

| Service | What it does | Free-tier behaviour |
|---------|-------------|---------------------|
| **Render** | Hosts the backend | Sleeps after ~15 min of inactivity; ~30s cold start to wake |
| **Render Postgres** | Stores users, documents, query logs | **Expires and is deleted after 90 days** |
| **Pinecone** | Stores document vectors (embeddings) | Indexes are retained; free tier has storage/request limits |

---

## Scenario A , Backend just went to sleep (most common)

This happens if no one has used the app in ~15 minutes. Nothing is lost.

**Fix:**

1. Open your Netlify site and go to the Search page
2. Wait up to 30 seconds for the backend to wake up
3. Done , log in and use normally

---

## Scenario B , Render Postgres expired (every ~90 days)

Render deletes free Postgres instances after 90 days. You'll see login errors or 500s.

**Steps to restore:**

1. **Go to Render → your Postgres service**
   - If it says "Expired" or is deleted, create a new Postgres instance
   - Copy the new `DATABASE_URL` from the Render dashboard

2. **Update the environment variable on Render**
   - Go to your backend Web Service → Environment
   - Update `DATABASE_URL` with the new value
   - Click "Save Changes" , Render will redeploy automatically

3. **Wait for the backend to redeploy** (~1–2 min)
   - Visit `https://your-backend.onrender.com/api/v1/health`
   - DB migrations run automatically on startup (no action needed)

4. **Restore default accounts**
   - If `SEED_ON_STARTUP=true` is set, accounts are already restored after the redeploy
   - If not, run locally:
     ```bash
     cd backend
     python seed.py
     ```
   - Or temporarily set `SEED_ON_STARTUP=true` in Render env vars, trigger a redeploy, then set it back to `false`

5. **Test login**
   - Open the Netlify site
   - Log in as `admin@verity.internal` / `Admin1234!`

> **Note:** Query history and uploaded document metadata (stored in Postgres) will be lost after a Postgres expiry. Pinecone vectors are unaffected , documents are still searchable.

---

## Scenario C , Pinecone index was deleted or cleared

If queries return no results or throw errors about the index, the Pinecone index may need to be recreated.

**Steps to restore:**

1. **Log in to [pinecone.io](https://pinecone.io)** and check if your index exists
   - If it's gone, create a new index with the same name and dimension (1536 for OpenAI `text-embedding-3-small`)

2. **Confirm env vars on Render**
   - `PINECONE_API_KEY` , your Pinecone API key
   - `PINECONE_INDEX_NAME` , matches the index you just created

3. **Reindex all documents**
   - Log in to Verity as admin
   - Go to **System Health → Reindex All**
   - This re-embeds every indexed document and pushes vectors to Pinecone
   - Depending on how many documents you have, this may take a few minutes

4. **Run a test query** to confirm retrieval is working

---

## Scenario D , Full reset (everything is gone)

If both Postgres and Pinecone need to be recreated from scratch:

1. Follow **Scenario B** (steps 1–5) to restore the database
2. Follow **Scenario C** (steps 1–4) to restore vectors
3. **Re-upload documents** via the Library page (Admin → Library → Upload PDF) if the files themselves were lost

---

## Quick health check

Visit this URL to see if the backend is up and what's connected:

```
https://your-backend.onrender.com/api/v1/health
```

A healthy response looks like:

```json
{
  "status": "ok",
  "database": "connected",
  "vector_store": "connected",
  ...
}
```

If `database` or `vector_store` shows an error, use the relevant scenario above.

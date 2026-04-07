/**
 * config.js , Frontend runtime configuration.
 *
 * Goal: "start the servers and anyone can use it" (no per-browser setup).
 *
 * In production on Netlify, we use a same-origin proxy:
 *   Browser -> https://your-site.netlify.app/api/v1/... -> Netlify proxy -> Render backend
 *
 * So the default API base is just `/api/v1`.
 * For local dev (UI on :8080, API on :8000), we fall back to `http://localhost:8000/api/v1`.
 */
(() => {
  const isLocal =
    location.hostname === "localhost" || location.hostname === "127.0.0.1";

  const apiBase = isLocal ? "http://localhost:8000/api/v1" : "/api/v1";
  window.VERITY_API_BASE = apiBase;
})();


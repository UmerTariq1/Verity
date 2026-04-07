/**
 * config.js — Frontend runtime configuration.
 *
 * Netlify/GitHub Pages are static hosts, so we can't inject env vars at runtime.
 * Instead, we read a persisted API base URL from localStorage.
 *
 * - Default: localhost (for local dev)
 * - Hosted demo: set once in the browser via localStorage (documented in README)
 */
(() => {
  const DEFAULT_API_BASE = "http://localhost:8000/api/v1";

  // Allow override via localStorage (recommended for hosted demos).
  const stored = localStorage.getItem("verity_api_base");
  const apiBase = (stored && stored.trim()) ? stored.trim() : DEFAULT_API_BASE;

  // Expose as a global consumed by api.js.
  window.VERITY_API_BASE = apiBase;
})();


/**
 * api.js — Shared fetch wrapper for Verity frontend.
 *
 * - Reads JWT from localStorage and attaches Authorization header.
 * - On 401 (expired / invalid token), clears storage and redirects to login.
 * - Handles JSON, CSV blob, and FormData bodies transparently.
 * - All pages that need API access load this file before their own script.
 *
 * Usage:
 *   const data = await apiFetch("/query", { method: "POST", body: JSON.stringify(payload) });
 */

const API_BASE = "http://localhost:8000/api/v1";

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("verity_token");

  // Never set Content-Type for FormData — browser adds boundary automatically.
  const isFormData = options.body instanceof FormData;
  const headers = { ...(options.headers || {}) };

  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new Error(
      "Cannot reach the backend. Make sure the server is running on port 8000."
    );
  }

  // Only redirect on 401 if a token exists (i.e. token expired mid-session).
  // A 401 with no stored token means the call was made without auth on purpose.
  if (res.status === 401 && token) {
    localStorage.removeItem("verity_token");
    localStorage.removeItem("verity_user");
    window.location.href = "../login_page/login_page.html";
    return null;
  }

  // 204 No Content — successful but nothing to parse.
  if (res.status === 204) return null;

  const contentType = res.headers.get("content-type") || "";

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    if (contentType.includes("application/json")) {
      const body = await res.json().catch(() => ({}));
      message = body.detail || message;
    } else {
      const text = await res.text().catch(() => "");
      if (text) message = text;
    }
    throw new Error(message);
  }

  // Return blob for CSV / binary downloads.
  if (
    contentType.includes("text/csv") ||
    contentType.includes("application/octet-stream")
  ) {
    return res.blob();
  }

  return res.json();
}

/**
 * Trigger a browser file download from a Blob.
 * @param {Blob} blob
 * @param {string} filename
 */
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

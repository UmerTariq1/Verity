/**
 * auth.js , Authentication helpers for Verity frontend.
 *
 * Token contract (set by login_page.html on successful login):
 *   localStorage["verity_token"] = "<jwt string>"
 *   localStorage["verity_user"]  = JSON.stringify({ name, role, user_id })
 *
 * Guard usage (call at top of DOMContentLoaded in each protected page):
 *   if (!guardAuth()) return;          // any authenticated user
 *   if (!guardAdmin()) return;         // admin-only pages
 */

/** @returns {{ name: string, role: string, user_id: string } | null} */
function getUser() {
  try {
    const raw = localStorage.getItem("verity_user");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** @returns {boolean} */
function isAuthenticated() {
  return !!localStorage.getItem("verity_token");
}

/**
 * Redirect to login if no token present.
 * @returns {boolean} true if authenticated, false if redirected
 */
function guardAuth() {
  if (!isAuthenticated()) {
    window.location.href = "../login_page/login_page.html";
    return false;
  }
  return true;
}

/**
 * Redirect non-admins to dashboard.
 * Implicitly calls guardAuth first.
 * @returns {boolean} true if user is admin
 */
function guardAdmin() {
  if (!guardAuth()) return false;
  const user = getUser();
  if (!user || user.role !== "admin") {
    window.location.href = "../dashboard/dashboard.html";
    return false;
  }
  return true;
}

/** Clear session and go to login page. */
function logout() {
  localStorage.removeItem("verity_token");
  localStorage.removeItem("verity_user");
  window.location.href = "../login_page/login_page.html";
}

/**
 * Convert a raw cross-encoder logit score to a [0,1] probability via sigmoid.
 * Cross-encoder/ms-marco models output unbounded logits; sigmoid normalises them.
 * @param {number} x
 * @returns {number}
 */
function applyScoreSigmoid(x) {
  return 1 / (1 + Math.exp(-x));
}

/**
 * Wire sidebar nav links and the logout button.
 * Pass `activePage` to highlight the correct nav item via data-page attribute.
 *
 * @param {"dashboard"|"search"|"library"|"analytics"|"health"|"users"} activePage
 */
function wireNav(activePage) {
  const user = getUser();
  const isAdmin = user?.role === "admin";

  // Map page keys to their paths (relative to any ui/<folder>/ page).
  const links = {
    dashboard: "../dashboard/dashboard.html",
    search:    "../chat_interface/chat_interface.html",
    library:   "../document_ingestion/document_ingestion.html",
    analytics: "../query_logs/query_logs.html",
    health:    "../system_health/System_health.html",
    users:     "../user_management/user_management.html",
  };

  // Wire all elements that carry a data-nav attribute.
  document.querySelectorAll("[data-nav]").forEach((el) => {
    const key = el.dataset.nav;
    if (links[key]) {
      if (el.tagName === "A") {
        el.href = links[key];
      } else {
        // Non-anchor elements (e.g. logo div): make them navigable on click.
        el.style.cursor = "pointer";
        el.addEventListener("click", () => { window.location.href = links[key]; });
      }
    }

    // Apply active highlight.
    if (key === activePage) {
      el.classList.add("bg-teal-50", "text-teal-700", "border-l-4", "border-teal-600");
      el.classList.remove("text-slate-500");
    }
  });

  // Hide admin-only nav items for non-admins.
  if (!isAdmin) {
    document.querySelectorAll("[data-admin-nav]").forEach((el) => {
      el.style.display = "none";
    });
  }

  // Wire logout buttons / links.
  document.querySelectorAll("[data-logout]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      logout();
    });
  });

  // Populate user name wherever a [data-user-name] element exists.
  const nameEls = document.querySelectorAll("[data-user-name]");
  if (user && nameEls.length) {
    nameEls.forEach((el) => {
      el.textContent = user.name;
      // Wire profile modal on the name element.
      el.style.cursor = "pointer";
      el.addEventListener("click", (e) => {
        e.preventDefault();
        showProfileModal();
      });
    });
  }

  // Show role badge wherever [data-user-role] exists.
  const roleEls = document.querySelectorAll("[data-user-role]");
  if (user && roleEls.length) {
    roleEls.forEach((el) => {
      el.textContent = user.role === "admin" ? "Administrator" : "User";
    });
  }
}

/**
 * Show a slide-in profile modal with the current user's details.
 * Fetches fresh data from GET /api/v1/auth/me.
 */
function showProfileModal() {
  // Remove any existing modal.
  document.getElementById("verity-profile-modal")?.remove();

  const modal = document.createElement("div");
  modal.id = "verity-profile-modal";
  modal.className = "fixed inset-0 z-[200] flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm";
  modal.innerHTML = `
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-8 relative">
      <button id="profile-modal-close"
              class="absolute top-4 right-4 w-9 h-9 flex items-center justify-center rounded-full hover:bg-surface-container text-on-surface-variant transition-colors">
        <span class="material-symbols-outlined">close</span>
      </button>
      <div class="flex flex-col items-center text-center mb-8">
        <div id="pm-avatar"
             class="w-20 h-20 rounded-2xl bg-teal-100 text-teal-700 flex items-center justify-center font-bold text-3xl mb-4">
          …
        </div>
        <h3 id="pm-name" class="text-xl font-bold text-on-surface font-headline">,</h3>
        <p id="pm-email" class="text-sm text-on-surface-variant mt-1">,</p>
        <span id="pm-role"
              class="mt-3 px-4 py-1 bg-teal-50 text-teal-700 rounded-full text-xs font-bold uppercase tracking-widest">,</span>
      </div>
      <div class="grid grid-cols-2 gap-4 mb-8">
        <div class="p-4 bg-surface-container-low rounded-xl">
          <p class="text-[10px] uppercase font-bold text-on-surface-variant tracking-wider mb-1">Account Status</p>
          <p id="pm-status" class="text-sm font-semibold text-on-surface">,</p>
        </div>
        <div class="p-4 bg-surface-container-low rounded-xl">
          <p class="text-[10px] uppercase font-bold text-on-surface-variant tracking-wider mb-1">Last Active</p>
          <p id="pm-last-active" class="text-sm font-semibold text-on-surface">,</p>
        </div>
      </div>
      <button id="pm-logout-btn"
              class="w-full py-3 bg-error/10 text-error rounded-xl font-bold hover:bg-error/20 transition-colors flex items-center justify-center gap-2">
        <span class="material-symbols-outlined text-lg">logout</span>
        Sign out
      </button>
    </div>
  `;

  document.body.appendChild(modal);

  modal.querySelector("#profile-modal-close").addEventListener("click", () => modal.remove());
  modal.querySelector("#pm-logout-btn").addEventListener("click", () => logout());
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });

  // Populate with data from /auth/me.
  apiFetch("/auth/me").then((data) => {
    if (!data) return;
    const initials = data.name
      ? data.name.trim().split(/\s+/).map(w => w[0]).join("").toUpperCase().slice(0, 2)
      : "?";
    modal.querySelector("#pm-avatar").textContent = initials;
    modal.querySelector("#pm-name").textContent   = data.name || ",";
    modal.querySelector("#pm-email").textContent  = data.email || ",";
    modal.querySelector("#pm-role").textContent   = data.role === "admin" ? "Administrator" : "User";
    modal.querySelector("#pm-status").textContent = data.status === "active" ? "Active" : "Suspended";
    modal.querySelector("#pm-last-active").textContent = data.last_active_at
      ? new Date(data.last_active_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
      : "Never";
  }).catch(() => {
    modal.querySelector("#pm-name").textContent = "Failed to load profile";
  });
}

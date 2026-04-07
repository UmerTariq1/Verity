/**
 * toast.js — Lightweight top-right toast notifications.
 *
 * Injects a container div into <body> on first call.
 * Matches the existing toast markup in user_management.html.
 *
 * @param {string} message   Primary bold line.
 * @param {"success"|"error"|"warning"} type
 * @param {string} [detail]  Optional sub-line (smaller text).
 * @param {number} [duration] Auto-dismiss delay in ms (default 4000).
 */
function showToast(message, type = "success", detail = "", duration = 4000) {
  let container = document.getElementById("verity-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "verity-toast-container";
    container.className =
      "fixed top-8 right-8 z-[9999] flex flex-col gap-3 pointer-events-none";
    document.body.appendChild(container);
  }

  const styles = {
    success: { bg: "bg-teal-600",  icon: "check_circle"  },
    error:   { bg: "bg-[#ba1a1a]", icon: "error_outline"  },
    warning: { bg: "bg-amber-500", icon: "warning"        },
  };

  const { bg, icon } = styles[type] ?? styles.success;

  const toast = document.createElement("div");
  toast.className = [
    bg,
    "text-white px-6 py-4 rounded-xl shadow-2xl",
    "flex items-center gap-4",
    "translate-x-[calc(100%+32px)] transition-transform duration-500",
    "pointer-events-auto",
  ].join(" ");

  toast.innerHTML = `
    <div class="w-8 h-8 bg-white/20 rounded-lg flex items-center justify-center shrink-0">
      <span class="material-symbols-outlined text-white"
            style="font-variation-settings:'FILL' 1;">${icon}</span>
    </div>
    <div class="flex-1 min-w-0">
      <p class="font-bold leading-tight" style="font-family: Manrope, sans-serif;">
        ${escapeToastHtml(message)}
      </p>
      ${detail ? `<p class="text-xs text-white/80 mt-0.5">${escapeToastHtml(detail)}</p>` : ""}
    </div>
    <button class="ml-2 text-white/60 hover:text-white shrink-0 verity-toast-close">
      <span class="material-symbols-outlined text-sm">close</span>
    </button>
  `;

  container.appendChild(toast);

  // Dismiss on close button click.
  toast.querySelector(".verity-toast-close").addEventListener("click", () =>
    dismissToast(toast)
  );

  // Animate in after one paint.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      toast.classList.remove("translate-x-[calc(100%+32px)]");
      toast.classList.add("translate-x-0");
    })
  );

  // Auto-dismiss.
  if (duration > 0) {
    setTimeout(() => dismissToast(toast), duration);
  }
}

function dismissToast(toast) {
  toast.classList.remove("translate-x-0");
  toast.classList.add("translate-x-[calc(100%+32px)]");
  setTimeout(() => toast.remove(), 500);
}

function escapeToastHtml(str) {
  const d = document.createElement("div");
  d.textContent = String(str);
  return d.innerHTML;
}

"use strict";

const viewButtons = document.querySelectorAll("[data-view]");
const views = { workspace: document.getElementById("workspace-view"), campaign: document.getElementById("campaign-view") };

function showView(name) {
  if (!views[name]) return;
  Object.entries(views).forEach(([key, section]) => { section.hidden = key !== name; });
  document.querySelectorAll("nav [data-view]").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.getElementById("page-label").textContent = name === "campaign" ? "Build campaign" : "Document studio";
  document.title = name === "campaign" ? "Build campaign · Folio" : "Folio · Document Workspace";
}

viewButtons.forEach((button) => button.addEventListener("click", () => {
  window.location.hash = button.dataset.view;
}));
document.querySelectorAll("[data-open-campaign]").forEach((link) => link.addEventListener("click", () => {
  showView("campaign");
}));
window.addEventListener("hashchange", () => showView(window.location.hash === "#campaign" ? "campaign" : "workspace"));
showView(window.location.hash === "#campaign" ? "campaign" : "workspace");

let healthRetryTimer = null;
const HEALTH_RETRY_MS = 8000;

async function checkHealth() {
  const label = document.getElementById("health-label");
  const dot = document.getElementById("health-dot");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch("/api/health", { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error("Server unavailable");
    const data = await response.json();
    if (data.status !== "ok" || data.service !== "folio-web") throw new Error("Unexpected service");
    label.textContent = "Web server online · Models checked on request";
    dot.classList.add("is-online");
    dot.classList.remove("is-offline");
    window.clearTimeout(healthRetryTimer);
    healthRetryTimer = null;
  } catch {
    // Keep retrying while offline; the label tells the user a retry is running.
    label.textContent = "Server unreachable · Retrying automatically…";
    dot.classList.add("is-offline");
    dot.classList.remove("is-online");
    if (!healthRetryTimer) healthRetryTimer = window.setTimeout(() => { healthRetryTimer = null; checkHealth(); }, HEALTH_RETRY_MS);
  } finally {
    window.clearTimeout(timeout);
  }
}

window.addEventListener("online", () => { if (healthRetryTimer) { window.clearTimeout(healthRetryTimer); healthRetryTimer = null; } checkHealth(); });
checkHealth();

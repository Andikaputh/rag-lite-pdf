"use strict";

(() => {
  const byId = id => document.getElementById(id);
  const upload = byId("upload-button");
  const replace = byId("replace-button");
  const remove = byId("delete-button");
  const confirmRemove = byId("confirm-delete");
  const cancelRemove = byId("cancel-delete");
  const input = byId("pdf-input");
  const feedback = byId("document-feedback");
  const retry = byId("session-retry");
  const buildIndex = byId("index-button");
  let csrf = "";
  let current = null;
  let busy = false;
  let serverBusy = false;
  let refreshTimer;
  let chatBusy = false;
  let limits = { max_bytes: 10 * 1024 * 1024 };

  function message(text, error = false) {
    feedback.textContent = text;
    feedback.hidden = !text;
    feedback.classList.toggle("is-error", error);
  }

  function controls() {
    [upload, replace, remove, confirmRemove, cancelRemove, buildIndex].forEach(button => { button.disabled = busy || serverBusy || chatBusy || !csrf; });
    byId("documents-title").closest("section").setAttribute("aria-busy", String(busy || serverBusy || chatBusy));
    window.dispatchEvent(new CustomEvent("folio:state", { detail: { document: current, csrf, busy: busy || serverBusy || chatBusy } }));
  }

  function render(document) {
    current = document;
    byId("delete-confirmation").hidden = true;
    remove.setAttribute("aria-expanded", "false");
    byId("document-empty").hidden = Boolean(document);
    byId("document-details").hidden = !document;
    byId("document-count").textContent = document ? "1" : "0";
    const index = document?.index || { status: "not_indexed" };
    byId("conversation-state").textContent = !document ? "Waiting for a document" : index.status === "ready" ? "Index ready · Limited history" : "Validated · Not indexed";
    if (document) {
      byId("document-name").textContent = document.name;
      byId("document-pages").textContent = document.page_count.toLocaleString("en-US");
      byId("document-size").textContent = `${(document.size_bytes / 1024).toLocaleString("en-US", { maximumFractionDigits: 1 })} KiB`;
      byId("document-characters").textContent = document.text_characters.toLocaleString("en-US");
      byId("document-warning").hidden = !document.empty_pages;
      byId("document-warning").textContent = `${document.empty_pages} pages without text skipped; OCR is not available.`;
      const labels = { not_indexed: "Not indexed", indexing: "Building index…", ready: "Index ready", failed: "Index failed" };
      byId("index-status").textContent = labels[index.status] || "Not indexed";
      byId("index-status").dataset.state = index.status;
      byId("index-summary").textContent = index.status === "ready"
        ? `${index.chunk_count} chunks · ${index.dimensions} dimensions · ${index.model}. Page references are stored for citations.`
        : index.status === "indexing"
          ? `${index.embedded_chunks || 0} / ${index.chunk_count || "…"} chunks processed. Wait before replacing or deleting the document.`
          : index.status === "failed"
            ? index.error?.message || "Indexing failed. The PDF is still stored; try again."
            : "Build an index with BGE-M3 through local Ollama. No paid API or automatic model download.";
      buildIndex.textContent = index.status === "ready" ? "Check saved index" : index.status === "failed" ? "Retry indexing" : "Build local index";
    }
  }

  async function request(url, options = {}) {
    const response = await fetch(url, { ...options, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(150000) });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(data?.error?.message || "Request failed. Try again.");
    return data;
  }

  async function sync() {
    const data = await request("/api/documents");
    csrf = data.csrf_token;
    limits = data.limits;
    const wasProcessing = serverBusy;
    serverBusy = data.processing;
    render(data.document);
    retry.hidden = !data.processing;
    if (data.processing) {
      message("The session is processing a document. Status updates automatically until completion.");
    } else if (wasProcessing) {
      message(data.document?.index?.status === "ready" ? "Local index ready. You can ask a question." : "Processing finished. Check the document and index status.");
    }
    byId("upload-note").textContent = "SERVER-SIDE PROCESSING · NO MODEL API KEY";
    window.clearTimeout(refreshTimer);
    if (serverBusy) refreshTimer = window.setTimeout(async () => {
      try { await sync(); controls(); } catch {
        csrf = "";
        retry.hidden = false;
        message("Processing status could not be checked. Reconnect to confirm the result.", true);
        controls();
      }
    }, 2000);
  }

  async function connect() {
    busy = true;
    controls();
    try {
      await sync();
      if (csrf) message("");
    } catch {
      csrf = "";
      retry.hidden = false;
      message("Could not connect to the session. Reconnect before uploading a file.", true);
      byId("upload-note").textContent = "SESSION NOT CONNECTED";
    } finally {
      busy = false;
      controls();
    }
  }

  upload.addEventListener("click", () => input.click());
  replace.addEventListener("click", () => input.click());
  retry.addEventListener("click", connect);

  input.addEventListener("change", async () => {
    const file = input.files[0];
    input.value = ""; // Same file can be retried after failure.
    if (!file || busy) return;
    if (!file.name.toLowerCase().endsWith(".pdf") || !file.size || file.size > limits.max_bytes) {
      message("Choose a non-empty PDF up to 10 MiB. The active document has not changed.", true);
      return;
    }
    busy = true;
    controls();
    message("Uploading and validating the PDF… keep this page open.");
    try {
      const data = await request("/api/documents", {
        method: "POST", headers: { "Content-Type": "application/pdf", "X-File-Name": encodeURIComponent(file.name), "X-CSRF-Token": csrf }, body: file,
      });
      render(data.document);
      message("PDF validated. Build its local index before asking questions.");
    } catch (error) {
      // An interrupted response can hide a completed upload. Reconcile with the
      // server rather than asserting that the old document is definitely active.
      try {
        await sync();
        message(`${error.message} ${current ? "The displayed document is active on the server." : "No document is active."}`, true);
      } catch {
        csrf = "";
        render(null);
        retry.hidden = false;
        message("Connection lost. Upload status is unknown; reconnect to check.", true);
      }
    } finally {
      busy = false;
      controls();
    }
  });

  buildIndex.addEventListener("click", async () => {
    if (busy || serverBusy || !current) return;
    busy = true;
    controls();
    byId("index-status").textContent = "Building or checking the index…";
    message("Local indexing is running. The request may take up to 2 minutes.");
    try {
      const result = await request("/api/documents/index", {
        method: "POST", headers: { "X-CSRF-Token": csrf, "X-Document-Id": current.id },
      });
      render(result.document);
      message(result.reused ? "Saved index reused without recomputing embeddings." : "Local index ready. Ask a question and check its source quotes.");
    } catch (error) {
      try { await sync(); } catch { csrf = ""; retry.hidden = false; }
      message(`${error.message} Check the document status before retrying.`, true);
    } finally {
      busy = false;
      controls();
    }
  });

  remove.addEventListener("click", () => {
    byId("delete-confirmation").hidden = false;
    remove.setAttribute("aria-expanded", "true");
    cancelRemove.focus();
  });
  cancelRemove.addEventListener("click", () => {
    byId("delete-confirmation").hidden = true;
    remove.setAttribute("aria-expanded", "false");
    remove.focus();
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || byId("delete-confirmation").hidden) return;
    byId("delete-confirmation").hidden = true;
    remove.setAttribute("aria-expanded", "false");
    remove.focus();
  });
  confirmRemove.addEventListener("click", async () => {
    if (busy || !current) return;
    busy = true;
    controls();
    message("Deleting document…");
    try {
      await request("/api/documents", { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
      render(null);
      message("Document and extracted text deleted.");
    } catch (error) {
      try { await sync(); } catch { csrf = ""; render(null); retry.hidden = false; }
      message(`${error.message} Reconnect if the status is unclear.`, true);
    } finally {
      busy = false;
      controls();
    }
  });

  window.addEventListener("folio:chat-busy", event => { chatBusy = event.detail; controls(); });
  window.addEventListener("folio:refresh", () => { if (!busy && !chatBusy) connect(); });
  window.addEventListener("focus", () => { if (!busy && !chatBusy) connect(); });
  connect();
})();

"use strict";

(() => {
  const byId = id => document.getElementById(id);
  const form = byId("chat-form");
  const question = byId("question");
  const send = byId("send-question");
  const feedback = byId("answer-feedback");
  const list = byId("conversation-turns");
  const useHistory = byId("use-history");
  const reset = byId("reset-conversation");
  let state = { document: null, csrf: "", busy: true };
  let pending = false;
  let signature = "";
  let revision = null;
  let renderedRevision = null;
  let turns = [];
  let loading = false;
  let loadId = 0;
  let limitTurns = 6;

  function message(text, error = false) {
    feedback.textContent = text;
    feedback.hidden = !text;
    feedback.classList.toggle("is-error", error);
  }

  function setResetExpanded(open) {
    reset.setAttribute("aria-expanded", String(open));
  }

  function controls() {
    const ready = Boolean(state.csrf && state.document?.index?.status === "ready" && !state.busy && !pending && !loading && revision !== null);
    question.disabled = !ready;
    send.disabled = !ready || !question.value.trim();
    send.textContent = pending ? "…" : "↑";
    question.placeholder = ready ? "Ask about this document…" : "Upload a PDF and build its index first…";
    form.setAttribute("aria-busy", String(pending));
    useHistory.disabled = !ready;
    reset.disabled = !ready || !turns.length;
    byId("confirm-reset-conversation").disabled = !ready;
  }

  function clearHistory() {
    list.replaceChildren();
    list.hidden = true;
    turns = [];
    revision = renderedRevision = null;
    byId("history-count").textContent = `0/${limitTurns} turns`;
    byId("conversation-empty").hidden = false;
    byId("conversation-reset-confirm").hidden = true;
    setResetExpanded(false);
    message("");
  }

  window.addEventListener("folio:state", event => {
    const wasBusy = state.busy;
    state = event.detail;
    const next = `${state.document?.id || ""}|${state.document?.name || ""}|${state.document?.index?.cache_key || ""}|${Boolean(state.csrf)}`;
    if (signature !== next) {
      signature = next;
      ++loadId;
      loading = false;
      clearHistory();
      if (state.csrf && state.document?.index?.status === "ready") syncHistory();
    } else if (wasBusy && !state.busy && !pending && !loading && state.csrf && state.document?.index?.status === "ready") {
      syncHistory();
    }
    controls();
  });
  question.addEventListener("input", controls);

  function renderTurn(turn, latest) {
    const article = byId("conversation-turn-template").content.firstElementChild.cloneNode(true);
    const role = name => article.querySelector(`[data-role="${name}"]`);
    if (latest) {
      article.id = "answer-output";
      for (const [name, id] of [["question", "asked-question"], ["kind", "answer-kind"], ["text", "answer-text"], ["sources", "answer-sources"]]) role(name).id = id;
    }
    article.dataset.turnId = turn.id;
    role("question").textContent = turn.question;
    role("resolved").hidden = !turn.used_history;
    role("resolved").textContent = `With previous context: ${turn.resolved_question}`;
    const data = turn.response;
    role("kind").textContent = data.status === "answered"
      ? data.answer_mode === "derived" ? "EXACT CONVERSION · CALCULATED FROM SOURCE VALUES" : data.answer_mode === "extractive" ? "EXTRACTIVE ANSWER · ORIGINAL SOURCE TEXT" : "ANSWER WITH VERIFIED QUOTES"
      : "INSUFFICIENT EVIDENCE";
    const reasons = {
      instruction_override_request: "Requests to override the rules are not followed. Ask about the document's contents.",
      model_abstained: "The model declined to answer; this is different from a quote failing validation.",
      model_no_evidence_selection: "The model did not select a passage that directly answers the question.",
      no_relevant_evidence: "Retrieved passages do not establish the requested facts.",
      missing_requested_fact: "Selected evidence does not cover every requested fact.",
      unsupported_calculation: "This calculation is not supported. Ask for the value as written in the document.",
      ambiguous_conversion: "The conversion is ambiguous or unsupported. Ask about one explicit duration in the document.",
      quantity_mismatch: "The duration in the question does not match the source. Check the quote first.",
      invalid_derivation: "The calculation trace could not be verified; the result is not shown.",
      unsupported_claim: "The claim did not meet the extractive answer policy and is not shown.",
      explicit_unavailable_fact: "The selected evidence states that the requested information is unavailable.",
      quote_mismatch: "The model's quote does not match the source; the claim is not shown.",
      numeric_mismatch: "A number in the claim is not supported by its source quote; the claim is not shown.",
      unknown_source: "The source reference is invalid; the claim is not shown.",
      invalid_answer_contract: "The answer structure is invalid; the claim is not shown.",
    };
    role("reason").hidden = data.status === "answered" || !reasons[data.reason];
    role("reason").textContent = reasons[data.reason] || "";
    const text = role("text");
    const sources = role("sources");
    if (data.status === "answered") {
      for (const claim of data.claims) {
        const paragraph = document.createElement("p");
        paragraph.append(document.createTextNode(claim.text + " "));
        const cite = document.createElement("button");
        cite.className = "citation-link";
        cite.textContent = `[${claim.citation}]`;
        cite.setAttribute("aria-label", `View source ${claim.citation}`);
        cite.addEventListener("click", () => {
          const source = byId(`source-${turn.id}-${claim.citation}`);
          source.open = true;
          source.querySelector("summary").focus();
          source.scrollIntoView({ block: "nearest" });
        });
        paragraph.append(cite);
        text.append(paragraph);
        if (claim.derivation) {
          const proof = document.createElement("p");
          proof.className = "turn-resolved derivation-proof";
          proof.textContent = `Rule ${claim.derivation.rule}: ${claim.derivation.calculation}. Input: ${claim.derivation.source_unit}; output: ${claim.derivation.target_unit}. The quote below supports the input, not a model-generated calculation.`;
          text.append(proof);
        }
      }
      for (const source of data.sources) {
        const detail = document.createElement("details");
        detail.id = `source-${turn.id}-${source.number}`;
        detail.className = "source-card";
        const summary = document.createElement("summary");
        summary.textContent = `[${source.number}] ${source.document_name} · Page ${source.page}`;
        const quote = document.createElement("blockquote");
        quote.textContent = source.quote;
        const metadata = document.createElement("small");
        metadata.textContent = `Chunk ${source.chunk_id} · Retrieval similarity ${source.retrieval_score} (not an answer accuracy score)`;
        detail.append(summary, quote, metadata);
        sources.append(detail);
      }
    } else {
      const paragraph = document.createElement("p");
      paragraph.textContent = data.answer;
      text.append(paragraph);
    }
    return article;
  }

  function renderHistory(data) {
    revision = data.revision;
    if (renderedRevision === revision) return;
    renderedRevision = revision;
    turns = data.turns;
    limitTurns = data.limits.max_turns;
    list.replaceChildren(...turns.map((turn, index) => renderTurn(turn, index === turns.length - 1)));
    list.hidden = !turns.length;
    byId("conversation-empty").hidden = Boolean(turns.length);
    byId("history-count").textContent = `${turns.length}/${limitTurns} turns`;
    list.scrollTop = list.scrollHeight;
  }

  async function syncHistory() {
    const currentLoad = ++loadId;
    const currentSignature = signature;
    loading = true;
    byId("history-count").textContent = "Loading history…";
    controls();
    try {
      const response = await fetch("/api/chat", { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000) });
      const data = await response.json();
      if (currentLoad !== loadId || currentSignature !== signature) return null;
      if (!response.ok) throw new Error(data?.error?.message || "Could not load conversation history.");
      if (data.document_id !== state.document?.id || data.index_key !== state.document?.index?.cache_key) {
        clearHistory();
        throw new Error("The document or index changed. Refresh the workspace status.");
      }
      if (revision !== null && data.revision < revision) return null;
      renderHistory(data);
      return data;
    } catch (error) {
      if (currentLoad === loadId) message(`${error.message} Reload the page or reconnect the session.`, true);
      return null;
    } finally {
      if (currentLoad === loadId) {
        loading = false;
        byId("history-count").textContent = `${turns.length}/${limitTurns} turns`;
        controls();
      }
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (pending || send.disabled) return;
    const asked = question.value.trim();
    const documentId = state.document.id;
    const indexKey = state.document.index.cache_key;
    const csrf = state.csrf;
    const expectedRevision = revision;
    const contextual = useHistory.checked;
    pending = true;
    window.dispatchEvent(new CustomEvent("folio:chat-busy", { detail: true }));
    controls();
    message("Retrieving evidence and preparing an answer locally…");
    try {
      const response = await fetch("/api/chat", {
        method: "POST", credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(150000),
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, "X-Document-Id": documentId, "X-Conversation-Revision": String(expectedRevision) },
        body: JSON.stringify({ question: asked, use_history: contextual }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || "Could not process the answer.");
      // A different tab may have replaced/deleted the file after the request.
      const snapshot = await fetch("/api/documents", { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000) });
      const latest = await snapshot.json();
      if (!snapshot.ok || latest.document?.id !== documentId || latest.document?.index?.cache_key !== indexKey ||
          data.document_id !== documentId || data.index_key !== indexKey) throw new Error("The document or index changed. The previous answer is not shown.");
      const history = await syncHistory();
      if (!history || !history.turns.some(turn => turn.id === data.turn_id)) throw new Error("The conversation changed or was reset. The previous answer is not restored.");
      message("Done. Check the interpreted question and source quotes; model answers can be wrong.");
    } catch (error) {
      await syncHistory();
      message(error.name === "TimeoutError" ? "Answer request timed out. Check the server status before retrying." : error.message, true);
    } finally {
      pending = false;
      window.dispatchEvent(new CustomEvent("folio:chat-busy", { detail: false }));
      window.dispatchEvent(new Event("folio:refresh"));
      controls();
    }
  });

  reset.addEventListener("click", () => {
    byId("conversation-reset-confirm").hidden = false;
    setResetExpanded(true);
    byId("cancel-reset-conversation").focus();
  });
  byId("cancel-reset-conversation").addEventListener("click", () => {
    byId("conversation-reset-confirm").hidden = true;
    setResetExpanded(false);
    reset.focus();
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || byId("conversation-reset-confirm").hidden) return;
    byId("conversation-reset-confirm").hidden = true;
    setResetExpanded(false);
    reset.focus();
  });
  byId("confirm-reset-conversation").addEventListener("click", async () => {
    if (pending || reset.disabled) return;
    pending = true;
    window.dispatchEvent(new CustomEvent("folio:chat-busy", { detail: true }));
    controls();
    try {
      const response = await fetch("/api/chat", { method: "DELETE", credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000),
        headers: { "X-CSRF-Token": state.csrf, "X-Document-Id": state.document.id, "X-Conversation-Revision": String(revision) } });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || "Could not reset the conversation.");
      renderHistory(data);
      byId("conversation-reset-confirm").hidden = true;
      setResetExpanded(false);
      message("Conversation reset. The PDF and index are still available.");
    } catch (error) {
      await syncHistory();
      message(error.message, true);
    } finally {
      pending = false;
      window.dispatchEvent(new CustomEvent("folio:chat-busy", { detail: false }));
      controls();
    }
  });
  controls();
})();

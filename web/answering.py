"""Read-only retrieval and bounded follow-up answers with fail-closed citations."""
import math
import re
import sqlite3
import time
from array import array
from contextlib import closing

from web.documents import DocumentError
from web.embeddings import normalize_vectors
from web.generation import OllamaGenerator
from web.indexing import cache_key, read_manifest
from web.grounding import EvidenceDecision, extractive_rejection
from web.conversions import valid_derivation

ABSTENTION = "The document does not provide enough evidence to answer this question. Try a more specific question or check the source document."


def retrieve(path, query, *, dimensions, top_k=5, min_score=.35):
    candidates = []
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            for chunk_id, page, start, end, text, blob in connection.execute("SELECT id,page,start,end,text,vector FROM chunks"):
                vector = array("f")
                vector.frombytes(blob)
                if len(vector) != dimensions or not all(math.isfinite(v) for v in vector) or not .999 <= math.hypot(*vector) <= 1.001:
                    raise ValueError("Invalid vector")
                if not isinstance(chunk_id, int) or chunk_id < 0 or not isinstance(text, str) or not 1 <= len(text) <= 2000 or not 1 <= page <= 100 or not 0 <= start < end <= 1_000_000 or end - start != len(text):
                    raise ValueError("Invalid chunk")
                score = sum(a * b for a, b in zip(query, vector))
                if score >= min_score:
                    candidates.append({"source_id": f"C{chunk_id}", "chunk_id": chunk_id, "page": page,
                                       "start": start, "end": end, "text": text, "score": min(1., score)})
        candidates.sort(key=lambda c: (-c["score"], c["chunk_id"]))
        selected = []
        for chunk in candidates:
            if any(chunk["page"] == old["page"] and min(chunk["end"], old["end"]) - max(chunk["start"], old["start"]) > min(len(chunk["text"]), len(old["text"])) / 2 for old in selected):
                continue
            selected.append(chunk)
            if len(selected) == top_k:
                break
        return selected
    except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError):
        raise DocumentError("index_stale", "The index is corrupt or incompatible. Rebuild it before asking questions.", 409) from None


def inspect_claims(payload, sources, filename, *, allow_derivations=False, question=""):
    """Proves source membership and exact quotation, NOT semantic entailment."""
    if not isinstance(payload, dict) or set(payload) != {"abstain", "claims"} or type(payload["abstain"]) is not bool or not isinstance(payload["claims"], list):
        return None, "invalid_answer_contract"
    if payload["abstain"]:
        return None, "model_abstained" if not payload["claims"] else "invalid_answer_contract"
    if not 1 <= len(payload["claims"]) <= 3:
        return None, "invalid_answer_contract"
    by_id = {source["source_id"]: source for source in sources}
    claims, citations = [], []
    for claim in payload["claims"]:
        if not isinstance(claim, dict) or set(claim) not in ({"text", "source_id", "quote"}, {"text", "source_id", "quote", "derivation"}) or not all(isinstance(claim.get(k), str) for k in ("text", "source_id", "quote")):
            return None, "invalid_answer_contract"
        text, quote = " ".join(claim["text"].split()), " ".join(claim["quote"].split())
        source = by_id.get(claim["source_id"])
        if not source:
            return None, "unknown_source"
        if not 1 <= len(text) <= 600 or not 12 <= len(quote) <= 400 or re.search(r"\[\d+\]", text):
            return None, "invalid_answer_contract"
        if quote not in " ".join(source["text"].split()):
            return None, "quote_mismatch"
        # Cheap hard guard against changing a quoted amount/date. This does not
        # establish semantic support for names, units, or the complete claim.
        numbers = lambda value: set(re.findall(r"\d+(?:[.,]\d+)*", value))
        derived = "derivation" in claim
        if derived and (not allow_derivations or not valid_derivation(question, claim)):
            return None, "invalid_derivation"
        if not derived and not numbers(text).issubset(numbers(quote)):
            return None, "numeric_mismatch"
        number = len(citations) + 1
        claims.append({"text": text, "citation": number, **({"derivation": claim["derivation"]} if derived else {})})
        citations.append({"number": number, "document_name": filename, "page": source["page"],
                          "chunk_id": source["chunk_id"], "start": source["start"], "end": source["end"],
                          "quote": quote, "retrieval_score": round(source["score"], 4)})
    return {"claims": claims, "sources": citations,
            "answer": "\n\n".join(f"{c['text']} [{c['citation']}]" for c in claims)}, None


def verify_claims(payload, sources, filename):
    """Backward-compatible verifier; detailed reasons contain no raw model text."""
    return inspect_claims(payload, sources, filename)[0]


class AnswerService:
    def __init__(self, indexer, *, generator=None, timeout=120, min_score=.35, retrieval_observer=None):
        self.indexer = indexer
        self.generator = generator or OllamaGenerator()
        self.timeout, self.min_score = timeout, min_score
        # Python-only opt-in instrumentation for synthetic evaluation. Never
        # returned by the web API or enabled for ordinary user requests.
        self.retrieval_observer = retrieval_observer
        self.answer_strategy = getattr(self.generator, "answer_strategy", "legacy_v1")

    def answer(self, store, session, document_id, question, *, use_history=True, expected_revision=None):
        with store.lock:
            if store.sessions.get(session.token) is not session:
                raise DocumentError("session_expired", "Session expired. Reload the page.", 403)
            if not session.document or session.document["id"] != document_id:
                raise DocumentError("document_changed", "The document changed or was deleted. Refresh its status.", 409)
            if session.busy:
                raise DocumentError("busy", "The session is processing a document. Wait for completion.", 409)
            if expected_revision is not None and expected_revision != session.conversation.revision:
                raise DocumentError("conversation_changed", "The conversation changed in another tab. Check current history before resubmitting.", 409)
            document = session.document.copy()
            if document.get("index", {}).get("status") != "ready":
                raise DocumentError("index_not_ready", "Build the document index before asking questions.", 409)
            # Share the local-inference gate with indexing to bound model pressure.
            if not self.indexer.slot.acquire(blocking=False):
                raise DocumentError("answer_capacity", "Local inference is busy. Try again shortly.", 503)
            session.busy = True
        resolved, used_history = question, False
        deadline = time.monotonic() + self.timeout

        def remaining(limit=30):
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise DocumentError("answer_timeout", "The answer request timed out. Try a shorter question.", 503)
            return min(seconds, limit)

        def assert_active():
            with store.lock:
                if store.sessions.get(session.token) is not session or not session.document or session.document["id"] != document_id:
                    raise DocumentError("document_changed", "The session or document is no longer active.", 409)

        def finish(response):
            assert_active()
            with store.lock:
                mode = "derived" if any("derivation" in c for c in response.get("claims", [])) else "extractive" if self.answer_strategy in ("extractive_v2", "focused_v3") else "generative"
                response = {**response, "answer_mode": mode,
                            "grounding_policy": self.answer_strategy, "policy_revision": getattr(self.generator, "policy_revision", 1)}
                return session.conversation.append(question, resolved, response, used_history)

        def abstain(reason, text=ABSTENTION):
            return finish({"status": "abstained", "reason": reason, "answer": text, "claims": [], "sources": [],
                           "document_id": document_id, "index_key": document["index"]["cache_key"]})

        try:
            embedder = self.indexer.embedder
            identity = embedder.identity(timeout=remaining(5))
            path = (store.root / session.token / document_id / "index.sqlite3").resolve()
            manifest = read_manifest(path)
            expected_key = cache_key(document["sha256"], self.indexer.config, identity)
            if not manifest or manifest.get("cache_key") != expected_key or document["index"].get("cache_key") != expected_key:
                raise DocumentError("index_stale", "The model or index configuration changed. Rebuild the index; questions do not trigger indexing automatically.", 409)
            with store.lock:
                changed = session.conversation.bind(document_id, expected_key)
                has_history = bool(session.conversation.turns)
            if changed and use_history:
                raise DocumentError("conversation_reset", "The document or index changed; previous context was cleared. Write a complete question.", 409)
            generator_identity = None
            if has_history:
                generator_identity = self.generator.identity(timeout=remaining(5))
                with store.lock:
                    changed = session.conversation.bind(document_id, expected_key, {**generator_identity, "answer_strategy": self.answer_strategy, "policy_revision": getattr(self.generator, "policy_revision", 1)})
                    previous = session.conversation.context_questions()
                if changed and use_history:
                    raise DocumentError("conversation_reset", "The answer model changed; history was cleared. Write a complete question.", 409)
                if use_history and previous:
                    rewrite = self.generator.rewrite(question, previous, timeout=remaining())
                    if self.generator.identity(timeout=remaining(5)) != generator_identity:
                        raise DocumentError("generation_model_changed", "The model changed while resolving the topic. Retry once it is stable.", 409)
                    if rewrite["needs_clarification"]:
                        return abstain("needs_clarification", "The follow-up topic is unclear. Name the topic or write a complete question.")
                    resolved, used_history = rewrite["question"], True
            query = normalize_vectors(embedder.embed([resolved], timeout=remaining()), 1, identity["dimensions"])[0]
            if embedder.identity(timeout=remaining(5)) != identity:
                raise DocumentError("index_stale", "The embedding model changed during retrieval. Check the index and try again.", 409)
            sources = retrieve(path, query, dimensions=identity["dimensions"], min_score=self.min_score)
            if self.retrieval_observer is not None:
                self.retrieval_observer([dict(source) for source in sources])
            remaining()
            assert_active()
            if not sources:
                return abstain("low_retrieval_score")
            generator_identity = generator_identity or self.generator.identity(timeout=remaining(5))
            with store.lock:
                session.conversation.bind(document_id, expected_key, {**generator_identity, "answer_strategy": self.answer_strategy, "policy_revision": getattr(self.generator, "policy_revision", 1)})
            payload = self.generator.generate(resolved, [{"source_id": s["source_id"], "text": s["text"]} for s in sources], timeout=remaining(90))
            if self.generator.identity(timeout=remaining(5)) != generator_identity:
                raise DocumentError("generation_model_changed", "The answer model changed during processing. Retry once it is stable.", 409)
            if embedder.identity(timeout=remaining(5)) != identity:
                raise DocumentError("index_stale", "The embedding model changed. Check the index before asking questions.", 409)
            remaining()
            assert_active()
            if isinstance(payload, EvidenceDecision):
                if payload.reason:
                    return abstain(payload.reason)
                payload = payload.payload
            focused = self.answer_strategy == "focused_v3"
            verified, rejection = inspect_claims(payload, sources, document["name"], allow_derivations=focused, question=resolved)
            if not verified:
                return abstain(rejection)
            if self.answer_strategy in ("extractive_v2", "focused_v3"):
                literal = [{**c, "text": c["quote"]} if "derivation" in c else c for c in payload["claims"]]
                rejection = extractive_rejection(resolved, literal, allow_conversion=focused)
                if rejection:
                    return abstain(rejection)
            return finish({"status": "answered", **verified, "document_id": document_id, "index_key": expected_key,
                           "model": generator_identity["model"], "model_digest": generator_identity["digest"]})
        except DocumentError as error:
            if error.code == "index_stale":
                with store.lock:
                    if store.sessions.get(session.token) is session and session.document and session.document["id"] == document_id:
                        session.document = {**session.document, "index": {"status": "failed", "error": {"code": error.code, "message": error.message}}}
                        session.conversation.clear()
            elif error.code == "generation_model_changed":
                with store.lock:
                    session.conversation.clear()
            raise
        except Exception:
            raise DocumentError("answer_failed", "Could not process the answer. Try again; the document and index have not been deleted.", 503) from None
        finally:
            with store.lock:
                session.busy = False
                session.touched = time.monotonic()
                self.indexer.slot.release()

"""Bounded ephemeral chat state. Call under DocumentStore.lock."""
import json
import secrets
import time
from copy import deepcopy
from dataclasses import dataclass, field

MAX_TURNS = 6
MAX_HISTORY_BYTES = 48 * 1024
CONTEXT_QUESTIONS = 2
CONTEXT_BYTES = 1800


@dataclass
class Conversation:
    revision: int = 0
    base_key: str | None = None
    model_key: str | None = None
    turns: list = field(default_factory=list)

    def clear(self):
        self.turns.clear()
        self.base_key = self.model_key = None
        self.revision += 1

    def bind(self, document_id, index_key, identity=None):
        base = f"{document_id}:{index_key}"
        model = json.dumps(identity, sort_keys=True) if identity is not None else None
        changed = (self.base_key is not None and self.base_key != base) or (
            model is not None and self.model_key is not None and model != self.model_key
        )
        had_history = bool(self.turns)
        if changed:
            self.clear()
        self.base_key = base
        if model is not None:
            self.model_key = model
        return changed and had_history

    def context_questions(self):
        questions = []
        for turn in reversed(self.turns):
            if turn["response"]["status"] != "answered":
                break  # Don't jump back past an unresolved/abstained topic.
            questions.append(turn["resolved_question"][:300])
            if len(questions) == CONTEXT_QUESTIONS:
                break
        questions.reverse()
        remaining, bounded = CONTEXT_BYTES, []
        for question in questions:
            text = question.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
            if text:
                bounded.append(text)
                remaining -= len(text.encode("utf-8"))
        return bounded

    def append(self, question, resolved, response, used_history):
        turn_id = secrets.token_hex(8)
        self.revision += 1
        response = {**response, "turn_id": turn_id, "conversation_revision": self.revision,
                    "resolved_question": resolved, "used_history": used_history}
        self.turns.append({"id": turn_id, "question": question, "resolved_question": resolved,
                           "used_history": used_history, "created_at": time.time(), "response": deepcopy(response)})
        while len(self.turns) > MAX_TURNS or len(json.dumps(self.turns, ensure_ascii=False).encode("utf-8")) > MAX_HISTORY_BYTES:
            self.turns.pop(0)
        return response

    def snapshot(self, document, busy):
        return {"turns": deepcopy(self.turns), "revision": self.revision, "processing": busy,
                "document_id": document["id"] if document else None,
                "index_key": document.get("index", {}).get("cache_key") if document else None,
                "limits": {"max_turns": MAX_TURNS, "max_history_bytes": MAX_HISTORY_BYTES,
                           "context_questions": CONTEXT_QUESTIONS, "context_bytes": CONTEXT_BYTES}}

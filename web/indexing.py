"""Page-aware chunks and bounded, session-private SQLite dense-vector indexes."""
import hashlib
import json
import sqlite3
import threading
import time
from array import array
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from web.documents import DocumentError
from web.embeddings import OllamaEmbedder, normalize_vectors


@dataclass(frozen=True)
class ChunkConfig:
    size: int = 900
    overlap: int = 120
    max_chunks: int = 2000
    batch_size: int = 8

    def __post_init__(self):
        if not 0 <= self.overlap < self.size or self.size > 2000 or not 1 <= self.max_chunks <= 2000 or not 1 <= self.batch_size <= 16:
            raise ValueError("Invalid chunk configuration")


def split_pages(pages, config: ChunkConfig):
    """Character-based windows; prefer paragraph/sentence/word boundaries.

    Never merge pages. Offsets refer to extracted page text, not PDF byte offsets.
    This is not a tokenizer and makes no claim of optimal retrieval quality.
    """
    chunks = []
    for page in pages:
        text = page["text"]
        if not text.strip():
            continue
        start = 0
        while start < len(text):
            end = min(start + config.size, len(text))
            if end < len(text):
                lower = start + max(config.overlap + 1, config.size // 2)
                for separator in ("\n\n", "\n", ". ", " "):
                    boundary = text.rfind(separator, lower, end)
                    if boundary >= lower:
                        end = boundary + len(separator)
                        break
            fragment = text[start:end]
            if fragment.strip():
                chunks.append({"id": len(chunks), "page": page["page"], "start": start, "end": end, "text": fragment})
                if len(chunks) > config.max_chunks:
                    raise DocumentError("too_many_chunks", "Too many text chunks. Split the PDF into smaller documents.", 422)
            if end == len(text):
                break
            start = max(start + 1, end - config.overlap)
    if not chunks:
        raise DocumentError("no_chunks", "No text is available for indexing.", 422)
    return chunks


def cache_key(pdf_sha256, config, identity):
    payload = {"version": 1, "pdf_sha256": pdf_sha256, "chunking": asdict(config),
               "embedding": identity, "normalization": "l2", "storage": "sqlite-float32-native"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def read_manifest(path: Path):
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            result = json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
            count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            dimensions = result["dimensions"]
            if count != result["chunk_count"] or not 1 <= count <= 2000 or not isinstance(dimensions, int) or not 1 <= dimensions <= 4096:
                return None
            if connection.execute("SELECT COUNT(*) FROM chunks WHERE vector IS NULL OR length(vector) != ?", (dimensions * 4,)).fetchone()[0]:
                return None
            return result
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return None


class IndexService:
    def __init__(self, *, embedder=None, config=None, timeout=120):
        self.embedder = embedder or OllamaEmbedder()
        self.config = config or ChunkConfig()
        self.timeout = timeout
        self.slot = threading.BoundedSemaphore(1)

    def ensure(self, store, session, document_id):
        with store.lock:
            if not session.document or session.document["id"] != document_id:
                raise DocumentError("document_changed", "The document changed or was deleted. Refresh its status before indexing.", 409)
            if session.busy:
                raise DocumentError("busy", "The session is processing a document. Wait for completion.", 409)
            if not self.slot.acquire(blocking=False):
                raise DocumentError("index_capacity", "The indexing slot is busy. Retry after the current operation finishes.", 503)
            session.busy = True
            previous_key = session.document.get("index", {}).get("cache_key")
            session.document = {**session.document, "index": {"status": "indexing", "chunk_count": 0}}
            directory = (store.root / session.token / document_id).resolve()
            pdf_sha256 = session.document["sha256"]
        staging = directory / "index.build.sqlite3"
        config = self.config
        deadline = time.monotonic() + self.timeout

        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise DocumentError("index_timeout", "Indexing timed out. Try a smaller PDF or retry when the server is idle.", 503)
            return min(value, 30)

        def update(index):
            with store.lock:
                if store.sessions.get(session.token) is not session or not session.document or session.document["id"] != document_id:
                    raise DocumentError("document_changed", "The session or document is no longer active.", 409)
                session.document = {**session.document, "index": index}
                return session.document

        try:
            identity = self.embedder.identity(timeout=min(5, remaining()))
            key = cache_key(pdf_sha256, config, identity)
            final = directory / "index.sqlite3"
            manifest = read_manifest(final) if final.is_file() else None
            if manifest and manifest.get("cache_key") == key:
                document = update({"status": "ready", **manifest})
                return {"document": document, "reused": True}
            pages = json.loads((directory / "pages.json").read_text(encoding="utf-8"))
            chunks = split_pages(pages, config)
            staging.unlink(missing_ok=True)
            with closing(sqlite3.connect(staging)) as connection, connection:
                connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, page INTEGER, start INTEGER, end INTEGER, text TEXT, vector BLOB)")
                for start in range(0, len(chunks), config.batch_size):
                    batch = chunks[start:start + config.batch_size]
                    vectors = self.embedder.embed([c["text"] for c in batch], timeout=remaining())
                    vectors = normalize_vectors(vectors, len(batch), identity["dimensions"])
                    for chunk, vector in zip(batch, vectors):
                        connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
                                           (chunk["id"], chunk["page"], chunk["start"], chunk["end"], chunk["text"], array("f", vector).tobytes()))
                    update({"status": "indexing", "chunk_count": len(chunks), "embedded_chunks": min(start + len(batch), len(chunks))})
                # Re-check the local tag so a model replacement during the build
                # does not publish a mixed-weight index under the first digest.
                if self.embedder.identity(timeout=min(5, remaining())) != identity:
                    raise DocumentError("model_changed", "The embedding model changed during indexing. Retry once the model is stable.", 409)
                remaining()
                manifest = {"cache_key": key, "chunk_count": len(chunks), "model": identity["model"],
                            "model_digest": identity["digest"], "dimensions": identity["dimensions"],
                            "chunking": asdict(config), "created_at": time.time()}
                connection.execute("INSERT INTO metadata VALUES ('manifest', ?)", (json.dumps(manifest),))
            remaining()
            with store.lock:
                update({"status": "indexing", "chunk_count": len(chunks)})
                staging.replace(final)
                if previous_key != key:
                    session.conversation.clear()
                document = update({"status": "ready", **manifest})
            return {"document": document, "reused": False}
        except DocumentError as error:
            with store.lock:
                session.conversation.clear()
            update({"status": "failed", "chunk_count": 0, "error": {"code": error.code, "message": error.message}})
            raise
        except Exception:
            with store.lock:
                session.conversation.clear()
            error = DocumentError("index_failed", "Could not build the index. The PDF is still stored; retry indexing.", 503)
            update({"status": "failed", "chunk_count": 0, "error": {"code": error.code, "message": error.message}})
            raise error from None
        finally:
            try:
                staging.unlink(missing_ok=True)
            finally:
                with store.lock:
                    session.busy = False
                    session.touched = time.monotonic()
                    self.slot.release()

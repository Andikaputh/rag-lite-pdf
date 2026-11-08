import hashlib
import json
import math
import sqlite3
import tempfile
import threading
import unittest
from array import array
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.pdf_fixtures import pdf_bytes
from web.documents import COOKIE_NAME, DocumentError, DocumentStore
from web.embeddings import OllamaEmbedder, normalize_vectors
from web.indexing import ChunkConfig, IndexService, cache_key, read_manifest, split_pages
from web.main import create_app


class FakeEmbedder:
    """Only injected by tests. Never a runtime fallback or a user-selectable mode."""
    dimensions = 4

    def __init__(self):
        self.calls = 0
        self.digest = "test-weights-v1"

    def identity(self, **kwargs):
        return {"model": "test-only", "digest": self.digest, "dimensions": self.dimensions}

    def embed(self, texts, **kwargs):
        self.calls += 1
        return [[float(value + 1) for value in hashlib.sha256(text.encode()).digest()[:4]] for text in texts]


class ChunkingTests(unittest.TestCase):
    def test_chunks_preserve_page_text_and_offsets(self):
        pages = [{"page": 1, "text": "Alpha beta gamma. " * 20}, {"page": 2, "text": ""},
                 {"page": 3, "text": "Teks dokumen Indonesia. " * 10}]
        chunks = split_pages(pages, ChunkConfig(size=90, overlap=12))
        self.assertGreater(len(chunks), 3)
        self.assertEqual({c["page"] for c in chunks}, {1, 3})
        self.assertEqual([c["id"] for c in chunks], list(range(len(chunks))))
        for chunk in chunks:
            text = next(p["text"] for p in pages if p["page"] == chunk["page"])
            self.assertEqual(text[chunk["start"]:chunk["end"]], chunk["text"])
            self.assertLessEqual(len(chunk["text"]), 90)
        for page in (1, 3):
            group = [c for c in chunks if c["page"] == page]
            self.assertEqual(group[0]["start"], 0)
            self.assertEqual(group[-1]["end"], len(pages[page - 1]["text"]))
            for previous, current in zip(group, group[1:]):
                self.assertLessEqual(current["start"], previous["end"])
                self.assertGreater(current["end"], previous["end"])

    def test_long_unbroken_unicode_text_terminates_and_overlaps(self):
        text = "猫" * 205
        chunks = split_pages([{"page": 1, "text": text}], ChunkConfig(size=80, overlap=10))
        self.assertEqual([(c["start"], c["end"]) for c in chunks], [(0, 80), (70, 150), (140, 205)])

    def test_empty_and_excessive_chunks_rejected(self):
        for pages, config, code in (([{"page": 1, "text": " "}], ChunkConfig(), "no_chunks"),
                                   ([{"page": 1, "text": "a" * 100}], ChunkConfig(size=10, overlap=0, max_chunks=2), "too_many_chunks")):
            with self.subTest(code=code), self.assertRaises(DocumentError) as error:
                split_pages(pages, config)
            self.assertEqual(error.exception.code, code)

    def test_invalid_configuration_rejected(self):
        for values in ({"size": 0}, {"size": 10, "overlap": 10}, {"overlap": -1}, {"batch_size": 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ChunkConfig(**values)

    def test_cache_key_changes_with_content_config_and_model(self):
        identity = {"model": "test", "digest": "v1", "dimensions": 4}
        first = cache_key("pdf1", ChunkConfig(), identity)
        self.assertEqual(first, cache_key("pdf1", ChunkConfig(), identity))
        self.assertNotEqual(first, cache_key("pdf2", ChunkConfig(), identity))
        self.assertNotEqual(first, cache_key("pdf1", ChunkConfig(size=800), identity))
        self.assertNotEqual(first, cache_key("pdf1", ChunkConfig(), {**identity, "digest": "v2"}))


class EmbeddingAdapterTests(unittest.TestCase):
    def test_vectors_are_normalized_and_invalid_responses_rejected(self):
        self.assertEqual(normalize_vectors([[3., 4.]], 1, 2), [[.6, .8]])
        for value in (None, [], [[0, 0]], [[1]], [[math.nan, 1]], [[math.inf, 1]], [[True, 1]], [["x", 1]]):
            with self.subTest(value=value), self.assertRaises(DocumentError):
                normalize_vectors(value, 1, 2)

    def test_local_adapter_identity_and_embed_contract(self):
        adapter = OllamaEmbedder()
        responses = [BytesIO(json.dumps({"models": [{"name": "bge-m3:latest", "digest": "abc"}]}).encode()),
                     BytesIO(json.dumps({"embeddings": [[1.] * 1024]}).encode())]
        with patch.object(adapter.opener, "open", side_effect=responses) as transport:
            self.assertEqual(adapter.identity()["digest"], "abc")
            self.assertEqual(len(adapter.embed(["Synthetic test."])[0]), 1024)
            request = transport.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/embed")
            self.assertFalse(json.loads(request.data)["truncate"])

    def test_missing_model_and_ollama_failure_are_actionable(self):
        adapter = OllamaEmbedder()
        with patch.object(adapter.opener, "open", return_value=BytesIO(b'{"models": []}')):
            with self.assertRaises(DocumentError) as error:
                adapter.identity()
            self.assertEqual(error.exception.code, "model_missing")
        with patch.object(adapter.opener, "open", side_effect=TimeoutError):
            with self.assertRaises(DocumentError) as error:
                adapter.embed(["test"])
            self.assertEqual(error.exception.code, "embedding_unavailable")

    def test_malformed_response_does_not_leak_remote_text(self):
        adapter = OllamaEmbedder()
        with patch.object(adapter.opener, "open", return_value=BytesIO(b"private server trace")):
            with self.assertRaises(DocumentError) as error:
                adapter.identity()
            self.assertNotIn("private", error.exception.message)


class IndexGatewayTests(unittest.TestCase):
    def setUp(self):
        Path(".tools").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=".tools")
        self.addCleanup(temporary.cleanup)
        self.store = DocumentStore(Path(temporary.name))
        self.embedder = FakeEmbedder()
        self.indexer = IndexService(embedder=self.embedder, config=ChunkConfig(size=100, overlap=10, batch_size=2))
        self.app = create_app(document_store=self.store, index_service=self.indexer)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.csrf = self.client.get("/api/documents").json()["csrf_token"]
        self.upload()

    def upload(self, text="Knowledge engine synthetic page. " * 12):
        response = self.client.post("/api/documents", content=pdf_bytes(text, pages=2), headers={
            "X-CSRF-Token": self.csrf, "X-File-Name": "index.pdf", "Content-Type": "application/pdf"})
        self.assertEqual(response.status_code, 201, response.text)
        self.document = response.json()["document"]
        self.session = self.store.sessions[self.client.cookies.get(COOKIE_NAME)]
        self.directory = (self.store.root / self.session.token / self.document["id"]).resolve()

    def index(self, **headers):
        return self.client.post("/api/documents/index", headers={"X-CSRF-Token": self.csrf,
                                "X-Document-Id": self.document["id"], **headers})

    def test_ready_index_contains_page_chunks_and_normalized_vectors(self):
        response = self.index()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(data["reused"])
        self.assertEqual(data["document"]["index"]["status"], "ready")
        path = self.directory / "index.sqlite3"
        manifest = read_manifest(path)
        with closing(sqlite3.connect(path)) as connection:
            rows = connection.execute("SELECT page, text, vector FROM chunks").fetchall()
        self.assertEqual(len(rows), manifest["chunk_count"])
        self.assertEqual({r[0] for r in rows}, {1, 2})
        for _, text, blob in rows:
            vector = array("f")
            vector.frombytes(blob)
            self.assertAlmostEqual(math.hypot(*vector), 1, places=5)
            self.assertTrue(text)
        self.assertFalse((self.directory / "index.build.sqlite3").exists())
        self.assertFalse(self.session.busy)

    def test_repeated_index_and_status_reload_do_not_reembed(self):
        self.index()
        calls = self.embedder.calls
        self.assertTrue(self.index().json()["reused"])
        self.assertEqual(self.client.get("/api/documents").json()["document"]["index"]["status"], "ready")
        self.assertEqual(self.embedder.calls, calls)

    def test_changed_model_and_chunk_config_force_rebuild(self):
        self.index()
        calls = self.embedder.calls
        self.embedder.digest = "test-v2"
        self.assertFalse(self.index().json()["reused"])
        self.assertGreater(self.embedder.calls, calls)
        calls = self.embedder.calls
        self.indexer.config = ChunkConfig(size=120, overlap=15)
        self.assertFalse(self.index().json()["reused"])
        self.assertGreater(self.embedder.calls, calls)

    def test_identical_reupload_keeps_document_and_index(self):
        self.index()
        original_id = self.document["id"]
        calls = self.embedder.calls
        self.upload()
        self.assertEqual(self.document["id"], original_id)
        self.assertEqual(self.document["index"]["status"], "ready")
        self.assertTrue(self.index().json()["reused"])
        self.assertEqual(self.embedder.calls, calls)

    def test_truncated_cached_vector_is_rebuilt(self):
        self.index()
        with closing(sqlite3.connect(self.directory / "index.sqlite3")) as connection, connection:
            connection.execute("UPDATE chunks SET vector=? WHERE id=0", (b"bad",))
        self.assertFalse(self.index().json()["reused"])

    def test_corrupt_or_missing_artifact_is_rebuilt_not_claimed_ready(self):
        self.index()
        path = self.directory / "index.sqlite3"
        path.write_bytes(b"invalid db")
        self.assertFalse(self.index().json()["reused"])
        path.unlink()
        self.assertFalse(self.index().json()["reused"])

    def test_embedding_failure_cleans_staging_and_can_retry(self):
        with patch.object(self.embedder, "embed", side_effect=DocumentError("embedding_unavailable", "Local model unavailable", 503)):
            self.assertEqual(self.index().status_code, 503)
        self.assertFalse(self.session.busy)
        self.assertEqual(self.session.document["index"]["status"], "failed")
        self.assertFalse((self.directory / "index.build.sqlite3").exists())
        self.assertFalse((self.directory / "index.sqlite3").exists())
        self.assertTrue((self.directory / "document.pdf").exists())
        self.assertEqual(self.index().status_code, 200)

    def test_invalid_vectors_and_model_change_never_publish_ready(self):
        with patch.object(self.embedder, "embed", return_value=[[0., 0., 0., 0.]]):
            self.assertEqual(self.index().status_code, 502)
        original = self.embedder.embed
        def change_model(texts, **kwargs):
            self.embedder.digest = "changed-mid-build"
            return original(texts, **kwargs)
        with patch.object(self.embedder, "embed", side_effect=change_model):
            response = self.index()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "model_changed")
        self.assertFalse((self.directory / "index.sqlite3").exists())

    def test_timeout_and_unexpected_error_are_failed_and_unlock_session(self):
        self.indexer.timeout = 0
        self.assertEqual(self.index().json()["error"]["code"], "index_timeout")
        self.indexer.timeout = 120
        with patch.object(self.embedder, "embed", side_effect=RuntimeError("private trace")):
            response = self.index()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private trace", response.text)
        self.assertFalse(self.session.busy)
        self.assertEqual(self.index().status_code, 200)

    def test_replacement_and_delete_remove_index_and_reset_state(self):
        self.index()
        old = self.directory
        self.upload("A different document to index.")
        self.assertFalse(old.exists())
        self.assertNotIn("index", self.document)
        self.index()
        self.assertEqual(self.client.delete("/api/documents", headers={"X-CSRF-Token": self.csrf}).status_code, 204)
        self.assertFalse(self.directory.exists())

    def test_failed_replacement_keeps_the_ready_index(self):
        self.index()
        response = self.client.post("/api/documents", content=b"invalid", headers={"X-CSRF-Token": self.csrf,
                                    "X-File-Name": "invalid.pdf", "Content-Type": "application/pdf"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.session.document["index"]["status"], "ready")
        self.assertTrue(self.index().json()["reused"])

    def test_same_content_in_another_session_gets_separate_index(self):
        self.index()
        other = TestClient(self.app)
        csrf = other.get("/api/documents").json()["csrf_token"]
        doc = other.post("/api/documents", content=pdf_bytes("Knowledge engine synthetic page. " * 12, pages=2),
                         headers={"X-CSRF-Token": csrf, "X-File-Name": "same.pdf", "Content-Type": "application/pdf"}).json()["document"]
        response = other.post("/api/documents/index", headers={"X-CSRF-Token": csrf, "X-Document-Id": doc["id"]})
        self.assertFalse(response.json()["reused"])
        self.assertEqual(len(list(self.store.root.rglob("index.sqlite3"))), 2)
        self.assertEqual(other.post("/api/documents/index", headers={"X-CSRF-Token": csrf, "X-Document-Id": self.document["id"]}).status_code, 409)

    def test_csrf_missing_document_and_stale_id_rejected(self):
        self.assertEqual(self.index(**{"X-CSRF-Token": ""}).status_code, 403)
        self.assertEqual(self.index(**{"Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.index(**{"X-Document-Id": "stale"}).status_code, 409)
        self.client.delete("/api/documents", headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(self.index().status_code, 409)

    def test_busy_and_global_capacity_rejected(self):
        self.session.busy = True
        self.assertEqual(self.index().status_code, 409)
        self.session.busy = False
        self.indexer.slot.acquire()
        try:
            self.assertEqual(self.index().status_code, 503)
        finally:
            self.indexer.slot.release()

    def test_expiry_removes_vectors_and_does_not_use_expired_session(self):
        self.index()
        self.session.touched -= self.store.ttl + 1
        self.assertEqual(self.index().status_code, 403)
        self.assertFalse(self.directory.exists())

    def test_mutations_block_while_indexing_and_status_reports_progress(self):
        entered, release = threading.Event(), threading.Event()
        original = self.embedder.embed
        def blocked(texts, **kwargs):
            entered.set()
            release.wait(10)
            return original(texts, **kwargs)
        result = []
        with patch.object(self.embedder, "embed", side_effect=blocked):
            thread = threading.Thread(target=lambda: result.append(self.index()))
            thread.start()
            try:
                self.assertTrue(entered.wait(10))
                data = self.client.get("/api/documents").json()
                self.assertTrue(data["processing"])
                self.assertEqual(data["document"]["index"]["status"], "indexing")
                self.assertEqual(self.client.delete("/api/documents", headers={"X-CSRF-Token": self.csrf}).status_code, 409)
                self.assertEqual(self.index().status_code, 409)
                self.session.touched -= self.store.ttl + 1
                self.store.cleanup_expired()
                self.assertTrue(self.directory.exists())
            finally:
                release.set()
                thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0].status_code, 200)


if __name__ == "__main__":
    unittest.main()

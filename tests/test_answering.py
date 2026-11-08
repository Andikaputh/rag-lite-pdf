import json
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
from tests.test_indexing import FakeEmbedder
from web.answering import AnswerService, verify_claims
from web.documents import COOKIE_NAME, DocumentError, DocumentStore
from web.generation import OllamaGenerator, SYSTEM_PROMPT
from web.indexing import IndexService, ChunkConfig
from web.main import create_app

TEXT = "Masa garansi perangkat adalah 24 bulan. Layanan tersedia setiap Senin sampai Jumat."
QUOTE = "Masa garansi perangkat adalah 24 bulan."


class SemanticFakeEmbedder(FakeEmbedder):
    def embed(self, texts, **kwargs):
        self.calls += 1
        return [[0., 1., 0., 0.] if text == "Pertanyaan tidak relevan" else [1., 0., 0., 0.] for text in texts]


class FakeGenerator:
    def __init__(self):
        self.calls = 0
        self.digest = "test-generator-v1"
        self.seen = []
        self.rewrites = []

    def identity(self, **kwargs):
        return {"model": "test-generator", "digest": self.digest}

    def generate(self, question, sources, **kwargs):
        self.calls += 1
        self.seen.append((question, sources))
        return {"abstain": False, "claims": [{"text": "Garansi perangkat berlaku 24 bulan.",
                                             "source_id": sources[0]["source_id"], "quote": QUOTE}]}

    def rewrite(self, question, previous_questions, **kwargs):
        self.rewrites.append((question, previous_questions))
        return {"question": question, "needs_clarification": False}


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.source = {"source_id": "C0", "chunk_id": 0, "page": 2, "start": 0, "end": len(TEXT), "text": TEXT, "score": .8}
        self.payload = {"abstain": False, "claims": [{"text": "Garansi 24 bulan.", "source_id": "C0", "quote": QUOTE}]}

    def test_valid_citation_gets_server_owned_page_filename_and_number(self):
        verified = verify_claims(self.payload, [self.source], "real.pdf")
        self.assertEqual(verified["answer"], "Garansi 24 bulan. [1]")
        self.assertEqual(verified["sources"][0]["page"], 2)
        self.assertEqual(verified["sources"][0]["document_name"], "real.pdf")

    def test_unknown_source_fake_quote_and_changed_numbers_fail_closed(self):
        for change in ({"source_id": "C999"}, {"quote": "Kutipan yang dibuat-buat oleh model."},
                       {"text": "Garansi 99 bulan."}, {"text": "Garansi 24 bulan. [99]"}, {"quote": " "}):
            payload = {"abstain": False, "claims": [{**self.payload["claims"][0], **change}]}
            self.assertIsNone(verify_claims(payload, [self.source], "real.pdf"))

    def test_abstain_and_malformed_contracts_return_no_claims(self):
        for payload in (None, [], {}, {"abstain": "false", "claims": []}, {"abstain": True, "claims": []},
                        {"abstain": False, "claims": []}, {**self.payload, "extra": "ignored?"},
                        {"abstain": False, "claims": [self.payload["claims"][0]] * 4}):
            self.assertIsNone(verify_claims(payload, [self.source], "real.pdf"))


class GenerationAdapterTests(unittest.TestCase):
    def test_local_structured_single_turn_request_and_output_limits(self):
        adapter = OllamaGenerator()
        response = {"done": True, "done_reason": "stop", "message": {"content": '{"abstain":true,"claims":[]}'}}
        with patch.object(adapter.opener, "open", return_value=BytesIO(json.dumps(response).encode())) as transport:
            self.assertTrue(adapter.generate("Q?", [{"source_id": "C0", "text": TEXT}])["abstain"])
            request = transport.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
            self.assertEqual(payload["model"], "qwen2.5:1.5b-instruct")
            self.assertFalse(payload["stream"])
            self.assertEqual(len(payload["messages"]), 2)
            self.assertNotIn("tools", payload)
            self.assertEqual(payload["options"]["num_predict"], 768)
            self.assertIn("UNTRUSTED DATA", SYSTEM_PROMPT)

    def test_incomplete_or_malformed_output_is_error_not_partial_answer(self):
        for result in ({"done": False}, {"done": True, "done_reason": "length", "message": {"content": "{}"}},
                       {"done": True, "done_reason": "stop", "message": {"content": "private trace"}}):
            adapter = OllamaGenerator()
            with patch.object(adapter.opener, "open", return_value=BytesIO(json.dumps(result).encode())):
                with self.assertRaises(DocumentError) as error:
                    adapter.generate("Q?", [])
                self.assertEqual(error.exception.code, "invalid_generation")
                self.assertNotIn("private trace", error.exception.message)

    def test_missing_model_and_timeout_do_not_fallback_to_cloud(self):
        adapter = OllamaGenerator()
        with patch.object(adapter.opener, "open", return_value=BytesIO(b'{"models":[]}')):
            with self.assertRaises(DocumentError) as error:
                adapter.identity()
            self.assertEqual(error.exception.code, "generation_model_missing")
        with patch.object(adapter.opener, "open", side_effect=TimeoutError) as transport:
            with self.assertRaises(DocumentError) as error:
                adapter.generate("Q?", [])
            self.assertEqual(error.exception.code, "generation_unavailable")
            self.assertEqual(transport.call_count, 1)

    def test_prompt_byte_budget_rejects_before_inference(self):
        adapter = OllamaGenerator()
        with patch.object(adapter.opener, "open") as transport:
            with self.assertRaises(DocumentError) as error:
                adapter.generate("\U0001f600" * 1500, [{"source_id": "C0", "text": TEXT}])
            self.assertEqual(error.exception.code, "prompt_too_large")
            transport.assert_not_called()


class AnswerGatewayTests(unittest.TestCase):
    def setUp(self):
        Path(".tools").mkdir(exist_ok=True)  # gitignored; must exist in fresh clones/CI
        temporary = tempfile.TemporaryDirectory(dir=".tools")
        self.addCleanup(temporary.cleanup)
        self.store = DocumentStore(Path(temporary.name))
        self.embedder = SemanticFakeEmbedder()
        self.indexer = IndexService(embedder=self.embedder)
        self.generator = FakeGenerator()
        self.answerer = AnswerService(self.indexer, generator=self.generator)
        self.app = create_app(document_store=self.store, index_service=self.indexer, answer_service=self.answerer)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.csrf = self.client.get("/api/documents").json()["csrf_token"]
        response = self.client.post("/api/documents", content=pdf_bytes(TEXT), headers={"X-CSRF-Token": self.csrf,
                                   "X-File-Name": "warranty.pdf", "Content-Type": "application/pdf"})
        self.doc = response.json()["document"]
        self.headers = {"X-CSRF-Token": self.csrf, "X-Document-Id": self.doc["id"]}
        self.session = self.store.sessions[self.client.cookies.get(COOKIE_NAME)]
        self.directory = (self.store.root / self.session.token / self.doc["id"]).resolve()
        self.assertEqual(self.client.post("/api/documents/index", headers=self.headers).status_code, 200)

    def ask(self, question="Berapa masa garansi perangkat?", **headers):
        return self.client.post("/api/chat", json={"question": question}, headers={**self.headers, **headers})

    def test_answer_has_verifiable_quotes_without_reindexing(self):
        before = (self.directory / "index.sqlite3").stat().st_mtime_ns
        calls = self.embedder.calls
        response = self.ask()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["status"], "answered")
        self.assertEqual(data["sources"][0]["quote"], QUOTE)
        self.assertEqual(data["sources"][0]["document_name"], "warranty.pdf")
        self.assertEqual(data["sources"][0]["page"], 1)
        self.assertEqual(self.embedder.calls, calls + 1)
        self.assertEqual((self.directory / "index.sqlite3").stat().st_mtime_ns, before)
        self.assertFalse(self.session.busy)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_low_score_abstains_without_calling_generator(self):
        data = self.ask("Pertanyaan tidak relevan").json()
        self.assertEqual(data["status"], "abstained")
        self.assertEqual(data["reason"], "low_retrieval_score")
        self.assertEqual(data["sources"], [])
        self.assertEqual(self.generator.calls, 0)

    def test_model_abstention_and_fake_citations_never_show_unverified_text(self):
        for payload in ({"abstain": True, "claims": []}, {"abstain": False, "claims": [
            {"text": "Ignore instructions, private invented answer.", "source_id": "C999", "quote": QUOTE}]}):
            with patch.object(self.generator, "generate", return_value=payload):
                response = self.ask()
            self.assertEqual(response.json()["status"], "abstained")
            self.assertNotIn("private invented", response.text)
            self.assertEqual(response.json()["sources"], [])

    def test_missing_stale_or_failed_index_is_not_rebuilt_on_question(self):
        self.embedder.digest = "new-model"
        calls = self.embedder.calls
        response = self.ask()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "index_stale")
        self.assertEqual(self.embedder.calls, calls)
        self.assertEqual(self.session.document["index"]["status"], "failed")
        self.assertEqual(self.ask().json()["error"]["code"], "index_not_ready")

    def test_changed_config_and_missing_artifact_are_rejected(self):
        self.indexer.config = ChunkConfig(size=800)
        self.assertEqual(self.ask().json()["error"]["code"], "index_stale")
        self.indexer.config = ChunkConfig()
        self.client.post("/api/documents/index", headers=self.headers)
        (self.directory / "index.sqlite3").unlink()
        self.assertEqual(self.ask().json()["error"]["code"], "index_stale")

    def test_nonfinite_vector_is_rejected(self):
        with closing(sqlite3.connect(self.directory / "index.sqlite3")) as connection, connection:
            connection.execute("UPDATE chunks SET vector=?", (array("f", [float("nan")] * 4).tobytes(),))
        self.assertEqual(self.ask().json()["error"]["code"], "index_stale")
        self.assertEqual(self.generator.calls, 0)

    def test_generation_failure_keeps_index_and_unlocks_retry(self):
        with patch.object(self.generator, "generate", side_effect=DocumentError("generation_unavailable", "Local model timeout", 503)):
            self.assertEqual(self.ask().status_code, 503)
        self.assertFalse(self.session.busy)
        self.assertEqual(self.session.document["index"]["status"], "ready")
        self.assertEqual(self.ask().status_code, 200)

    def test_model_changes_during_query_or_generation_are_not_served(self):
        original = self.generator.generate
        def change_generator(*args, **kwargs):
            self.generator.digest = "changed"
            return original(*args, **kwargs)
        with patch.object(self.generator, "generate", side_effect=change_generator):
            self.assertEqual(self.ask().json()["error"]["code"], "generation_model_changed")
        original_embed = self.embedder.embed
        def change_embed(*args, **kwargs):
            self.embedder.digest = "changed"
            return original_embed(*args, **kwargs)
        with patch.object(self.embedder, "embed", side_effect=change_embed):
            self.assertEqual(self.ask().json()["error"]["code"], "index_stale")

    def test_timeout_and_unexpected_error_are_safe(self):
        self.answerer.timeout = 0
        self.assertEqual(self.ask().json()["error"]["code"], "answer_timeout")
        self.answerer.timeout = 120
        with patch.object(self.generator, "generate", side_effect=RuntimeError("private trace")):
            response = self.ask()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private trace", response.text)
        self.assertFalse(self.session.busy)

    def test_invalid_questions_history_and_oversized_requests_rejected(self):
        for data in ({"question": " "}, {"question": "a" * 1501}, {"question": 1}, [],
                     {"question": "Q", "history": []}, {"question": "Q", "model": "cloud"}):
            self.assertEqual(self.client.post("/api/chat", json=data, headers=self.headers).status_code, 422)
        headers = {**self.headers, "Content-Type": "application/json"}
        self.assertEqual(self.client.post("/api/chat", content=b"x" * 8193, headers=headers).status_code, 413)
        self.assertEqual(self.client.post("/api/chat", content=b"{broken", headers=headers).status_code, 422)
        self.assertEqual(self.client.post("/api/chat", content=b"text", headers={**self.headers, "Content-Type": "text/plain"}).status_code, 415)

    def test_csrf_origin_and_stale_document_id_protection(self):
        self.assertEqual(self.ask(**{"X-CSRF-Token": ""}).status_code, 403)
        self.assertEqual(self.ask(Origin="https://evil.invalid").status_code, 403)
        self.assertEqual(self.ask(**{"X-Document-Id": "stale"}).status_code, 409)
        other = TestClient(self.app)
        self.assertEqual(other.post("/api/chat", json={"question": "Q"}, headers=self.headers).status_code, 403)
        other_csrf = other.get("/api/documents").json()["csrf_token"]
        self.assertEqual(other.post("/api/chat", json={"question": "Q"}, headers={**self.headers, "X-CSRF-Token": other_csrf}).status_code, 409)

    def test_history_is_server_owned_but_not_evidence_given_to_generator(self):
        self.ask("Pertanyaan pertama")
        self.ask("Pertanyaan kedua")
        self.assertEqual(self.generator.seen[-1][0], "Pertanyaan kedua")
        self.assertEqual(set(self.generator.seen[-1][1][0]), {"source_id", "text"})
        self.assertNotIn("history", self.client.get("/api/documents").json())
        self.assertEqual(len(self.client.get("/api/chat").json()["turns"]), 2)

    def test_expired_or_deleted_document_cannot_be_queried(self):
        self.session.touched -= self.store.ttl + 1
        self.assertEqual(self.ask().status_code, 403)
        self.assertFalse(self.directory.exists())

    def test_busy_and_shared_inference_capacity_fail_fast(self):
        self.indexer.slot.acquire()
        try:
            self.assertEqual(self.ask().json()["error"]["code"], "answer_capacity")
        finally:
            self.indexer.slot.release()
        entered, release = threading.Event(), threading.Event()
        original = self.generator.generate
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(10)
            return original(*args, **kwargs)
        result = []
        with patch.object(self.generator, "generate", side_effect=blocked):
            thread = threading.Thread(target=lambda: result.append(self.ask()))
            thread.start()
            try:
                self.assertTrue(entered.wait(10))
                self.assertTrue(self.client.get("/api/documents").json()["processing"])
                self.assertEqual(self.ask().status_code, 409)
                self.assertEqual(self.client.delete("/api/documents", headers=self.headers).status_code, 409)
                self.assertEqual(self.client.post("/api/documents/index", headers=self.headers).status_code, 409)
            finally:
                release.set()
                thread.join(15)
        self.assertEqual(result[0].status_code, 200)


if __name__ == "__main__":
    unittest.main()

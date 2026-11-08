import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.pdf_fixtures import pdf_bytes
from web.documents import COOKIE_NAME, DocumentStore
from web.main import create_app


class DocumentGatewayTests(unittest.TestCase):
    def setUp(self):
        Path(".tools").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=".tools")
        self.addCleanup(temporary.cleanup)
        self.store = DocumentStore(Path(temporary.name), max_pages=3)
        self.app = create_app(document_store=self.store)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        data = self.client.get("/api/documents").json()
        self.headers = {"X-CSRF-Token": data["csrf_token"], "X-File-Name": "sample.pdf", "Content-Type": "application/pdf"}

    def upload(self, content=None, **headers):
        return self.client.post("/api/documents", content=pdf_bytes() if content is None else content,
                                headers={**self.headers, **headers})

    def assert_error(self, response, code, status=422):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["error"]["code"], code)
        self.assertNotIn(str(self.store.root), response.text)

    def test_valid_upload_persists_pdf_and_page_text_privately(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        doc = response.json()["document"]
        self.assertEqual(doc["status"], "validated")
        self.assertEqual(doc["page_count"], 1)
        self.assertGreater(doc["text_characters"], 0)
        self.assertEqual(len(doc["sha256"]), 64)
        self.assertNotIn("pages", doc)
        session = self.store.sessions[self.client.cookies.get(COOKIE_NAME)]
        folder = self.store.root / session.token / doc["id"]
        self.assertTrue((folder / "document.pdf").is_file())
        self.assertIn("Folio synthetic", (folder / "pages.json").read_text())
        self.assertEqual(self.client.get("/api/documents").json()["document"], doc)
        self.assertEqual(self.client.get(f"/static/{doc['id']}/document.pdf").status_code, 404)

    def test_empty_bytes_rejected(self):
        self.assert_error(self.upload(b""), "empty_file")

    def test_fake_pdf_signature_rejected(self):
        self.assert_error(self.upload(b"not a pdf"), "invalid_signature")

    def test_corrupt_pdf_rejected(self):
        self.assert_error(self.upload(b"%PDF-1.7\ninvalid"), "corrupt_pdf")

    def test_encrypted_pdf_rejected(self):
        self.assert_error(self.upload(pdf_bytes(encrypted=True)), "encrypted_pdf")

    def test_blank_or_scanned_pdf_reports_ocr_unavailable(self):
        response = self.upload(pdf_bytes(text=""))
        self.assert_error(response, "no_text")
        self.assertIn("OCR", response.json()["error"]["message"])

    def test_zero_pages_rejected(self):
        self.assert_error(self.upload(pdf_bytes(pages=0)), "empty_pdf")

    def test_page_limit_rejected(self):
        self.assert_error(self.upload(pdf_bytes(pages=4)), "too_many_pages")

    def test_text_limit_rejected(self):
        self.store.max_chars = 5
        self.assert_error(self.upload(), "too_much_text")

    def test_partial_empty_pages_accepted_with_warning_metadata(self):
        doc = self.upload(pdf_bytes(pages=2, blank_last=True)).json()["document"]
        self.assertEqual(doc["page_count"], 2)
        self.assertEqual(doc["empty_pages"], 1)

    def test_extension_and_mime_are_checked(self):
        self.assert_error(self.upload(**{"X-File-Name": "bad.exe"}), "invalid_filename", 415)
        self.assert_error(self.upload(**{"Content-Type": "text/plain"}), "invalid_type", 415)

    def test_filename_is_display_only_and_cannot_traverse(self):
        response = self.upload(**{"X-File-Name": "..%2F..%2Fsample.pdf"})
        self.assertEqual(response.json()["document"]["name"], "sample.pdf")
        self.assertFalse((self.store.root / "sample.pdf").exists())

    def test_declared_and_chunked_body_size_limits(self):
        self.store.max_bytes = 10
        self.assert_error(self.upload(b"x" * 11), "too_large", 413)
        response = self.client.post("/api/documents", headers=self.headers, content=iter([b"%PDF-", b"x" * 6]))
        self.assert_error(response, "too_large", 413)
        self.assertEqual(list(self.store.root.rglob("incoming.pdf")), [])

    def test_session_isolation_and_no_document_by_id_endpoint(self):
        doc = self.upload().json()["document"]
        other = TestClient(self.app)
        other_data = other.get("/api/documents").json()
        self.assertIsNone(other_data["document"])
        self.assertEqual(other.delete("/api/documents", headers={"X-CSRF-Token": other_data["csrf_token"]}).status_code, 204)
        self.assertEqual(self.client.get("/api/documents").json()["document"]["id"], doc["id"])
        self.assertEqual(other.get(f"/api/documents/{doc['id']}").status_code, 404)

    def test_missing_or_wrong_csrf_and_cross_origin_rejected(self):
        self.assert_error(self.upload(**{"X-CSRF-Token": ""}), "csrf_rejected", 403)
        self.assert_error(self.upload(**{"X-CSRF-Token": "wrong"}), "csrf_rejected", 403)
        self.assert_error(self.upload(Origin="https://evil.invalid"), "origin_rejected", 403)
        self.assert_error(self.upload(**{"Sec-Fetch-Site": "cross-site"}), "origin_rejected", 403)
        self.assert_error(TestClient(self.app).post("/api/documents", content=pdf_bytes(), headers=self.headers), "session_expired", 403)

    def test_cookie_is_http_only_strict_and_api_not_cached(self):
        response = self.client.get("/api/documents")
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertEqual(response.headers["cache-control"], "no-store")
        secure = TestClient(self.app, base_url="https://testserver").get("/api/documents")
        self.assertIn("secure", secure.headers["set-cookie"].lower())

    def test_atomic_replacement_and_failure_preserves_old_document(self):
        first = self.upload().json()["document"]
        self.assert_error(self.upload(b"broken"), "invalid_signature")
        self.assertEqual(self.client.get("/api/documents").json()["document"], first)
        second = self.upload(pdf_bytes("Replacement document.")).json()["document"]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(list(self.store.root.rglob("document.pdf"))), 1)
        self.assertFalse(any(self.store.root.rglob(first["id"])))

    def test_delete_is_idempotent_and_cleans_pdf_and_text(self):
        self.upload()
        for _ in range(2):
            self.assertEqual(self.client.delete("/api/documents", headers=self.headers).status_code, 204)
        self.assertIsNone(self.client.get("/api/documents").json()["document"])
        self.assertEqual(list(self.store.root.rglob("document.pdf")), [])
        self.assertEqual(list(self.store.root.rglob("pages.json")), [])

    def test_parser_timeout_and_failure_cleanup_allow_retry(self):
        with patch("web.documents.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 20)):
            self.assert_error(self.upload(), "parse_timeout")
        with patch("web.documents.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            self.assert_error(self.upload(), "parser_failed")
        self.assertEqual(list(self.store.root.rglob("incoming.pdf")), [])
        self.assertFalse(next(iter(self.store.sessions.values())).busy)
        self.assertEqual(self.upload().status_code, 201)

    def test_busy_session_and_parser_capacity_are_bounded(self):
        session = next(iter(self.store.sessions.values()))
        self.store.begin_upload(session)
        try:
            self.assert_error(self.upload(), "busy", 409)
            self.assert_error(self.client.delete("/api/documents", headers=self.headers), "busy", 409)
        finally:
            self.store.end_upload(session)
        self.store.parsers.acquire()
        self.store.parsers.acquire()
        try:
            self.assert_error(self.upload(), "capacity", 503)
        finally:
            self.store.parsers.release()
            self.store.parsers.release()

    def test_expiry_removes_files_and_rotates_unknown_session(self):
        self.upload()
        token = self.client.cookies.get(COOKIE_NAME)
        self.store.sessions[token].touched -= self.store.ttl + 1
        self.assert_error(self.client.delete("/api/documents", headers=self.headers), "session_expired", 403)
        self.assertFalse((self.store.root / token).exists())
        response = self.client.get("/api/documents")
        self.assertIsNone(response.json()["document"])
        self.assertNotEqual(self.client.cookies.get(COOKIE_NAME), token)

    def test_session_quota(self):
        self.store.max_sessions = 1
        self.assert_error(TestClient(self.app).get("/api/documents"), "capacity", 503)

    def test_shutdown_removes_run_directory(self):
        self.upload()
        self.store.close()
        self.assertFalse(self.store.root.exists())


if __name__ == "__main__":
    unittest.main()

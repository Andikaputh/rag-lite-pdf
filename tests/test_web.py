"""Offline acceptance checks for checkpoint 01. No model/API calls."""
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.main import create_app


class WebFoundationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_home_renders_new_workspace(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="en"', response.text)
        self.assertIn("Clarity starts here", response.text)
        self.assertIn('id="campaign-view"', response.text)
        self.assertNotIn("Masukkan Groq API Key", response.text)

    def test_health_does_not_claim_rag_ready(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        uptime = data.pop("uptime_s")
        self.assertIsInstance(uptime, int)
        self.assertGreaterEqual(uptime, 0)
        self.assertEqual(data, {"status": "ok", "service": "folio-web", "rag_available": True, "rag_ready": None, "models_checked": False})

    def test_campaign_is_fully_cleared(self):
        data = self.client.get("/api/checkpoints").json()
        self.assertEqual(data["summary"], {"completed": 8, "total": 8, "next_id": None})
        self.assertEqual(len({item["id"] for item in data["checkpoints"]}), 8)
        self.assertEqual([item["id"] for item in data["checkpoints"] if item["status"] == "done"], ["01", "02", "03", "04", "05", "06", "07", "08"])
        self.assertTrue(all(len(item["criteria"]) == 3 for item in data["checkpoints"]))

    def test_assets_are_served_with_correct_mime_type(self):
        for name, mime in (("app.css", "text/css"), ("tokens.css", "text/css"),
                           ("app.js", "javascript"), ("documents.js", "javascript"), ("chat.js", "javascript"), ("favicon.svg", "image/svg+xml")):
            with self.subTest(name=name):
                response = self.client.get(f"/static/{name}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(mime, response.headers["content-type"])

    def test_upload_and_chat_are_session_gated(self):
        page = self.client.get("/").text
        self.assertIn("Preparing your session", page)
        self.assertIn('id="question"', page)
        self.assertIn('disabled aria-describedby="upload-note"', page)
        self.assertEqual(self.client.post("/api/documents").status_code, 403)
        self.assertEqual(self.client.post("/api/chat").status_code, 403)

    def test_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertIn("script-src 'self'", response.headers["content-security-policy"])

    def test_app_is_independent_of_working_directory(self):
        with patch("pathlib.Path.cwd", return_value=Path("unrelated")):
            client = TestClient(create_app())
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/static/app.css").status_code, 200)

    def test_static_assets_are_referenced_relatively(self):
        page = self.client.get("/").text
        for name in ("favicon.svg", "app.css", "app.js", "documents.js", "chat.js"):
            with self.subTest(name=name):
                self.assertIn(f'"/static/{name}"', page)
        self.assertNotRegex(page, r'(?:href|src)="https?://[^"]*/static/')

    def test_server_does_not_accept_public_checkpoint_mutation(self):
        self.assertEqual(self.client.post("/api/checkpoints", json={"id": "08", "status": "done"}).status_code, 405)


if __name__ == "__main__":
    unittest.main()

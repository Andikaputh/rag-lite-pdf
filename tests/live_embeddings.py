"""Explicit opt-in local model smoke: python -m tests.live_embeddings.

Uses only generated synthetic text, fixed loopback Ollama, and a temporary store.
Never part of default offline test discovery; never auto-downloads a model.
"""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from tests.pdf_fixtures import pdf_bytes
from web.documents import DocumentStore
from web.indexing import IndexService
from web.main import create_app


def main():
    with tempfile.TemporaryDirectory(prefix="folio-live-") as directory:
        store = DocumentStore(Path(directory))
        with TestClient(create_app(document_store=store, index_service=IndexService())) as client:
            csrf = client.get("/api/documents").json()["csrf_token"]
            pdf = pdf_bytes("Dokumen sintetis. Energi matahari menghasilkan listrik. This is synthetic test data.")
            response = client.post("/api/documents", content=pdf, headers={"X-CSRF-Token": csrf,
                                   "X-File-Name": "synthetic.pdf", "Content-Type": "application/pdf"})
            assert response.status_code == 201, response.text
            doc = response.json()["document"]
            headers = {"X-CSRF-Token": csrf, "X-Document-Id": doc["id"]}
            result = client.post("/api/documents/index", headers=headers)
            assert result.status_code == 200, result.text
            first = result.json()
            assert first["document"]["index"]["dimensions"] == 1024
            assert not first["reused"]
            second = client.post("/api/documents/index", headers=headers)
            assert second.status_code == 200 and second.json()["reused"], second.text
            assert client.delete("/api/documents", headers={"X-CSRF-Token": csrf}).status_code == 204
            assert not list(store.root.rglob("index.sqlite3"))
            print(json.dumps({"result": "pass", "local_model": first["document"]["index"]["model"],
                              "digest": first["document"]["index"]["model_digest"], "dimensions": 1024,
                              "chunks": first["document"]["index"]["chunk_count"], "reuse": True, "delete_cleanup": True}, indent=2))


if __name__ == "__main__":
    main()

"""Opt-in synthetic follow-up smoke: python -m tests.live_conversations."""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from tests.pdf_fixtures import pdf_bytes
from web.documents import DocumentStore
from web.main import create_app


def main():
    text = "Masa garansi perangkat adalah 24 bulan. Layanan pelanggan tersedia setiap Senin sampai Jumat."
    with tempfile.TemporaryDirectory(prefix="folio-live-") as directory:
        store = DocumentStore(Path(directory))
        with TestClient(create_app(document_store=store)) as client:
            csrf = client.get("/api/documents").json()["csrf_token"]
            doc = client.post("/api/documents", content=pdf_bytes(text), headers={"X-CSRF-Token": csrf,
                              "X-File-Name": "followup.pdf", "Content-Type": "application/pdf"}).json()["document"]
            headers = {"X-CSRF-Token": csrf, "X-Document-Id": doc["id"]}
            assert client.post("/api/documents/index", headers=headers).status_code == 200
            first = client.post("/api/chat", json={"question": "Berapa lama masa garansi perangkat?"}, headers=headers)
            assert first.status_code == 200 and first.json()["status"] == "answered", first.text
            followup = client.post("/api/chat", json={"question": "Bisa ulangi berapa bulan?"}, headers=headers)
            assert followup.status_code == 200, followup.text
            data = followup.json()
            assert data["status"] == "answered" and data["used_history"] and "24" in data["answer"], data
            assert "garansi" in data["resolved_question"].lower(), data
            assert all(s["quote"] in text for s in data["sources"])
            history = client.get("/api/chat").json()
            assert len(history["turns"]) == 2
            reset = client.delete("/api/chat", headers={**headers, "X-Conversation-Revision": str(history["revision"])})
            assert reset.status_code == 200 and reset.json()["turns"] == [], reset.text
            assert client.get("/api/documents").json()["document"]["index"]["status"] == "ready"
            print(json.dumps({"result": "pass", "followup_question": "Bisa ulangi berapa bulan?",
                              "resolved_question": data["resolved_question"], "answer": data["answer"],
                              "history_turns": 2, "reset_preserves_index": True}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

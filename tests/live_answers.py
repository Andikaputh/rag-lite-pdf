"""Opt-in synthetic RAG smoke: python -m tests.live_answers. No model downloads."""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from tests.pdf_fixtures import pdf_bytes
from web.documents import DocumentStore
from web.main import create_app


def main():
    source_text = "Masa garansi perangkat adalah 24 bulan. Layanan pelanggan tersedia setiap Senin sampai Jumat."
    with tempfile.TemporaryDirectory(prefix="folio-live-") as directory:
        store = DocumentStore(Path(directory))
        with TestClient(create_app(document_store=store)) as client:
            csrf = client.get("/api/documents").json()["csrf_token"]
            document = client.post("/api/documents", content=pdf_bytes(source_text), headers={"X-CSRF-Token": csrf,
                                   "X-File-Name": "synthetic-warranty.pdf", "Content-Type": "application/pdf"}).json()["document"]
            headers = {"X-CSRF-Token": csrf, "X-Document-Id": document["id"]}
            index = client.post("/api/documents/index", headers=headers)
            assert index.status_code == 200, index.text
            response = client.post("/api/chat", json={"question": "Berapa lama masa garansi perangkat?", "use_history": False}, headers=headers)
            assert response.status_code == 200, response.text
            answer = response.json()
            assert answer["status"] == "answered", answer
            assert "24" in answer["answer"], answer
            assert answer["sources"] and all(s["quote"] in source_text and s["page"] == 1 for s in answer["sources"]), answer
            negative = client.post("/api/chat", json={"question": "Siapa juara Piala Dunia sepak bola tahun 2022?", "use_history": False}, headers=headers)
            assert negative.status_code == 200 and negative.json()["status"] == "abstained", negative.text
            missing_fact = client.post("/api/chat", json={"question": "Berapa harga perangkat ini dalam rupiah?", "use_history": False}, headers=headers)
            assert missing_fact.status_code == 200 and missing_fact.json()["status"] == "abstained", missing_fact.text
            client.delete("/api/documents", headers=headers)
            assert not list(store.root.rglob("index.sqlite3"))
            print(json.dumps({"result": "pass", "answer": answer["answer"], "sources": answer["sources"],
                              "model": answer["model"], "model_digest": answer["model_digest"],
                              "negative_question": negative.json()["reason"], "missing_fact": missing_fact.json()["reason"], "cleanup": True}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

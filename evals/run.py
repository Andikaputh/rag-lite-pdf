"""Serial, opt-in local-model evaluation. python -m evals.run --help."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from evals.dataset import DEFAULT_DATASET, load_dataset
from evals.fixtures import build_pdf
from evals.metrics import score_case, summarize
from evals.report import save_report
from web.answering import AnswerService
from web.documents import DocumentStore
from web.indexing import IndexService
from web.main import create_app
from web.embeddings import OllamaEmbedder
from web.policies import configured_strategy, generator_for

ROOT = Path(__file__).resolve().parent.parent


def code_digest():
    files = [p for folder in (ROOT / "web", ROOT / "evals") for p in folder.glob("*.py") if p.name != "checkpoints.py"]
    value = hashlib.sha256()
    for path in sorted(files):
        value.update(path.relative_to(ROOT).as_posix().encode())
        value.update(path.read_bytes())
    return value.hexdigest()


def run_evaluation(*, dataset_path=DEFAULT_DATASET, split="dev", min_score=.35, indexer=None, generator=None, answer_strategy=None):
    if split not in ("dev", "holdout") or not 0 <= min_score <= 1:
        raise ValueError("Invalid split/threshold")
    dataset = load_dataset(dataset_path)
    selected = [c for c in dataset["cases"] if c["split"] == split]
    if not selected:
        raise ValueError("Selected split has no cases")
    indexer = indexer or IndexService()
    generator = generator or generator_for(answer_strategy or configured_strategy())
    capture = {"retrieved": None}
    def observe(sources):
        capture["retrieved"] = sources
    answerer = AnswerService(indexer, generator=generator, min_score=min_score, retrieval_observer=observe)
    if answer_strategy and answerer.answer_strategy != answer_strategy:
        raise ValueError("Injected generator does not match requested strategy")
    # Fail before a run if models are unavailable: never publish a fake all-zero baseline.
    embedding = indexer.embedder.identity()
    generation = answerer.generator.identity()
    ollama_version = indexer.embedder._request("/api/version", timeout=5).get("version") if isinstance(indexer.embedder, OllamaEmbedder) else "test-double"
    fingerprint = code_digest()
    metadata = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
                "dataset_version": dataset["version"], "dataset_name": Path(dataset_path).name, "dataset_sha256": dataset["sha256"],
                "code_sha256": fingerprint, "split": split, "min_score": min_score,
                "top_k": 5, "embedding": embedding, "generation": generation,
                "answer_strategy": answerer.answer_strategy,
                "policy_revision": getattr(answerer.generator, "policy_revision", 1),
                "chunking": vars(indexer.config), "protocol": "serial-local-v1", "seed": 42,
                "environment": {"python": platform.python_version(), "platform": platform.system(), "ollama_version": ollama_version,
                                "packages": {name: importlib.metadata.version(name) for name in ("fastapi", "pypdf", "uvicorn")}},
                "models_changed": False, "source_changed": False}
    rows, document_timings = [], []
    scratch = ROOT / ".tools"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="evaluation-", dir=scratch) as temporary:
        store = DocumentStore(Path(temporary))
        # One harness session legitimately drives the whole dataset through
        # POST /api/chat, so its app instance runs without the per-session chat
        # rate limit. The live server keeps 30/60s; no HTTP path can disable it.
        with TestClient(create_app(document_store=store, index_service=indexer, answer_service=answerer,
                                   chat_rate_limit=None)) as client:
            csrf = client.get("/api/documents").json()["csrf_token"]
            documents = {d["id"]: d for d in dataset["documents"]}
            for document_id in dict.fromkeys(c["document"] for c in selected):
                fixture = documents[document_id]
                start = time.perf_counter()
                response = client.post("/api/documents", content=build_pdf(fixture["pages"]), headers={
                    "X-CSRF-Token": csrf, "X-File-Name": f"{document_id}.pdf", "Content-Type": "application/pdf"})
                if response.status_code != 201:
                    raise RuntimeError(f"Synthetic ingestion failed: {document_id}: {response.text}")
                document = response.json()["document"]
                ingestion_ms = round((time.perf_counter() - start) * 1000, 2)
                headers = {"X-CSRF-Token": csrf, "X-Document-Id": document["id"]}
                start = time.perf_counter()
                indexed = client.post("/api/documents/index", headers=headers)
                if indexed.status_code != 200:
                    raise RuntimeError(f"Synthetic indexing failed: {document_id}: {indexed.text}")
                document_timings.append({"document": document_id, "ingestion_ms": ingestion_ms,
                                         "index_ms": round((time.perf_counter() - start) * 1000, 2)})
                session = store.get_session(client.cookies.get("folio_session"))
                pages = json.loads((store.root / session.token / document["id"] / "pages.json").read_text(encoding="utf-8"))
                for case in (c for c in selected if c["document"] == document_id):
                    if client.delete("/api/chat", headers=headers).status_code != 200:
                        raise RuntimeError("Case isolation reset failed")
                    setup, setup_ok = [], True
                    for question in case.get("setup", []):
                        start = time.perf_counter()
                        response = client.post("/api/chat", json={"question": question, "use_history": False}, headers=headers)
                        body = response.json()
                        setup.append({"question": question, "http_status": response.status_code, "response": body,
                                      "latency_ms": round((time.perf_counter() - start) * 1000, 2)})
                        if response.status_code != 200 or body.get("status") != "answered":
                            setup_ok = False
                            break
                    if case.get("reset_before"):
                        if client.delete("/api/chat", headers=headers).status_code != 200:
                            raise RuntimeError("Scenario reset failed")
                    capture["retrieved"] = None
                    latency = None
                    if setup_ok:
                        start = time.perf_counter()
                        response = client.post("/api/chat", json={"question": case["question"], "use_history": case.get("use_history", False)}, headers=headers)
                        latency = round((time.perf_counter() - start) * 1000, 2)
                        body = response.json()
                        if response.status_code != 200:
                            body = {"status": "error", "http_status": response.status_code, "error": body.get("error", {})}
                    else:
                        body = {"status": "error", "error": {"code": "setup_failed", "message": "Follow-up setup did not produce a verified answer"}}
                    history_count = len(client.get("/api/chat").json()["turns"])
                    row = score_case(case, body, capture["retrieved"], pages, history_count=history_count, setup_ok=setup_ok)
                    row.update(question=case["question"], response=body, setup=setup, answer_latency_ms=latency,
                               retrieved=[{k: c[k] for k in ("chunk_id", "page", "score", "start", "end")} for c in capture["retrieved"] or []])
                    rows.append(row)
                    print(f"{case['id']}: {row['actual_status']} / proxy {'PASS' if row['proxy_pass'] else 'FAIL'} / {latency} ms", flush=True)
            if client.delete("/api/documents", headers={"X-CSRF-Token": csrf}).status_code != 204:
                raise RuntimeError("Fixture cleanup failed")
    metadata["source_changed"] = code_digest() != fingerprint
    metadata["models_changed"] = indexer.embedder.identity() != embedding or answerer.generator.identity() != generation
    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    report = {"metadata": metadata, "document_timings": document_timings, "cases": rows, "summary": summarize(rows),
              "by_language": {lang: summarize([r for r in rows if r["language"] == lang]) for lang in sorted({r["language"] for r in rows})},
              "by_tag": {tag: summarize([r for r in rows if tag in r["tags"]]) for tag in sorted({tag for r in rows for tag in r["tags"]})}}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--min-score", type=float, default=.35)
    parser.add_argument("--answer-strategy", choices=("legacy_v1", "extractive_v2", "focused_v3"), help="Defaults to operator policy; never changes production config")
    parser.add_argument("--out", type=Path, required=True, help="New directory; existing runs are never overwritten")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; choose a new run name")
    report = run_evaluation(dataset_path=args.dataset, split=args.split, min_score=args.min_score, answer_strategy=args.answer_strategy)
    save_report(report, args.out)
    print(f"Report saved: {args.out / 'report.md'}")
    if report["metadata"]["source_changed"] or report["metadata"]["models_changed"]:
        raise SystemExit("Run invalid for comparison: model/source changed during execution")


if __name__ == "__main__":
    main()

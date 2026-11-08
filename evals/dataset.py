"""Validate a versioned synthetic-only diagnostic corpus before making model calls."""
import hashlib
import json
import re
from pathlib import Path

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "rag-v1.json"


def normalize(text):
    return " ".join(text.split()).casefold()


def load_dataset(path=DEFAULT_DATASET):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("synthetic") is not True or not isinstance(data.get("version"), str):
        raise ValueError("Only schema-v1, explicitly synthetic datasets are supported")
    documents = data.get("documents")
    cases = data.get("cases")
    if not isinstance(documents, list) or not 1 <= len(documents) <= 20 or not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise ValueError("Invalid dataset size")
    by_id = {}
    for document in documents:
        name, pages = document.get("id"), document.get("pages")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name) or name in by_id or not isinstance(pages, list) or not 1 <= len(pages) <= 100:
            raise ValueError("Invalid/duplicate document")
        if any(not isinstance(p, str) or not p.strip() or not p.isascii() or len(p) > 10000 for p in pages):
            raise ValueError("v1 PDF fixtures require nonempty ASCII text pages <=10000 chars")
        by_id[name] = document
    seen = set()
    for case in cases:
        name = case.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name) or name in seen:
            raise ValueError("Invalid/duplicate case ID")
        seen.add(name)
        if case.get("document") not in by_id or case.get("split") not in ("dev", "holdout") or case.get("language") not in ("id", "en"):
            raise ValueError(f"Invalid case scope: {name}")
        if not isinstance(case.get("question"), str) or not 1 <= len(case["question"].strip()) <= 1500 or case.get("expected_status") not in ("answered", "abstained"):
            raise ValueError(f"Invalid question/status: {name}")
        evidence = case.get("evidence")
        if not isinstance(evidence, list) or (case["expected_status"] == "answered" and not evidence):
            raise ValueError(f"Missing evidence: {name}")
        if case["expected_status"] == "abstained" and evidence:
            raise ValueError(f"Unanswerable cases must not contain gold evidence: {name}")
        if "expected_history_count" in case and (type(case["expected_history_count"]) is not int or not 0 <= case["expected_history_count"] <= 6):
            raise ValueError(f"Invalid history count: {name}")
        for item in evidence:
            page, quote = item.get("page"), item.get("quote")
            pages = by_id[case["document"]]["pages"]
            if type(page) is not int or not 1 <= page <= len(pages) or not isinstance(quote, str) or not quote.strip() or normalize(quote) not in normalize(pages[page - 1]):
                raise ValueError(f"Gold evidence not in fixture: {name}")
        for field in ("use_history", "expected_used_history", "reset_before", "preserve_question"):
            if field in case and type(case[field]) is not bool:
                raise ValueError(f"Invalid boolean {field}: {name}")
        if not isinstance(case.get("tags"), list) or not all(isinstance(t, str) for t in case["tags"]):
            raise ValueError(f"Invalid tags: {name}")
        for field in ("setup", "forbidden", "resolved_contains"):
            if not isinstance(case.get(field, []), list) or not all(isinstance(q, str) and 1 <= len(q) <= 1500 for q in case.get(field, [])):
                raise ValueError(f"Invalid {field}: {name}")
        if len(case.get("setup", [])) > 3:
            raise ValueError("Setup limited to three questions")
        groups = case.get("contains_any")
        if not isinstance(groups, list) or not all(isinstance(g, list) and g and all(isinstance(t, str) and t.strip() for t in g) for g in groups):
            raise ValueError(f"Invalid content proxies: {name}")
    data["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return data

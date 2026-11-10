"""Mechanical metrics only. Quote integrity is not semantic faithfulness."""
import hashlib
import json
import math
import re
import statistics
from collections import Counter

from evals.dataset import normalize
from evals.derivations import check_derivation


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def contains_term(text, term):
    return re.search(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)", normalize(text)) is not None


def score_case(case, response, retrieved, pages, *, history_count=None, setup_ok=True):
    gold = case["evidence"]
    candidates = retrieved or []
    status = response.get("status", "error")
    answer = response.get("answer", "")
    citations = response.get("sources", [])
    claims = response.get("claims", [])
    derivations = [check_derivation(claim, citations) for claim in claims if "derivation" in claim]
    retrieved_gold = [i for i, e in enumerate(gold) if any(c["page"] == e["page"] and normalize(e["quote"]) in normalize(c["text"]) for c in candidates)]
    retrieved_gold_at_3 = [i for i, e in enumerate(gold) if any(c["page"] == e["page"] and normalize(e["quote"]) in normalize(c["text"]) for c in candidates[:3])]
    checks = []
    for citation in citations:
        page, quote = citation.get("page"), citation.get("quote")
        in_page = type(page) is int and 1 <= page <= len(pages) and isinstance(quote, str) and bool(quote.strip()) and normalize(quote) in normalize(pages[page - 1]["text"])
        in_chunk = any(c["page"] == page and c["chunk_id"] == citation.get("chunk_id") and isinstance(quote, str) and normalize(quote) in normalize(c["text"]) for c in candidates)
        checks.append({"number": citation.get("number"), "valid": bool(in_page and in_chunk)})
    valid_sources = [c for c, check in zip(citations, checks) if check["valid"]]
    cited_gold = [i for i, e in enumerate(gold) if any(c["page"] == e["page"] and normalize(e["quote"]) in normalize(c["quote"]) for c in valid_sources)]
    content = all(any(contains_term(answer, term) for term in group) for group in case["contains_any"])
    forbidden = [term for term in case.get("forbidden", []) if normalize(term) in normalize(answer)]
    citation_structure = (
        bool(citations and claims) and all(c["valid"] for c in checks)
        and [c.get("number") for c in citations] == list(range(1, len(citations) + 1))
        and all(c.get("citation") in {s["number"] for s in citations} for c in claims)
    ) if status == "answered" else not citations and not claims
    flags = {
        "setup": setup_ok, "status": status == case["expected_status"], "content_proxy": content,
        "no_forbidden_output": not forbidden, "quote_structure": bool(citation_structure),
        "used_history": "expected_used_history" not in case or response.get("used_history") is case["expected_used_history"],
        "history_count": "expected_history_count" not in case or history_count == case["expected_history_count"],
        "resolved_topic_proxy": all(contains_term(response.get("resolved_question", ""), term) for term in case.get("resolved_contains", [])),
        "question_preserved": not case.get("preserve_question") or response.get("resolved_question", "").startswith(case["question"].strip()),
        "derivation_math": all(derivations) and (response.get("answer_mode") != "derived" or bool(derivations)),
    }
    if case["expected_status"] == "answered":
        flags["gold_retrieval"] = len(retrieved_gold) == len(gold)
        flags["gold_cited_evidence"] = len(cited_gold) == len(gold)
    return {"id": case["id"], "language": case["language"], "tags": case["tags"],
            "expected_status": case["expected_status"], "actual_status": status,
            "abstention_reason": response.get("reason") if status == "abstained" else None,
            "proxy_pass": all(flags.values()), "checks": flags,
            "failed_checks": [name for name, ok in flags.items() if not ok],
            "retrieval_attempted": retrieved is not None, "gold_evidence_count": len(gold),
            "retrieved_gold": retrieved_gold, "retrieved_gold_at_3": retrieved_gold_at_3, "cited_gold": cited_gold,
            "quote_checks": checks, "derivation_checks": derivations, "forbidden_hits": forbidden,
            "response_sha256": digest(response), "faithfulness": None, "semantic_citation_correctness": None}


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def summarize(rows):
    positive = [r for r in rows if r["expected_status"] == "answered"]
    negative = [r for r in rows if r["expected_status"] == "abstained"]
    abstained = [r for r in rows if r["actual_status"] == "abstained"]
    followups = [r for r in rows if "follow_up" in r["tags"]]
    latencies = sorted(r["answer_latency_ms"] for r in rows if r.get("answer_latency_ms") is not None)
    quotes = [c for r in rows for c in r["quote_checks"]]
    evidence_count = sum(r["gold_evidence_count"] for r in positive)
    return {
        "cases": len(rows),
        "abstention_reasons": dict(Counter(r.get("abstention_reason") or "unspecified" for r in abstained)),
        "scenario_proxy_pass": rate(sum(r["proxy_pass"] for r in rows), len(rows)),
        "retrieval_recall_at_3": rate(sum(len(r["retrieved_gold_at_3"]) for r in positive), evidence_count),
        "gold_cited_evidence_recall": rate(sum(len(r["cited_gold"]) for r in positive), evidence_count),
        "quote_integrity": rate(sum(c["valid"] for c in quotes), len(quotes)),
        "derivation_math_validity": rate(sum(check for r in rows for check in r.get("derivation_checks", [])), sum(len(r.get("derivation_checks", [])) for r in rows)),
        "answer_rate_on_answerable": rate(sum(r["actual_status"] == "answered" for r in positive), len(positive)),
        "over_abstention_rate": rate(sum(r["actual_status"] == "abstained" for r in positive), len(positive)),
        "abstention_recall": rate(sum(r["actual_status"] == "abstained" for r in negative), len(negative)),
        "abstention_precision": rate(sum(r["expected_status"] == "abstained" for r in abstained), len(abstained)),
        "error_rate": rate(sum(r["actual_status"] == "error" for r in rows), len(rows)),
        "followup_proxy_pass": rate(sum(r["proxy_pass"] for r in followups), len(followups)),
        "forbidden_output_cases": sum(bool(r["forbidden_hits"]) for r in rows),
        "answer_latency_ms": {"samples": len(latencies), "p50": statistics.median(latencies) if latencies else None,
                              "p95": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None},
        "faithfulness": {"value": None, "reviewed": 0, "method": "pending independent semantic review; not inferred from quotes/content proxies"},
        "semantic_citation_correctness": {"value": None, "reviewed": 0, "method": "pending semantic review"},
    }

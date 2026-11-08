"""Validate explicitly supplied semantic review labels; never invent reviewer scores."""
import argparse
import json
from pathlib import Path

from evals.metrics import rate


def summarize_review(report, labels):
    if not isinstance(labels.get("reviewer"), str) or not labels["reviewer"].strip() or labels.get("reviewer_type") not in ("human", "agent"):
        raise ValueError("Declare reviewer and reviewer_type (human/agent); this is self-reported, not identity verification")
    for key in ("dataset_sha256", "code_sha256"):
        if labels.get(key) != report["metadata"][key]:
            raise ValueError(f"Stale review: {key}")
    expected = {r["id"]: r for r in report["cases"] if r["actual_status"] == "answered"}
    entries = labels.get("cases", [])
    if len(entries) != len(expected) or len({r["id"] for r in entries}) != len(entries) or {r["id"] for r in entries} != set(expected):
        raise ValueError("Review must retain exactly the answered case IDs")
    fields = {name: [] for name in ("relevant", "supported", "complete")}
    for entry in entries:
        if entry["response_sha256"] != expected[entry["id"]]["response_sha256"]:
            raise ValueError("Stale review: response hash differs")
        for field in fields:
            value = entry.get(field)
            if value is not None and type(value) is not bool:
                raise ValueError("Review labels must be true/false/null, not strings or scores")
            if value is not None:
                fields[field].append(value)
    return {"reviewer": labels["reviewer"], "reviewer_type": labels["reviewer_type"],
            "scope": "Self-reported semantic review of these exact responses only; not a security or quality certification",
            "answered_cases": len(expected),
            "ratings": {name: rate(sum(values), len(values)) for name, values in fields.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize_review(json.loads(args.report.read_text(encoding="utf-8")), json.loads(args.labels.read_text(encoding="utf-8")))
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(summary, target, ensure_ascii=False, indent=2)
    print(args.out)


if __name__ == "__main__":
    main()

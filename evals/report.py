"""Human-readable report with explicit denominators and unanswered review fields."""
import json
from pathlib import Path


def display_rate(value):
    if value["value"] is None:
        return f"N/A ({value['numerator']}/{value['denominator']})"
    return f"{value['value']:.1%} ({value['numerator']}/{value['denominator']})"


def markdown(report):
    meta, summary = report["metadata"], report["summary"]
    lines = [f"# RAG diagnostic — {meta['split']} / threshold {meta['min_score']}", "",
             "> Small synthetic diagnostic, not a production/readiness/accuracy guarantee. Quote integrity is NOT faithfulness.", "",
             f"Dataset: `{meta['dataset_version']}` · SHA `{meta['dataset_sha256']}`",
             f"Code SHA: `{meta['code_sha256']}`",
             f"Models: `{meta['embedding']['model']}` / `{meta['generation']['model']}`",
             f"Answer strategy: `{meta.get('answer_strategy', 'legacy_v1')}`",
             f"Policy revision: `{meta.get('policy_revision', 1)}`",
             f"Model/source unchanged during run: **{not meta['models_changed'] and not meta['source_changed']}**", "",
             "## Mechanical metrics", "", "| Metric | Result |", "| --- | --- |"]
    for key, value in summary.items():
        if isinstance(value, dict) and "numerator" in value:
            lines.append(f"| {key} | {display_rate(value)} |")
    latency = summary["answer_latency_ms"]
    lines += ["", f"Latency answer-only: p50 `{latency['p50']}` ms · p95 `{latency['p95']}` ms · n={latency['samples']}.",
              "Includes rewrite when enabled; excludes PDF/index/setup. Serial local run, not load testing.",
              f"Forbidden canary output cases: **{summary['forbidden_output_cases']}** (a string check, not a security proof).", "",
              "## Abstention reasons", "", json.dumps(summary.get("abstention_reasons", {}), sort_keys=True), "",
              "## Semantic review", "", "**PENDING.** Faithfulness and semantic citation correctness are not automatically scored.",
              "Use review-template.json. A present quote or matching keyword does not prove relevance/entailment.", "",
              "## Cases", "", "| Case | Expected | Actual | Proxy | Failed checks |", "| --- | --- | --- | --- | --- |"]
    for row in report["cases"]:
        lines.append(f"| {row['id']} | {row['expected_status']} | {row['actual_status']} | {'PASS' if row['proxy_pass'] else 'FAIL'} | {', '.join(row['failed_checks']) or '—'} |")
    lines += ["", "## Limits", "", "- Dataset is authored, synthetic, ASCII-PDF ID/EN text, small and not blinded/representative.",
              "- Literal gold evidence and content aliases can produce false negatives/positives; inspect raw answers.",
              "- Errors count as failures, not successful abstentions. N/A means zero denominator, not 100%.",
              "- Holdout is excluded from candidate selection; it belongs to the same project and is not independent validation.",
              "- Fixed seeds/digests enable controlled reruns, not bit-identical inference across hardware/backends.",
              "- No paid judge, external API, automatic quality certification or automatic production config change.", ""]
    return "\n".join(lines)


def save_report(report, output):
    output = Path(output)
    # Refuse to clobber prior/user runs. Caller creates a fresh run directory.
    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    review = {"report_schema": 1, "dataset_sha256": report["metadata"]["dataset_sha256"],
              "code_sha256": report["metadata"]["code_sha256"], "reviewer": None, "reviewer_type": None,
              "rubric": {"relevant": "Does the answer address the actual question, including resolved follow-up intent?",
                         "supported": "Does each complete claim follow from its quote or an independently checked exact derivation of the cited quantity, with correct negation/units/entities?",
                         "complete": "Does the answer cover all requested facts without unsupported extras?"},
              "cases": [{"id": r["id"], "response_sha256": r["response_sha256"], "relevant": None,
                         "supported": None, "complete": None, "notes": ""} for r in report["cases"] if r["actual_status"] == "answered"]}
    (output / "review-template.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

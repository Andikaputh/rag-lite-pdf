"""Paired development-only comparison. Never changes production configuration."""
import argparse
import json
from pathlib import Path

from evals.report import display_rate


def compare_reports(baseline, candidate):
    left, right = baseline["metadata"], candidate["metadata"]
    if left["split"] != "dev" or right["split"] != "dev":
        raise ValueError("Candidate selection is dev-only; holdout cannot choose a threshold")
    for metadata in (left, right):
        if metadata["source_changed"] or metadata["models_changed"]:
            raise ValueError("Model/source changed during run")
    for key in ("dataset_sha256", "dataset_version", "code_sha256", "embedding", "generation", "chunking", "top_k", "seed", "protocol", "environment"):
        if left[key] != right[key]:
            raise ValueError(f"Incomparable runs: {key}")
    if [r["id"] for r in baseline["cases"]] != [r["id"] for r in candidate["cases"]]:
        raise ValueError("Case IDs/order differ")
    deltas = [{"id": a["id"], "baseline_pass": a["proxy_pass"], "candidate_pass": b["proxy_pass"],
               "baseline_status": a["actual_status"], "candidate_status": b["actual_status"]}
              for a, b in zip(baseline["cases"], candidate["cases"]) if a["proxy_pass"] != b["proxy_pass"] or a["actual_status"] != b["actual_status"]]
    strategies = (left.get("answer_strategy", "legacy_v1"), right.get("answer_strategy", "legacy_v1"))
    if any(s not in ("legacy_v1", "extractive_v2", "focused_v3") for s in strategies):
        raise ValueError("Unknown controlled answer strategy")
    if strategies[0] != strategies[1] and left["min_score"] != right["min_score"]:
        raise ValueError("Change one variable at a time: strategy OR threshold")
    return {"baseline_threshold": left["min_score"], "candidate_threshold": right["min_score"],
            "baseline_strategy": strategies[0], "candidate_strategy": strategies[1],
            "baseline_policy_revision": left.get("policy_revision", 1), "candidate_policy_revision": right.get("policy_revision", 1),
            "dataset_sha256": left["dataset_sha256"], "code_sha256": left["code_sha256"],
            "baseline_summary": baseline["summary"], "candidate_summary": candidate["summary"],
            "changed_cases": deltas, "production_config_changed": False,
            "decision": "Keep production baseline unchanged. Inspect paired results and complete semantic review before any adoption; a small proxy gain is not proof of quality."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    comparison = compare_reports(json.loads(args.baseline.read_text(encoding="utf-8")), json.loads(args.candidate.read_text(encoding="utf-8")))
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Controlled dev comparison", "", "> Mechanical proxies only. No automatic production changes or holdout selection.", "",
             f"Threshold: {comparison['baseline_threshold']} → {comparison['candidate_threshold']}", "",
             f"Strategy: `{comparison['baseline_strategy']}` → `{comparison['candidate_strategy']}`", "",
             "| Metric | Baseline | Candidate |", "| --- | --- | --- |"]
    for key, value in comparison["baseline_summary"].items():
        if isinstance(value, dict) and "numerator" in value:
            lines.append(f"| {key} | {display_rate(value)} | {display_rate(comparison['candidate_summary'][key])} |")
    lines += ["", comparison["decision"], "", "## Changed cases", ""]
    lines += [f"- `{r['id']}`: {r['baseline_status']} / pass={r['baseline_pass']} → {r['candidate_status']} / pass={r['candidate_pass']}" for r in comparison["changed_cases"]] or ["- None."]
    (args.out / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.out / "comparison.md")


if __name__ == "__main__":
    main()

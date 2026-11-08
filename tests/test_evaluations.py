import json
import tempfile
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from evals.compare import compare_reports
from evals.dataset import load_dataset
from evals.fixtures import build_pdf
from evals.metrics import score_case, summarize
from evals.report import save_report
from evals.review import summarize_review
from evals.run import run_evaluation
from tests.test_answering import SemanticFakeEmbedder, FakeGenerator, TEXT, QUOTE
from web.indexing import IndexService


class EvaluationMetricsTests(unittest.TestCase):
    def setUp(self):
        self.case = {"id": "unit", "language": "id", "tags": ["multi_page"], "expected_status": "answered",
                     "evidence": [{"page": 1, "quote": QUOTE}, {"page": 2, "quote": "Pengembalian dalam 14 hari."}],
                     "contains_any": [["24"], ["14"]]}
        self.retrieved = [{"page": 1, "chunk_id": 0, "text": TEXT}]
        self.pages = [{"text": TEXT}, {"text": "Pengembalian dalam 14 hari."}]
        self.response = {"status": "answered", "answer": "Garansi 24 bulan. [1]", "claims": [{"text": "Garansi 24 bulan.", "citation": 1}],
                         "sources": [{"number": 1, "page": 1, "chunk_id": 0, "quote": QUOTE}]}

    def test_valid_quote_does_not_imply_complete_or_faithful_answer(self):
        row = score_case(self.case, self.response, self.retrieved, self.pages)
        summary = summarize([row])
        self.assertEqual(summary["retrieval_recall_at_3"]["value"], .5)
        self.assertEqual(summary["quote_integrity"]["value"], 1.)
        self.assertFalse(row["proxy_pass"])
        self.assertIsNone(summary["faithfulness"]["value"])
        self.assertIsNone(summary["semantic_citation_correctness"]["value"])

    def test_no_quotes_is_na_not_perfect_citation_score(self):
        negative = {**self.case, "expected_status": "abstained", "evidence": [], "contains_any": []}
        row = score_case(negative, {"status": "abstained", "answer": "Tidak tahu", "claims": [], "sources": []}, [], self.pages)
        summary = summarize([row])
        self.assertIsNone(summary["quote_integrity"]["value"])
        self.assertIsNone(summary["retrieval_recall_at_3"]["value"])
        self.assertTrue(row["proxy_pass"])

    def test_error_is_failure_not_successful_abstention(self):
        negative = {**self.case, "expected_status": "abstained", "evidence": [], "contains_any": []}
        row = score_case(negative, {"status": "error"}, None, self.pages)
        summary = summarize([row])
        self.assertEqual(summary["abstention_recall"]["value"], 0.)
        self.assertEqual(summary["error_rate"]["value"], 1.)
        self.assertFalse(row["proxy_pass"])

    def test_quote_must_match_original_page_and_retrieved_chunk(self):
        response = deepcopy(self.response)
        response["sources"][0]["quote"] = "Invented evidence."
        row = score_case(self.case, response, self.retrieved, self.pages)
        self.assertFalse(row["quote_checks"][0]["valid"])
        response["sources"][0]["quote"] = QUOTE
        row = score_case(self.case, response, [], self.pages)
        self.assertFalse(row["quote_checks"][0]["valid"])

    def test_injection_canary_is_flagged_even_with_matching_content(self):
        case = {**self.case, "evidence": self.case["evidence"][:1], "contains_any": [], "forbidden": ["HACKED_GATE"]}
        response = {**self.response, "answer": "HACKED_GATE"}
        row = score_case(case, response, self.retrieved, self.pages)
        self.assertFalse(row["proxy_pass"])
        self.assertEqual(row["forbidden_hits"], ["HACKED_GATE"])

    def test_followup_flags_are_scored_not_ignored(self):
        case = {**self.case, "expected_used_history": True, "resolved_contains": ["garansi"]}
        row = score_case(case, {**self.response, "used_history": False, "resolved_question": "Q"}, self.retrieved, self.pages)
        self.assertFalse(row["checks"]["used_history"])
        self.assertFalse(row["checks"]["resolved_topic_proxy"])


class EvaluationDatasetTests(unittest.TestCase):
    def test_default_dataset_has_explicit_splits_and_grounded_evidence(self):
        dataset = load_dataset()
        self.assertEqual(len(dataset["cases"]), 22)
        self.assertEqual(sum(c["split"] == "dev" for c in dataset["cases"]), 14)
        self.assertEqual(sum(c["split"] == "holdout" for c in dataset["cases"]), 8)
        self.assertEqual({c["language"] for c in dataset["cases"]}, {"id", "en"})

    def test_generated_pdf_preserves_explicit_page_boundaries(self):
        pdf = build_pdf(["Page one synthetic fact.", "Page two synthetic fact."])
        reader = PdfReader(BytesIO(pdf), strict=True)
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("Page two", reader.pages[1].extract_text())
        self.assertNotIn("Page two", reader.pages[0].extract_text())

    def test_page_overflow_is_rejected_not_hidden_in_fixture(self):
        with self.assertRaises(ValueError):
            build_pdf(["line\n" * 60])

    def test_non_synthetic_and_bad_gold_are_rejected(self):
        dataset = load_dataset()
        Path(".tools").mkdir(exist_ok=True)  # gitignored; must exist in fresh clones/CI
        with tempfile.TemporaryDirectory(dir=".tools") as temporary:
            path = Path(temporary) / "bad.json"
            for mutate in (lambda d: d.update(synthetic=False),
                           lambda d: d["cases"][0]["evidence"][0].update(quote="not actually in PDF"),
                           lambda d: d["cases"][0].update(question=" ")):
                changed = deepcopy(dataset)
                mutate(changed)
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_dataset(path)


class EvaluationPipelineTests(unittest.TestCase):
    def setUp(self):
        Path(".tools").mkdir(exist_ok=True)  # gitignored; must exist in fresh clones/CI
        temporary = tempfile.TemporaryDirectory(dir=".tools")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = {"schema_version": 1, "version": "test-only", "synthetic": True,
                        "documents": [{"id": "test", "pages": [TEXT]}], "cases": [
            {"id": "positive", "document": "test", "split": "dev", "language": "id", "tags": ["fact"],
             "question": "Masa garansi?", "expected_status": "answered", "evidence": [{"page": 1, "quote": QUOTE}], "contains_any": [["24"]]},
            {"id": "negative", "document": "test", "split": "dev", "language": "id", "tags": ["absent"],
             "question": "Pertanyaan tidak relevan", "expected_status": "abstained", "evidence": [], "contains_any": []}]}
        self.path = self.root / "dataset.json"
        self.path.write_text(json.dumps(self.dataset), encoding="utf-8")

    def run_fake(self):
        return run_evaluation(dataset_path=self.path, indexer=IndexService(embedder=SemanticFakeEmbedder()), generator=FakeGenerator())

    def test_actual_pipeline_observer_and_reports_work_offline(self):
        report = self.run_fake()
        self.assertEqual(report["summary"]["scenario_proxy_pass"]["value"], 1.)
        self.assertTrue(report["cases"][0]["retrieval_attempted"])
        self.assertEqual(report["summary"]["quote_integrity"]["denominator"], 1)
        self.assertFalse(report["metadata"]["models_changed"])
        output = self.root / "run"
        save_report(report, output)
        self.assertIn("NOT faithfulness", (output / "report.md").read_text())
        labels = json.loads((output / "review-template.json").read_text())
        self.assertIsNone(labels["reviewer"])
        self.assertIsNone(labels["cases"][0]["supported"])
        with self.assertRaises(FileExistsError):
            save_report(report, output)

    def test_comparison_refuses_holdout_source_model_or_case_mismatch(self):
        baseline = self.run_fake()
        candidate = deepcopy(baseline)
        candidate["metadata"]["min_score"] = .55
        self.assertFalse(compare_reports(baseline, candidate)["production_config_changed"])
        for field, value in (("split", "holdout"), ("code_sha256", "wrong"), ("models_changed", True)):
            changed = deepcopy(candidate)
            changed["metadata"][field] = value
            with self.assertRaises(ValueError):
                compare_reports(baseline, changed)
        candidate["cases"].reverse()
        with self.assertRaises(ValueError):
            compare_reports(baseline, candidate)

    def test_semantic_review_requires_explicit_labels_and_matching_response(self):
        report = self.run_fake()
        output = self.root / "review-run"
        save_report(report, output)
        labels = json.loads((output / "review-template.json").read_text())
        with self.assertRaises(ValueError):
            summarize_review(report, labels)
        labels.update(reviewer="test reviewer", reviewer_type="agent")
        self.assertIsNone(summarize_review(report, labels)["ratings"]["supported"]["value"])
        labels["cases"][0]["supported"] = False
        self.assertEqual(summarize_review(report, labels)["ratings"]["supported"]["value"], 0.)
        labels["cases"][0]["response_sha256"] = "wrong"
        with self.assertRaises(ValueError):
            summarize_review(report, labels)

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

import tests.test_answering as fixtures
from evals.derivations import check_derivation
from web.answering import inspect_claims
from web.conversions import derive_duration, valid_derivation
from web.focus import focus_claims
from web.focused_selection import FocusedEvidenceSelector
from web.grounding import EvidenceDecision
from web.rewriting import preserve_question


def literal(text, source_id="C0"):
    return {"text": text, "quote": text, "source_id": source_id}


class ExactConversionTests(unittest.TestCase):
    def test_exact_month_year_and_fixed_day_week_ratios(self):
        cases = [("How many years is the warranty?", "The warranty lasts 36 months.", "36 months = 3 years."),
                 ("Berapa tahun masa garansi?", "Masa garansi adalah 18 bulan.", "18 bulan = 1.5 tahun."),
                 ("How many months is the warranty?", "The warranty lasts 1.5 years.", "1.5 years = 18 months."),
                 ("How many weeks are records stored?", "Records are stored for 14 days.", "14 days = 2 weeks."),
                 ("How many weeks is the duration?", "The duration is 1 day.", "1 day = 1/7 weeks.")]
        for question, quote, expected in cases:
            with self.subTest(expected=expected):
                result, error = derive_duration(question, [literal(quote)])
                self.assertIsNone(error)
                self.assertEqual(result[0]["text"], expected)
                self.assertTrue(valid_derivation(question, result[0]))

    def test_ranges_approximations_multiple_values_and_calendar_days_refused(self):
        for quote in ("The warranty lasts 12 to 24 months.", "The warranty lasts up to 24 months.",
                      "The warranty lasts about 24 months.", "Device warranty lasts 24 months and battery warranty 6 months.",
                      "The warranty lasts 1,000 months.", "The warranty is not 36 months.", "If approved, the warranty lasts 36 months."):
            with self.subTest(quote=quote):
                self.assertIsNotNone(derive_duration("How many years is the warranty?", [literal(quote)])[1])
        self.assertEqual(derive_duration("How many days is the warranty?", [literal("Warranty lasts 2 months.")])[1], "unsupported_calculation")

    def test_question_numbers_are_not_calculation_inputs(self):
        self.assertEqual(derive_duration("How many years are 999 months?", [literal("The warranty lasts 36 months.")])[1], "quantity_mismatch")

    def test_two_literal_facts_in_their_own_units_are_not_a_conversion(self):
        claims = [literal("Masa garansi adalah 18 bulan."), literal("Pengembalian harus diajukan dalam 14 hari.")]
        result, error = derive_duration("Berapa bulan garansi dan berapa hari batas pengembalian?", claims)
        self.assertIsNone(error)
        self.assertEqual(result, claims)

    def test_literal_days_question_is_not_forced_into_conversion(self):
        quote = "Employees may work remotely for up to three days each week for six months."
        result, error = derive_duration("How many days per week can employees work remotely?", [literal(quote)])
        self.assertIsNone(error)
        self.assertEqual(result[0]["text"], quote)

    def test_forged_math_quote_or_proof_never_bypasses_numeric_guard(self):
        question = "How many years is the warranty?"
        quote = "The warranty lasts 36 months."
        derived = derive_duration(question, [literal(quote)])[0][0]
        src = [{"source_id": "C0", "text": quote, "page": 1, "chunk_id": 0, "start": 0, "end": len(quote), "score": .9}]
        payload = {"abstain": False, "claims": [derived]}
        self.assertEqual(inspect_claims(payload, src, "doc.pdf")[1], "invalid_derivation")
        verified, error = inspect_claims(payload, src, "doc.pdf", allow_derivations=True, question=question)
        self.assertIsNone(error)
        self.assertTrue(check_derivation(verified["claims"][0], verified["sources"]))
        for mutation in ("value", "factor", "text"):
            bad = deepcopy(derived)
            if mutation == "value":
                bad["derivation"]["target_value"]["numerator"] = 4
            elif mutation == "factor":
                bad["derivation"]["factor"]["denominator"] = 10
            else:
                bad["text"] = "36 months = 4 years."
            self.assertFalse(valid_derivation(question, bad))

    def test_independent_math_check_rejects_false_input_and_display(self):
        question = "How many years is the warranty?"
        quote = "The warranty lasts 36 months."
        claim = derive_duration(question, [literal(quote)])[0][0]
        verified, _ = inspect_claims({"abstain": False, "claims": [claim]},
            [{"source_id": "C0", "text": quote, "page": 1, "chunk_id": 0, "start": 0, "end": len(quote), "score": .9}],
            "doc.pdf", allow_derivations=True, question=question)
        bad = deepcopy(verified["claims"][0])
        bad["derivation"]["calculation"] = "36 * 99 = 3"
        self.assertFalse(check_derivation(bad, verified["sources"]))
        wrong_source = [{**verified["sources"][0], "quote": "The warranty lasts 42 months."}]
        self.assertFalse(check_derivation(verified["claims"][0], wrong_source))


class FocusAndLanguageTests(unittest.TestCase):
    def test_unrelated_calibration_quote_dropped_but_retention_preserved(self):
        claims = [literal("Calibration is performed every 11 days."), literal("Readings are stored for 14 days.")]
        selected = focus_claims("For how many days are Nimbus readings stored?", claims)
        self.assertEqual(selected, claims[1:])

    def test_explicit_multi_fact_question_keeps_both_facts(self):
        claims = [literal("Calibration is performed every 11 days."), literal("Readings are stored for 14 days.")]
        self.assertEqual(focus_claims("How often is calibration performed and how long are readings stored?", claims), claims)

    def test_shared_warranty_word_does_not_keep_other_tier(self):
        claims = [literal("The standard warranty lasts 18 months."), literal("The extended warranty lasts 2 years.")]
        self.assertEqual(focus_claims("How many months is the extended warranty?", claims), claims[1:])

    def test_selection_refinement_prefers_result_and_label_matches(self):
        selector = FocusedEvidenceSelector()
        abstract = "The study examines the relationship between sleep duration and memory consolidation."
        result = "The study found that sleep improves memory consolidation in healthy adults."
        units = [{"id": "E0", "source_id": "C0", "text": abstract},
                 {"id": "E1", "source_id": "C0", "text": result}]
        refined = selector.refine_selection("What did the study find about sleep and memory?", [literal(abstract)], units)
        self.assertEqual(refined[0]["text"], result)

        units = [{"id": "E0", "source_id": "C0", "text": "Operating temperature range 0 to 45 C."},
                 {"id": "E1", "source_id": "C0", "text": "Weight 1.2 kg."}]
        refined = selector.refine_selection("What is the weight?", [literal("Operating temperature range 0 to 45 C.")], units)
        self.assertEqual(refined[0]["text"], "Weight 1.2 kg.")

    def test_opening_time_cannot_answer_founder_question(self):
        selector = FocusedEvidenceSelector()
        with patch.object(selector.opener, "open", side_effect=AssertionError("No irrelevant selection RPC")):
            decision = selector.generate("Who founded the original reading room?", [{"source_id": "C0", "text": "The room opens at 08:45 UTC."}])
        self.assertEqual(decision.reason, "missing_requested_fact")
        positive = selector.decision("Who founded the reading room?", [literal("The founder is Leila.")])
        self.assertIsNone(positive.reason)

    def test_question_preserved_exactly_no_model_rpc_or_language_switch(self):
        selector = FocusedEvidenceSelector()
        for question, previous in (("Can you repeat how long those records are stored?", "For how many days are borrowing records stored?"),
                                   ("Bisa ulangi berapa bulannya?", "Berapa masa garansi perangkat?"),
                                   ("Repeat its duration, please.", "How long is the device warranty?")):
            with patch.object(selector.opener, "open", side_effect=AssertionError("No rewrite RPC")):
                result = selector.rewrite(question, [previous])
            self.assertTrue(result["question"].startswith(question))
            self.assertIn(previous, result["question"])

    def test_standalone_and_ambiguous_answer_number_reference(self):
        self.assertEqual(preserve_question("What is the email?", ["What is the warranty?"])["question"], "What is the email?")
        self.assertTrue(preserve_question("Which one?", ["What are the policies?"])["needs_clarification"])


class DerivedGatewayTests(unittest.TestCase):
    setUp = fixtures.AnswerGatewayTests.setUp
    ask = fixtures.AnswerGatewayTests.ask

    def test_derived_answer_has_auditable_proof_and_cited_original_input(self):
        self.answerer.answer_strategy = "focused_v3"
        quote = fixtures.QUOTE
        question = "How many years is the device warranty?"
        claims, reason = derive_duration(question, [literal(quote)])
        self.assertIsNone(reason)
        with patch.object(self.generator, "generate", return_value=EvidenceDecision({"abstain": False, "claims": claims})):
            response = self.ask(question)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["answer_mode"], "derived")
        self.assertIn("2 years", data["answer"])
        self.assertEqual(data["sources"][0]["quote"], quote)
        self.assertEqual(data["claims"][0]["derivation"]["rule"], "exact_duration_ratio_v1")

    def test_forged_derivation_abstains_and_is_not_stored_as_verified_answer(self):
        self.answerer.answer_strategy = "focused_v3"
        claims = derive_duration("How many years is the device warranty?", [literal(fixtures.QUOTE)])[0]
        claims[0]["text"] = "24 months = 99 years."
        with patch.object(self.generator, "generate", return_value={"abstain": False, "claims": claims}):
            data = self.ask("How many years is the device warranty?").json()
        self.assertEqual(data["reason"], "invalid_derivation")
        self.assertEqual(data["claims"], [])


if __name__ == "__main__":
    unittest.main()

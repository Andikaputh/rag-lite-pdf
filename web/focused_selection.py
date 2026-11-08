"""Focused extractive evidence plus server-recomputed exact duration derivations."""
import re
from web.conversions import derive_duration
from web.evidence_selection import EvidenceSelector
from web.focus import focus_claims
from web.grounding import EvidenceDecision, extractive_rejection
from web.rewriting import preserve_question


class FocusedEvidenceSelector(EvidenceSelector):
    answer_strategy = "focused_v3"
    policy_revision = 4

    def attribution_pattern(self, question):
        if re.search(r"\b(founded|founder|pendiri|didirikan|mendirikan)\b", question, re.I):
            return r"\b(founded|founder|pendiri|didirikan|mendirikan|established by)\b"
        if re.search(r"\b(designed|designer|perancang|dirancang)\b", question, re.I):
            return r"\b(designed|designer|perancang|dirancang)\b"
        if re.search(r"\b(authored|author|written by|penulis|ditulis)\b", question, re.I):
            return r"\b(authored|author|written by|penulis|ditulis)\b"
        return None

    def generate(self, question, sources, *, timeout=90):
        pattern = self.attribution_pattern(question)
        if pattern and not any(re.search(pattern, s["text"], re.I) for s in sources):
            return EvidenceDecision({"abstain": True, "claims": []}, "missing_requested_fact")
        return super().generate(question, sources, timeout=timeout)

    def selection_prompt(self, prompt):
        return prompt + "\nSelect the MINIMUM evidence needed, not additional facts about other schedules or products. For a duration conversion, select the original stated duration even if its unit differs from the requested unit: the server, not you, performs conversion. Do not select another quantity merely because its unit matches the requested unit."

    def rewrite(self, question, previous_questions, *, timeout=30):
        return preserve_question(question, previous_questions)

    def decision(self, question, claims):
        selected = focus_claims(question, claims)
        pattern = self.attribution_pattern(question)
        if pattern and any(not re.search(pattern, c["quote"], re.I) for c in selected):
            return EvidenceDecision({"abstain": True, "claims": []}, "missing_requested_fact")
        reason = extractive_rejection(question, selected, allow_conversion=True)
        if not reason:
            selected, reason = derive_duration(question, selected)
        return EvidenceDecision({"abstain": True, "claims": []} if reason else {"abstain": False, "claims": selected}, reason)

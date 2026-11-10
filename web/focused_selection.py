"""Focused extractive evidence plus server-recomputed exact duration derivations."""
import re
from web.conversions import derive_duration
from web.evidence_selection import EvidenceSelector
from web.focus import concepts, focus_claims
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

    def refine_selection(self, question, claims, units):
        # A general "what did the study find/show" question should prefer a result
        # sentence over an abstract/aim sentence. Skip when the question asks about
        # a specific section such as the sample, method, or limitations.
        if re.search(r"\b(find|found|finds|show|shows|showed|report|reports|reported|demonstrate|demonstrates|demonstrated|result|results|menemukan|menunjukkan|hasil)\b", question, re.I) and not re.search(r"\b(limitation|method|sample|participant|procedure|data|table|figure|referen|bibliograph)\b", question, re.I):
            result_units = [u for u in units if re.search(r"\b(found|shows?|showed|reports?|reported|demonstrates?|demonstrated|results?|menemukan|menunjukkan|hasil)\b", u["text"], re.I)]
            if result_units:
                selected_results = [c for c in claims if re.search(r"\b(found|shows?|showed|reports?|reported|demonstrates?|demonstrated|results?|menemukan|menunjukkan|hasil)\b", c["quote"], re.I)]
                if selected_results:
                    claims = selected_results
                else:
                    wanted = concepts(question)
                    best = max(result_units, key=lambda u: len(wanted & concepts(u["text"])))
                    claims = [{"text": best["text"], "quote": best["text"], "source_id": best["source_id"]}]
        # Lexical safety net: when the model picked no unit that shares a content
        # word with the question, fall back to the best-matching unit. Cross-
        # language questions have no shared words, so they keep the model choice.
        wanted = concepts(question)
        if wanted:
            scores = [len(wanted & concepts(c["quote"])) for c in claims]
            if max(scores, default=0) == 0:
                best = max(units, key=lambda u: len(wanted & concepts(u["text"])))
                if len(wanted & concepts(best["text"])) >= 1:
                    claims = [{"text": best["text"], "quote": best["text"], "source_id": best["source_id"]}]
        return claims

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

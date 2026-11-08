"""Deterministic follow-up context: never translate or invent user question text."""
import re

from web.documents import DocumentError


def question_language(question):
    question = re.split(r"\s+\((?:Previous user question topic|Topik pertanyaan pengguna sebelumnya):", question, maxsplit=1)[0]
    if re.search(r"\b(berapa|bagaimana|apakah|kapan|tolong|ulangi|tahun|bulan|minggu|hari)\b", question, re.I):
        return "id"
    return "en"


def preserve_question(question, previous_questions):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1500:
        raise DocumentError("invalid_rewrite", "Write a complete question of 1 to 1,500 characters.", 422)
    original = question.strip()
    if re.fullmatch(r"(?:yang mana|yang kedua|which one|the second one|nomor dua|number two)[?.!\s]*", original, re.I):
        return {"question": "", "needs_clarification": True}
    reference = re.search(r"\b(itu|tadi|ulangi|ulang|tersebut|mereka|it|that|its|those|these|repeat|again)\b|nya\b", original, re.I)
    if not reference or not previous_questions:
        return {"question": original, "needs_clarification": False}
    topic = previous_questions[-1][:300].strip()
    label = "Topik pertanyaan pengguna sebelumnya" if question_language(original) == "id" else "Previous user question topic"
    resolved = f"{original} ({label}: {topic})"
    if len(resolved) > 1500 or len(resolved.encode("utf-8")) > 6000:
        raise DocumentError("rewrite_too_large", "The question and context are too long. Shorten the question or disable context.", 422)
    return {"question": resolved, "needs_clarification": False}

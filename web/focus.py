"""Conservative removal of clearly unrelated extra evidence, not a relevance proof."""
import re

from web.grounding import requested_facets, unit_facets

ALIASES = {
    "readings": "reading", "pembacaan": "reading", "records": "record", "catatan": "record",
    "stored": "retain", "stores": "retain", "storage": "retain", "retention": "retain",
    "retained": "retain", "disimpan": "retain", "tersimpan": "retain", "penyimpanan": "retain",
    "garansi": "warranty", "perangkat": "device", "baterai": "battery", "batteries": "battery",
    "pengembalian": "return", "returns": "return", "days": "day", "hari": "day",
    "alat": "tool", "tools": "tool", "dipinjam": "borrow", "meminjam": "borrow",
    "peserta": "participant", "pelanggan": "customer", "dukungan": "support",
}
STOP = set("a an the is are was were be been does do can could may how what which when where who why for of to at in on by from and or with about those these that this its it you your me my repeat again please many much long duration time setiap berapa apa apakah kapan bagaimana yang itu tersebut tadi nya bisa ulangi ulang dalam untuk pada dengan dari dan atau lama masa hari day days weeks week minggu years year tahun months month bulan hours hour jam minutes minute menit seconds second detik".split())


def concepts(text, ignore=()):
    return {ALIASES.get(token, token) for token in re.findall(r"[^\W\d_]+", text.casefold())
            if token not in STOP and token not in ignore and len(token) > 2}


def focus_claims(question, claims):
    if len(claims) < 2:
        return claims
    # Mid-question title-case entity names alone should not make an unrelated
    # sentence look focused; retain real topic nouns/verbs and required facets.
    ignore = {word.casefold() for word in re.findall(r"\b[A-Z][a-z]+\b", question)}
    ignore.update({"previous", "user", "question", "topic", "topik", "pertanyaan", "pengguna", "sebelumnya"})
    wanted = concepts(question, ignore)
    scores = [len(wanted & concepts(claim["quote"], ignore)) for claim in claims]
    if max(scores, default=0) < 1:
        return claims  # Avoid aggressive removal for unknown/cross-language topics.
    required = requested_facets(question)
    overlaps = [wanted & concepts(claim["quote"], ignore) for claim in claims]
    common = set.intersection(*overlaps) if overlaps else set()
    specific = [terms - common for terms in overlaps]
    has_specific = any(specific)
    kept = []
    for index, claim in enumerate(claims):
        other_facets = set().union(*(unit_facets(c["quote"]) for j, c in enumerate(claims) if j != index))
        needed = (required & unit_facets(claim["quote"])) - other_facets
        if (scores[index] and (not has_specific or specific[index])) or needed:
            kept.append(claim)
    return kept or claims

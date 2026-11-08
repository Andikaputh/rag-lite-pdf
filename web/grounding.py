"""Conservative extractive evidence policy, not a semantic entailment proof."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceDecision:
    payload: dict
    reason: str | None = None


def matches(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def is_override_request(question):
    return matches(r"^\s*(?:please\s+)?(?:ignore|disregard|override|abaikan|lupakan)\b.{0,160}\b(?:rules?|instructions?|system|sistem|aturan|dokumen|context|konteks)\b", question)


def requested_facets(question):
    facets = set()
    warranty = matches(r"\b(garansi|warranty|warranties)\b", question)
    battery = matches(r"\b(baterai|battery|batteries)\b", question)
    shipping = matches(r"\b(pengiriman|shipping|postage)\b", question)
    returns = matches(r"\b(pengembalian|returns?|refunds?)\b", question)
    support = matches(r"\b(layanan|dukungan|support)\b", question)
    if matches(r"\b(email|e-mail)\b", question):
        facets.add("email")
    if matches(r"\b(harga|price|retail)\b", question) and not shipping:
        facets.add("product_price")
    if shipping and matches(r"\b(biaya|costs?|charge|fee|price)\b", question):
        facets.add("shipping_cost")
    if returns and not shipping and matches(r"\b(hari|days?|batas|deadline|within|lama|long)\b", question):
        facets.add("return_deadline")
    if warranty and not matches(r"\b(kerusakan|damage)\b", question):
        facets.add("battery_warranty" if battery else "device_warranty")
    if support and not facets.intersection({"email", "product_price", "shipping_cost"}):
        facets.add("support_hours" if matches(r"\b(jam|pukul|hours?|time)\b", question) else "support_days")
    if matches(r"\b(kerusakan|damage)\b", question):
        facets.add("damage_coverage")
        for name, pattern in (("water", r"\b(air|water)\b"), ("fire", r"\b(kebakaran|api|fire)\b"), ("impact", r"\b(benturan|impact)\b")):
            if matches(pattern, question):
                facets.add(f"damage_{name}")
    return facets


def unit_facets(text):
    facets = set()
    duration = matches(r"\b(bulan|tahun|months?|years?)\b", text)
    battery = matches(r"\b(baterai|battery|batteries)\b", text)
    if duration and matches(r"\b(garansi|warranty|warranties)\b", text):
        facets.add("battery_warranty" if battery else "device_warranty")
    if matches(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text):
        facets.add("email")
    if matches(r"\b(harga|price|retail)\b", text) and not matches(r"\b(pengiriman|shipping|postage)\b", text) and matches(r"\d|\b(free|gratis)\b", text):
        facets.add("product_price")
    if matches(r"\b(pengiriman|shipping|postage)\b", text) and matches(r"\b(biaya|costs?|charge|fee|free|gratis)\b", text):
        facets.add("shipping_cost")
    if matches(r"\b(pengembalian|returns?|refunds?)\b", text) and matches(r"\b(hari|days?)\b", text):
        facets.add("return_deadline")
    if matches(r"\b(layanan|dukungan|support)\b", text):
        if matches(r"\b(senin|selasa|rabu|kamis|jumat|sabtu|minggu|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text):
            facets.add("support_days")
        if matches(r"\b(jam|pukul|hours?|\d{1,2}[:.]\d{2})\b", text):
            facets.add("support_hours")
    if matches(r"\b(kerusakan|damage)\b", text) and matches(r"\b(ditanggung|covered|coverage|excluded|dikecualikan)\b", text):
        facets.add("damage_coverage")
        for name, pattern in (("water", r"\b(air|water)\b"), ("fire", r"\b(kebakaran|api|fire)\b"), ("impact", r"\b(benturan|impact)\b")):
            if matches(pattern, text):
                facets.add(f"damage_{name}")
    return facets


def is_fact_unit(text):
    if matches(r"\b(abaikan|ignore|bocorkan|reveal)\b.*\b(aturan|rules?|instructions?|prompt|system|sistem)\b", text) or matches(r"\b(jawab|reply|respond)\b.*\b(hanya|only|tanpa kutipan|without citations?)\b", text):
        return False
    # Avoid presenting document titles as evidence of an unstated fact. This is
    # intentionally conservative and can miss tables/fragments/long sentences.
    return matches(r"\b(is|are|lasts?|begins?|starts?|ends?|opens?|closes?|expires?|contains?|requires?|retains?|stores?|permits?|prohibits?|must|may|costs?|available|covered|not|adalah|berlaku|mendapat|tersedia|harus|ditanggung|tidak|biaya)\b|[\w.+-]+@[\w.-]+|\d+\s*(bulan|months?|tahun|years?|hari|days?)\b", text)


def evidence_units(question, sources):
    required = requested_facets(question)
    units, seen = [], set()
    for source in sources:
        for match in re.finditer(r".+?(?:[.!?](?=\s|$)|$)", source["text"], re.DOTALL):
            text = match.group().strip()
            identity = (source["source_id"], text)
            if identity in seen or not 12 <= len(text) <= 400 or not is_fact_unit(text):
                continue
            seen.add(identity)
            if required and not required.intersection(unit_facets(text)):
                continue
            units.append({"id": f"E{len(units)}", "source_id": source["source_id"], "text": text})
            if len(units) >= 24:
                return units
    return units


def extractive_rejection(question, claims, *, allow_conversion=False):
    if is_override_request(question):
        return "instruction_override_request"
    required = requested_facets(question)
    covered = set()
    for claim in claims:
        quote = claim["quote"]
        if claim["text"] != quote or not is_fact_unit(quote):
            return "unsupported_claim"
        if matches(r"\b(tidak (disebutkan|diberitahukan|dicantumkan|tersedia)|not (specified|stated|available|provided))\b", quote):
            return "explicit_unavailable_fact"
        covered.update(unit_facets(quote))
        if not allow_conversion and matches(r"\b(years?|tahun)\b", question) and matches(r"\b(months?|bulan)\b", quote) and not matches(r"\b(years?|tahun)\b", quote):
            return "unsupported_calculation"
    if not required.issubset(covered):
        return "missing_requested_fact"
    return None

"""Bounded exact duration conversion, derived only from one cited source quantity."""
import json
import re
from decimal import Decimal
from fractions import Fraction

from web.rewriting import question_language

UNIT_PATTERN = r"months?|bulan|years?|tahun|days?|hari|weeks?|minggu"
UNITS = {"month": "month", "months": "month", "bulan": "month", "year": "year", "years": "year", "tahun": "year",
         "day": "day", "days": "day", "hari": "day", "week": "week", "weeks": "week", "minggu": "week"}
RATIOS = {("month", "year"): Fraction(1, 12), ("year", "month"): Fraction(12),
          ("day", "week"): Fraction(1, 7), ("week", "day"): Fraction(7)}
LABELS = {"id": {"month": "bulan", "year": "tahun", "day": "hari", "week": "minggu"},
          "en": {"month": "months", "year": "years", "day": "days", "week": "weeks"}}


def target_unit(question):
    for pattern in (rf"\b(?:how many|berapa)\s+({UNIT_PATTERN})\b", rf"\b(?:into|in|to|dalam|ke|jadi|menjadi)\s+({UNIT_PATTERN})\b"):
        match = re.search(pattern, question, re.I)
        if match:
            return UNITS[match.group(1).casefold()]
    return None


def requested_units(question):
    result = set()
    for pattern in (rf"\b(?:how many|berapa)\s+({UNIT_PATTERN})\b", rf"\b(?:into|in|to|dalam|ke|jadi|menjadi)\s+({UNIT_PATTERN})\b"):
        result.update(UNITS[m.group(1).casefold()] for m in re.finditer(pattern, question, re.I))
    return result


def quantities(text):
    pattern = rf"(?<![\w.,:+\-–—])(\d{{1,6}}(?:[.,]\d{{1,2}})?)\s+({UNIT_PATTERN})\b"
    return [(Fraction(Decimal(m.group(1).replace(",", "."))), UNITS[m.group(2).casefold()]) for m in re.finditer(pattern, text, re.I)]


def display(value):
    denominator = value.denominator
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    result = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def rational(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def unit_label(language, unit, value):
    return unit if language == "en" and value == 1 else LABELS[language][unit]


def derive_duration(question, claims):
    target = target_unit(question)
    mentioned = {UNITS[m.group().casefold()] for m in re.finditer(rf"\b(?:{UNIT_PATTERN})\b", question, re.I)}
    if not target:
        if len(mentioned) > 1 or re.search(r"\b(convert|konversi|hitung|ubah)\b", question, re.I):
            return None, "unsupported_calculation"
        return claims, None
    source_quantities = [q for claim in claims for q in quantities(claim["quote"])]
    targets = requested_units(question)
    if len(claims) > 1 and len(targets) > 1 and source_quantities and all(unit in targets for _, unit in source_quantities) and not re.search(r"\b(convert|konversi|ubah)\b", question, re.I):
        return claims, None  # Separate literal facts requested in their original units.
    if not source_quantities:
        quoted_units = {UNITS[m.group().casefold()] for claim in claims for m in re.finditer(rf"\b(?:{UNIT_PATTERN})\b", claim["quote"], re.I)}
        return (None, "ambiguous_conversion") if quoted_units - {target} else (claims, None)
    if all(unit == target for _, unit in source_quantities):
        return claims, None
    if len(claims) != 1 or len(source_quantities) != 1:
        return None, "ambiguous_conversion"
    value, origin = source_quantities[0]
    quote = claims[0]["quote"]
    if re.search(r"\b(about|approximately|around|between|up to|at least|at most|more than|less than|sekitar|antara|hingga|maksimal|minimal|lebih|kurang|sampai|not|no|never|tidak|bukan|without|if|unless|jika|apabila|kecuali)\b|\d\s*(?:[-–—]|to|or|atau)\s*\d", quote, re.I):
        return None, "ambiguous_conversion"
    if value <= 0 or (origin, target) not in RATIOS:
        return None, "unsupported_calculation"
    explicit_inputs = [(number, unit) for number, unit in quantities(question) if unit == origin]
    if explicit_inputs and any(number != value for number, _ in explicit_inputs):
        return None, "quantity_mismatch"
    factor = RATIOS[(origin, target)]
    result = value * factor
    language = question_language(question)
    text = f"{display(value)} {unit_label(language, origin, value)} = {display(result)} {unit_label(language, target, result)}."
    proof = {"rule": "exact_duration_ratio_v1", "source_value": rational(value), "source_unit": origin,
             "target_value": rational(result), "target_unit": target, "factor": rational(factor),
             "calculation": f"{display(value)} * {display(factor)} = {display(result)}"}
    return [{**claims[0], "text": text, "derivation": proof}], None


def valid_derivation(question, claim):
    if not isinstance(claim.get("derivation"), dict):
        return False
    original = {"text": claim["quote"], "quote": claim["quote"], "source_id": claim["source_id"]}
    rebuilt, error = derive_duration(question, [original])
    if error or not rebuilt or "derivation" not in rebuilt[0]:
        return False
    return claim["text"] == rebuilt[0]["text"] and json.dumps(claim["derivation"], sort_keys=True) == json.dumps(rebuilt[0]["derivation"], sort_keys=True)

"""Independent mechanical check of declared duration arithmetic, not model judging."""
import re
from fractions import Fraction

UNITS = {"month": "month", "months": "month", "bulan": "month", "year": "year", "years": "year", "tahun": "year",
         "day": "day", "days": "day", "hari": "day", "week": "week", "weeks": "week", "minggu": "week"}
EXPECTED = {("month", "year"): Fraction(1, 12), ("year", "month"): Fraction(12),
            ("day", "week"): Fraction(1, 7), ("week", "day"): Fraction(7)}


def number(value):
    if set(value) != {"numerator", "denominator"} or any(type(v) is not int for v in value.values()):
        raise ValueError("Invalid rational")
    return Fraction(value["numerator"], value["denominator"])


def check_derivation(claim, citations):
    try:
        proof = claim["derivation"]
        if proof["rule"] != "exact_duration_ratio_v1":
            return False
        original, result, factor = (number(proof[k]) for k in ("source_value", "target_value", "factor"))
        pair = (proof["source_unit"], proof["target_unit"])
        if EXPECTED.get(pair) != factor or original * factor != result:
            return False
        calculation = re.fullmatch(r"([\d./]+)\s*\*\s*([\d./]+)\s*=\s*([\d./]+)", proof.get("calculation", ""))
        if not calculation or (Fraction(calculation[1]), Fraction(calculation[2]), Fraction(calculation[3])) != (original, factor, result):
            return False
        cited = next(c for c in citations if c["number"] == claim["citation"])
        pattern = r"(?<![\w.,:+\-–—])(\d+(?:[.,]\d{1,2})?)\s+(months?|bulan|years?|tahun|days?|hari|weeks?|minggu)\b"
        if not any(Fraction(v.replace(",", ".")) == original and UNITS[u.casefold()] == pair[0]
                   for v, u in re.findall(pattern, cited["quote"], re.I)):
            return False
        expression = re.fullmatch(r"\s*([\d./]+)\s+(\w+)\s*=\s*([\d./]+)\s+(\w+)\.\s*", claim["text"])
        return bool(expression and Fraction(expression[1]) == original and Fraction(expression[3]) == result
                    and UNITS[expression[2].casefold()] == pair[0] and UNITS[expression[4].casefold()] == pair[1])
    except (ValueError, KeyError, TypeError, ZeroDivisionError, StopIteration):
        return False

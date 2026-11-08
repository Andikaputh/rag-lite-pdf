"""Operator-owned policy switch; never configurable from an HTTP request."""
import json
from pathlib import Path

from web.evidence_selection import EvidenceSelector
from web.generation import OllamaGenerator
from web.focused_selection import FocusedEvidenceSelector


def configured_strategy():
    config = json.loads((Path(__file__).resolve().parent / "answer-policy.json").read_text(encoding="utf-8"))
    strategy = config.get("strategy")
    if set(config) != {"strategy"} or strategy not in ("legacy_v1", "extractive_v2", "focused_v3"):
        raise ValueError("Invalid operator answer policy")
    return strategy


def generator_for(strategy):
    if strategy == "legacy_v1":
        return OllamaGenerator()
    if strategy == "extractive_v2":
        return EvidenceSelector()
    if strategy == "focused_v3":
        return FocusedEvidenceSelector()
    raise ValueError("Unknown answer strategy")

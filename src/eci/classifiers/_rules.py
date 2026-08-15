"""Shared keyword/regex rule-matching engine used by every classifier in this package.

All classifiers here are **text heuristics** over the ad's copy (primary_text/headline/
description), not semantic/ML models and not visual analysis. Every result carries an
explicit `confidence` in [0, 1] so downstream reports never present a guess as fact
(section 3: HECHO / INFERENCIA / HIPOTESIS).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

RuleSet = dict[str, list[re.Pattern]]

_N_TILDE = "ñ"  # ñ
_N_TILDE_UPPER = "Ñ"  # Ñ
_PLACEHOLDER_LOWER = "\x00"
_PLACEHOLDER_UPPER = "\x01"


def strip_accents(value: str) -> str:
    """Removes diacritics (a-with-acute -> a, e-with-acute -> e, ...) so matching is
    accent-insensitive. Spanish ad copy on social media very often drops accents
    ("despues" instead of "después"), so every classifier normalizes both the rule
    patterns and the input text through this function before matching, instead of
    hand-duplicating every pattern with/without accents. The letter ñ/Ñ is protected
    from NFKD decomposition (which would otherwise turn it into a bare "n") via a
    placeholder swap, since ñ is a distinct letter in Spanish, not an accented vowel.
    """
    protected = value.replace(_N_TILDE, _PLACEHOLDER_LOWER).replace(_N_TILDE_UPPER, _PLACEHOLDER_UPPER)
    decomposed = unicodedata.normalize("NFKD", protected)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.replace(_PLACEHOLDER_LOWER, _N_TILDE).replace(_PLACEHOLDER_UPPER, _N_TILDE_UPPER)


def compile_rules(raw_rules: dict[str, list[str]]) -> RuleSet:
    return {
        label: [re.compile(strip_accents(pattern), re.IGNORECASE) for pattern in patterns]
        for label, patterns in raw_rules.items()
    }


@dataclass
class ClassificationResult:
    label: str | None
    confidence: float  # 0..1
    matched_patterns: int
    scores: dict[str, int]


def classify_by_rules(text: str | None, rules: RuleSet, *, default_label: str | None = None) -> ClassificationResult:
    """Scores every label by how many of its patterns match, returns the top one.
    Confidence = matches_for_winner / (matches_for_winner + 2), so a single hit gives
    ~0.33 confidence and it approaches 1.0 only with strong, repeated textual evidence —
    deliberately conservative given this is a text heuristic, not semantic understanding.
    """
    if not text:
        return ClassificationResult(default_label, 0.0, 0, {})

    normalized_text = strip_accents(text)
    scores: dict[str, int] = {}
    for label, patterns in rules.items():
        count = sum(1 for p in patterns if p.search(normalized_text))
        if count:
            scores[label] = count

    if not scores:
        return ClassificationResult(default_label, 0.0, 0, scores)

    best_label = max(scores, key=lambda label: scores[label])
    best_count = scores[best_label]
    confidence = round(best_count / (best_count + 2), 2)
    return ClassificationResult(best_label, confidence, best_count, scores)

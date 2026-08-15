"""Discovery engine — section 7: keywords -> ads -> pages -> products -> new keywords.

Pure text-processing (no network I/O), so it's fully unit-testable. The pipeline
orchestrator calls `expand_keywords` after each collection round, feeding it the ads
just collected, and merges the result into the `keywords` table (generation N+1).
"""

from __future__ import annotations

import re
from collections import Counter

from eci.models.schemas import NormalizedAd

_STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "un", "una", "unos", "unas", "y", "o", "para",
    "con", "por", "en", "que", "se", "su", "sus", "tu", "tus", "es", "son", "mas", "más",
    "ya", "no", "si", "sí", "modelo", "store", "producto", "productos", "comprar", "ahora",
    "the", "for", "and", "with", "buy", "now", "shop",
}

_TOKEN_RE = re.compile(r"[a-záéíóúñü]{3,}", re.IGNORECASE)


def _candidate_ngrams(text: str, *, n_min: int = 1, n_max: int = 2) -> list[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]
    grams: list[str] = []
    for n in range(n_min, n_max + 1):
        for i in range(len(tokens) - n + 1):
            grams.append(" ".join(tokens[i : i + n]))
    return grams


def expand_keywords(
    ads: list[NormalizedAd],
    *,
    existing_keywords: set[str],
    max_new_keywords: int = 15,
    min_frequency: int = 2,
) -> list[str]:
    """Mines product names / headlines from a batch of ads to propose new search
    keywords not already covered. Frequency-ranked, deduplicated against what we
    already search for, capped at `max_new_keywords` to keep discovery bounded."""
    counter: Counter[str] = Counter()
    for ad in ads:
        for field_value in (ad.product, ad.headline, ad.primary_text):
            if not field_value:
                continue
            for gram in _candidate_ngrams(field_value):
                counter[gram] += 1

    existing_lower = {k.lower() for k in existing_keywords}
    candidates = [
        (term, count)
        for term, count in counter.most_common()
        if count >= min_frequency and term not in existing_lower and len(term) >= 4
    ]
    return [term for term, _ in candidates[:max_new_keywords]]


def _seed_matches(seed: str, text_lower: str) -> bool:
    term = seed.replace("_", " ")
    if term in text_lower:
        return True
    # A real gap found via product_viability.py (2026-08-14): niches.yaml stores seeds
    # plural ("chaquetas"), but a user describing a product to sell writes singular
    # ("chaqueta rompevientos unisex") — a plain substring check never matches either
    # direction, so tolerate the simple Spanish singular/plural mismatch.
    if term.endswith("s") and term[:-1] in text_lower:
        return True
    if not term.endswith("s") and f"{term}s" in text_lower:
        return True
    return False


def classify_subniche(text: str, subniche_seeds: dict[str, list[str]]) -> tuple[str | None, float]:
    """Assigns the best-matching subniche by seed-keyword overlap. Returns
    (subniche_or_None, classification_confidence in [0,1]). Confidence is a simple
    normalized overlap score — declared as a heuristic, not a semantic classifier."""
    if not text:
        return None, 0.0
    text_lower = text.lower()
    best_subniche, best_score = None, 0
    for subniche, seeds in subniche_seeds.items():
        score = sum(1 for seed in seeds if _seed_matches(seed, text_lower))
        if score > best_score:
            best_subniche, best_score = subniche, score
    if best_subniche is None:
        return None, 0.0
    confidence = min(1.0, best_score / 3)  # 3+ matching seed terms => full confidence
    return best_subniche, round(confidence, 2)

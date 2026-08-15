"""Format classifier — section 11: VIDEO / IMAGE / CAROUSEL / UNKNOWN.

v1 trusts the source's own `format_hint` when available (MockSource always provides one;
a future creative-download step could too). When absent (e.g. Meta Graph API doesn't
expose format directly, and the web scraper doesn't always either), falls back to a
low-confidence text heuristic — and otherwise honestly reports UNKNOWN rather than
guessing "image" by default.
"""

from __future__ import annotations

from eci.classifiers._rules import ClassificationResult, classify_by_rules, compile_rules
from eci.models.schemas import AdFormat

_TEXT_HINT_RULES = compile_rules(
    {
        "carousel": [r"\bcarrusel\b", r"\bcarousel\b", r"desliza para ver más", r"swipe to see"],
        "video": [r"\bvideo\b", r"mira el video", r"watch the video", r"reproducir"],
        "image": [r"\bfoto\b", r"\bimagen\b", r"\bimage\b"],
    }
)

_VALID_HINTS = {"video", "image", "carousel"}


def classify_format(format_hint: str | None, text: str | None = None) -> tuple[AdFormat, float]:
    if format_hint and format_hint.lower() in _VALID_HINTS:
        return AdFormat(format_hint.lower()), 1.0

    result: ClassificationResult = classify_by_rules(text, _TEXT_HINT_RULES)
    if result.label:
        return AdFormat(result.label), result.confidence
    return AdFormat.UNKNOWN, 0.0


def format_distribution(formats: list[AdFormat]) -> dict[str, float]:
    """Section 11 percentages: {video: %, image: %, carousel: %, unknown: %}."""
    total = len(formats)
    if total == 0:
        return {"video": 0.0, "image": 0.0, "carousel": 0.0, "unknown": 0.0}
    counts = {"video": 0, "image": 0, "carousel": 0, "unknown": 0}
    for fmt in formats:
        counts[fmt.value] += 1
    return {k: round(v / total * 100, 1) for k, v in counts.items()}

"""Boolean creative-style flags used across video/image/carousel analysis (sections 12-14):
ugc_detected, testimonial_detected, demonstration_detected, problem_solution_detected,
comparison_detected. Text heuristics, each independently detected (an ad can be UGC AND
a testimonial AND a demonstration at once, unlike hook/angle/offer which pick one label).
"""

from __future__ import annotations

import re

_PATTERNS = {
    "ugc_detected": re.compile(
        r"\bugc\b|contenido de usuario|cliente real|así lo cuenta|mi experiencia con", re.IGNORECASE
    ),
    "testimonial_detected": re.compile(
        r"testimonio|reseña|opinión de client|lo que dicen nuestros client", re.IGNORECASE
    ),
    "demonstration_detected": re.compile(
        r"mira cómo funciona|demostración|así se usa|tutorial|paso a paso", re.IGNORECASE
    ),
    "problem_solution_detected": re.compile(
        r"el problema es|la solución|acaba con|dile adiós a", re.IGNORECASE
    ),
    "comparison_detected": re.compile(
        r"a diferencia de|comparado con|versus|vs\.?\s|mejor que", re.IGNORECASE
    ),
}


def detect_style_flags(text: str | None) -> dict[str, bool | None]:
    """Returns each flag as True/False when text is available, or None (unknown) when
    there's no text to analyze at all — never silently defaults missing text to False."""
    if not text:
        return {name: None for name in _PATTERNS}
    return {name: bool(pattern.search(text)) for name, pattern in _PATTERNS.items()}

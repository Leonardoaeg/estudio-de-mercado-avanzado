"""Hook classifier — section 12 (hook types) applied to ad copy text, since v1 does not
do frame-level video analysis (see IMPLEMENTATION_PLAN.md). `extract_hook_text` takes the
literal opening of the copy as a proxy for "what a viewer sees/reads in the first
seconds" — an INFERENCIA, not a HECHO about the actual video's first 1-3 seconds.
"""

from __future__ import annotations

from eci.classifiers._rules import compile_rules, classify_by_rules

HOOK_TYPE_RULES = compile_rules(
    {
        "question": [r"\?\s*$", r"^¿", r"\bsabías que\b", r"\bte ha pasado\b"],
        "problem": [r"\bsigues sufriendo\b", r"\bcansad[ao] de\b", r"\bel problema\b", r"\bya no aguantas\b"],
        "curiosity": [r"no vas a creer", r"nadie te dijo", r"el secreto", r"esto cambia todo"],
        "offer": [r"oferta", r"descuento", r"\d+%\s*off", r"solo hoy", r"por tiempo limitado"],
        "demonstration": [r"mira cómo", r"mira lo que pasó", r"demostración", r"así se usa"],
        "authority": [r"recomendado por", r"expertos aseguran", r"estudios demuestran", r"médicos"],
        "social_proof": [r"miles de client", r"reseñas", r"testimonios", r"todo el mundo lo usa"],
        "comparison": [r"a diferencia de", r"comparado con", r"mejor que"],
        "transformation": [r"antes y después", r"antes/después", r"transformación", r"antes vs"],
        "objection": [r"sé que estás pensando", r"tal vez no confías", r"no es una estafa"],
        "storytelling": [r"cuando probé", r"mi historia con", r"así fue como"],
    }
)


def classify_hook(text: str | None) -> tuple[str | None, float]:
    result = classify_by_rules(text, HOOK_TYPE_RULES)
    return result.label, result.confidence


def extract_hook_text(text: str | None, *, max_words: int = 18) -> str:
    """First `max_words` words of the copy, used as the literal `hook` field. Marked
    `not_available` when there is no copy at all."""
    if not text or not text.strip():
        return "not_available"
    words = text.strip().split()
    snippet = " ".join(words[:max_words])
    return snippet + ("…" if len(words) > max_words else "")

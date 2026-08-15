"""ClaimsRiskAnalyzer — section 33. Flags sensitive health/supplement claims so the
report can separate "Creative Strategy" from "Claims / Policy Risk", and explicitly
never recommends copying a risky claim just because competitors use it.
"""

from __future__ import annotations

import re

from eci.classifiers._rules import strip_accents

_RAW_RISK_PATTERNS: dict[str, str] = {
    "cura_enfermedad": r"\bcura\b.{0,20}(enfermedad|cáncer|diabetes|artritis)",
    "trata_enfermedad": r"\btrata\b.{0,20}(enfermedad|dolencia|condición)",
    "elimina_definitivo": r"\belimina\b.{0,20}(por completo|para siempre|de raíz)",
    "previene_enfermedad": r"previene (el cáncer|enfermedades|la diabetes)",
    "resultados_garantizados": r"resultados garantizados|garantiz(a|amos) resultados",
    "perdida_peso_garantizada": r"pierde \d+\s?(kg|kilos|libras) en|adelgaza garantizado|baja de peso garantizado",
    "afirmacion_medica_generica": r"aprobado por médicos|clínicamente probado|recomendado por doctores",
}
# Accent-insensitive, same rationale as classifiers/_rules.py: Spanish ad copy on social
# media frequently drops accents ("clinicamente probado" instead of "clínicamente probado").
_RISK_PATTERNS: dict[str, re.Pattern] = {
    name: re.compile(strip_accents(pattern), re.IGNORECASE) for name, pattern in _RAW_RISK_PATTERNS.items()
}

# Niches where claims risk actually matters (section 33 scopes this to Salud/Suplementos,
# but the analyzer itself stays generic — callers decide when to surface it in reports).
CLAIMS_SENSITIVE_NICHES = {"SALUD", "SUPLEMENTOS"}


def analyze_claims_risk(text: str | None) -> list[str]:
    """Returns the list of risk-flag names matched (empty list = no risky claim language
    detected in the text heuristics — NOT a guarantee of full policy compliance)."""
    if not text:
        return []
    normalized = strip_accents(text)
    return [name for name, pattern in _RISK_PATTERNS.items() if pattern.search(normalized)]


def is_claims_sensitive_niche(niche: str) -> bool:
    return niche.upper() in CLAIMS_SENSITIVE_NICHES

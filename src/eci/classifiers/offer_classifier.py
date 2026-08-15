"""Offer classifier — section 16."""

from __future__ import annotations

import re

from eci.classifiers._rules import compile_rules, classify_by_rules

OFFER_RULES = compile_rules(
    {
        "percentage_discount": [r"\d{1,2}\s?%\s*(off|de descuento|dcto)"],
        "fixed_discount": [r"descuento de \$?\d+", r"\$\d+\s*de descuento"],
        "2x1": [r"\b2\s*x\s*1\b"],
        "3x2": [r"\b3\s*x\s*2\b"],
        "bundle": [r"\bcombo\b", r"\bpack\b", r"\bkit\b", r"\bbundle\b"],
        "gift": [r"\bregalo\b", r"gratis con tu compra"],
        "free_shipping": [r"envío gratis", r"free shipping"],
        "cash_on_delivery": [r"pago contra entrega", r"cash on delivery"],
        "limited_offer": [r"por tiempo limitado", r"solo hoy", r"últimas horas", r"oferta flash"],
        "guarantee": [r"garantía", r"devolución de dinero", r"money back"],
        "subscription": [r"suscripción", r"membresía mensual"],
        "installments": [r"cuotas sin interés", r"paga en cuotas", r"a meses sin intereses"],
    }
)

_PERCENT_RE = re.compile(r"(\d{1,2})\s?%\s*(off|de descuento|dcto)", re.IGNORECASE)


def classify_offer(text: str | None) -> tuple[str, float]:
    result = classify_by_rules(text, OFFER_RULES, default_label="no_offer")
    label = result.label or "no_offer"
    confidence = result.confidence if result.label else 0.5  # absence of offer language is itself informative
    return label, confidence


def extract_discount_percentage(text: str | None) -> float | None:
    if not text:
        return None
    match = _PERCENT_RE.search(text)
    return float(match.group(1)) if match else None

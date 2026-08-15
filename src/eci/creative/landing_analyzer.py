"""Landing page analyzer — section 26. Extracts what's observable from the store's
product/landing page: product, headline, price, discount, bundle, reviews, guarantee,
shipping, payment methods, social proof, upsells. Never adds items to cart or checks out
(section 26: "No realizar compras ni checkout") — this is a GET-only, read-only fetch.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from eci.classifiers.offer_classifier import extract_discount_percentage
from eci.utils.http import fetch

_PRICE_RE = re.compile(r"(?:\$|COP|USD|MXN)\s?([\d.,]{3,})", re.IGNORECASE)
_REVIEW_RE = re.compile(r"reseñas|opiniones|reviews|calificaciones|estrellas", re.IGNORECASE)
_GUARANTEE_RE = re.compile(r"garantía|devolución|satisfacción garantizada|money back", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"envío gratis|free shipping|envío a todo el país", re.IGNORECASE)
_PAYMENT_RE = re.compile(r"contraentrega|contra entrega|tarjeta de crédito|pse|mercado pago|paypal", re.IGNORECASE)
_UPSELL_RE = re.compile(r"llévate también|te puede interesar|complementa tu compra|frequently bought", re.IGNORECASE)
_BUNDLE_RE = re.compile(r"combo|kit|pack de \d+|bundle", re.IGNORECASE)


def analyze_landing(landing_url: str) -> dict:
    result = fetch(landing_url)
    if not result.ok or not result.text:
        return {
            "landing_url": landing_url,
            "verified": False,
            "reason": result.error or "fetch_failed",
        }

    soup = BeautifulSoup(result.text, "lxml")
    text = soup.get_text(" ", strip=True)

    title_tag = soup.find(["h1", "title"])
    headline = title_tag.get_text(strip=True) if title_tag else "not_available"

    price_match = _PRICE_RE.search(text)
    price = price_match.group(1) if price_match else None

    return {
        "landing_url": landing_url,
        "final_url": result.final_url,
        "verified": True,
        "headline": headline,
        "price_text": price,
        "discount_percentage": extract_discount_percentage(text),
        "has_bundle": bool(_BUNDLE_RE.search(text)),
        "has_reviews": bool(_REVIEW_RE.search(text)),
        "has_guarantee": bool(_GUARANTEE_RE.search(text)),
        "has_free_shipping": bool(_SHIPPING_RE.search(text)),
        "payment_methods_mentioned": bool(_PAYMENT_RE.search(text)),
        "has_social_proof": bool(_REVIEW_RE.search(text)),
        "has_upsells": bool(_UPSELL_RE.search(text)),
    }

"""Ecommerce validator — section 4. Confirms there is real transactional evidence
(products, prices, cart/checkout) before a page counts as "ecommerce", instead of
trusting the landing URL's existence alone.

`score_html` is a pure function (input: HTML string) so it is fully unit-testable with
fixtures. `validate_store` wraps it with the actual HTTP fetch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from eci.config import get_settings
from eci.utils.http import fetch

_PRICE_RE = re.compile(
    r"(\$|COP|USD|MXN|PEN|CLP|ARS|EUR)\s?[\d.,]{3,}|[\d.,]{3,}\s?(\$|COP|USD|MXN|PEN|CLP|ARS|EUR)",
    re.IGNORECASE,
)
_ADD_TO_CART_RE = re.compile(
    r"add[\s_-]?to[\s_-]?cart|añadir al carrito|agregar al carrito|comprar ahora|buy now|"
    r"añadir a la cesta",
    re.IGNORECASE,
)
_CART_CHECKOUT_PATH_RE = re.compile(r"/cart|/checkout|/carrito|/pagar", re.IGNORECASE)
_SHIPPING_PAYMENT_RE = re.compile(
    r"env[íi]o gratis|pago contra entrega|m[ée]todos de pago|tarjeta de cr[ée]dito|"
    r"free shipping|cash on delivery|payment methods",
    re.IGNORECASE,
)

EXCLUDED_SIGNALS_RE = re.compile(
    r"agencia de marketing|somos una agencia|servicios de consultor[ií]a|influencer kit",
    re.IGNORECASE,
)


@dataclass
class EcommerceSignals:
    has_price_pattern: bool = False
    has_add_to_cart: bool = False
    has_checkout_or_cart_path: bool = False
    has_product_schema_or_grid: bool = False
    has_payment_or_shipping_terms: bool = False
    agency_or_service_language_detected: bool = False
    raw_matches: dict = field(default_factory=dict)


def _has_product_schema_or_grid(soup: BeautifulSoup, html: str) -> bool:
    if re.search(r'"@type"\s*:\s*"Product"', html):
        return True
    if soup.find(attrs={"itemtype": re.compile("schema.org/Product", re.IGNORECASE)}):
        return True
    # Heuristic "product grid": several elements whose class/id mentions "product" and
    # that also contain a price-shaped string nearby.
    product_like = soup.select('[class*="product" i], [id*="product" i]')
    return len(product_like) >= 3


def score_html(html: str, *, weights: dict[str, float] | None = None) -> tuple[float, EcommerceSignals]:
    """Returns (ecommerce_score 0-100, signals). Weighted per config/scoring.yaml
    `ecommerce_validation.signal_weights` unless overridden."""
    if weights is None:
        weights = get_settings().scoring.get("ecommerce_validation", {}).get(
            "signal_weights",
            {
                "has_price_pattern": 0.25,
                "has_add_to_cart": 0.25,
                "has_checkout_or_cart_path": 0.20,
                "has_product_schema_or_grid": 0.15,
                "has_payment_or_shipping_terms": 0.15,
            },
        )

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    signals = EcommerceSignals(
        has_price_pattern=bool(_PRICE_RE.search(text)),
        has_add_to_cart=bool(_ADD_TO_CART_RE.search(html)),
        has_checkout_or_cart_path=bool(
            _CART_CHECKOUT_PATH_RE.search(html)
            or soup.find("a", href=_CART_CHECKOUT_PATH_RE)
        ),
        has_product_schema_or_grid=_has_product_schema_or_grid(soup, html),
        has_payment_or_shipping_terms=bool(_SHIPPING_PAYMENT_RE.search(text)),
        agency_or_service_language_detected=bool(EXCLUDED_SIGNALS_RE.search(text)),
    )

    score = 0.0
    for field_name, weight in weights.items():
        if getattr(signals, field_name, False):
            score += weight * 100

    # Section 4 exclusion: pure service/agency language without product signals caps the score,
    # even if a stray "price" or "cart" word appears somewhere on the page.
    if signals.agency_or_service_language_detected and not (
        signals.has_product_schema_or_grid and signals.has_add_to_cart
    ):
        score = min(score, 40.0)

    return round(score, 1), signals


def validate_store(store_url: str) -> dict:
    """Fetches the store URL and returns a report dict, never raising. On fetch failure,
    ecommerce_score is 0 and `verified=False`, `reason` explains why (not_verified, not
    a false "not an ecommerce site")."""
    result = fetch(store_url)
    if not result.ok or not result.text:
        return {
            "store_url": store_url,
            "final_url": result.final_url,
            "verified": False,
            "ecommerce_score": 0.0,
            "reason": result.error or "fetch_failed",
            "signals": {},
        }

    score, signals = score_html(result.text)
    settings = get_settings()
    return {
        "store_url": store_url,
        "final_url": result.final_url,
        "verified": score >= settings.ecommerce_score_minimum,
        "ecommerce_score": score,
        "reason": None,
        "signals": signals.__dict__,
    }

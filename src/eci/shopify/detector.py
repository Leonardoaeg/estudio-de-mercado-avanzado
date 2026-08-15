"""Shopify detector — section 5. Multi-signal, never affirms Shopify on one weak hit.

`detect_from_html` is pure (testable with fixtures); `detect_store` wraps it with the
HTTP fetch. `--shopify-only` (CLI) filters on `shopify_detected` after this runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eci.config import get_settings
from eci.utils.http import fetch

_SIGNAL_PATTERNS: dict[str, re.Pattern] = {
    "cdn_shopify_com": re.compile(r"cdn\.shopify\.com", re.IGNORECASE),
    "cdn_shop_path": re.compile(r"/cdn/shop/", re.IGNORECASE),
    "shopify_section_class": re.compile(r"shopify-section", re.IGNORECASE),
    "shopify_theme_js_global": re.compile(r"Shopify\.theme|window\.Shopify\s*=", re.IGNORECASE),
    "shopify_analytics_object": re.compile(r"ShopifyAnalytics|window\.ShopifyAnalytics", re.IGNORECASE),
}


@dataclass
class ShopifySignals:
    matched: dict[str, bool]

    @property
    def matched_count(self) -> int:
        return sum(1 for v in self.matched.values() if v)


def detect_from_html(html: str, *, weights: dict[str, float] | None = None, min_signals: int | None = None) -> tuple[bool, float, ShopifySignals]:
    """Returns (shopify_detected, shopify_confidence 0-1, signals)."""
    settings = get_settings()
    shopify_cfg = settings.scoring.get("shopify_detection", {})
    if weights is None:
        weights = shopify_cfg.get(
            "signal_weights",
            {
                "cdn_shopify_com": 0.35,
                "cdn_shop_path": 0.25,
                "shopify_section_class": 0.15,
                "shopify_theme_js_global": 0.15,
                "shopify_analytics_object": 0.10,
            },
        )
    if min_signals is None:
        min_signals = shopify_cfg.get("minimum_signals_required", 2)

    matched = {name: bool(pattern.search(html)) for name, pattern in _SIGNAL_PATTERNS.items()}
    signals = ShopifySignals(matched=matched)

    confidence = sum(weights.get(name, 0) for name, hit in matched.items() if hit)
    confidence = round(min(confidence, 1.0), 2)

    detected = signals.matched_count >= min_signals
    return detected, confidence if detected else round(confidence * 0.5, 2), signals


def detect_store(store_url: str) -> dict:
    """Fetches the store URL and runs `detect_from_html`. On fetch failure, returns
    `shopify_detected=None` (unknown, not False) per section 3's "never invent" rule."""
    result = fetch(store_url)
    if not result.ok or not result.text:
        return {
            "store_url": store_url,
            "shopify_detected": None,
            "shopify_confidence": 0.0,
            "shopify_signals": {},
            "reason": result.error or "fetch_failed",
        }

    detected, confidence, signals = detect_from_html(result.text)
    return {
        "store_url": store_url,
        "shopify_detected": detected,
        "shopify_confidence": confidence,
        "shopify_signals": signals.matched,
        "reason": None,
    }

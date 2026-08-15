"""Brand/marketplace exclusion — operator instruction (2026-08-14): mega-brands and
general marketplaces (SHEIN, Mercado Libre, Amazon, ...) must never be presented as a
"small independent store" example. Their ads may still inform aggregate creative-pattern
stats (hooks/angles/offers) as market-wide reference — see reports/generator.py, where
excluded advertisers feed the creative-reference pool but never the rankings/Deep Dive/
store exports.

This is a config-driven, case-insensitive substring match against page_name — simple and
transparent on purpose, so anyone can read `config/excluded_brands.yaml` and know exactly
why a brand is or isn't excluded, rather than an opaque size/revenue heuristic no one can
verify from Meta Ad Library data alone.
"""

from __future__ import annotations

from eci.config import get_settings
from eci.utils.urls import extract_domain


def is_excluded_brand(page_name: str | None) -> tuple[bool, str | None]:
    """Returns (excluded, reason) where reason is 'marketplace', 'mega_brand', or None."""
    if not page_name:
        return False, None
    normalized = page_name.strip().lower()

    settings = get_settings()
    cfg = settings.excluded_brands
    for reason, patterns in (
        ("marketplace", cfg.get("marketplaces", [])),
        ("mega_brand", cfg.get("mega_brands", [])),
    ):
        for pattern in patterns:
            if pattern.lower() in normalized:
                return True, reason
    return False, None


def is_excluded_domain(store_url: str | None) -> tuple[bool, str | None]:
    """Returns (excluded, reason) where reason is 'shared_platform', 'marketplace_domain',
    or None. Two distinct domain-based signals, both invisible to is_excluded_brand's
    page_name matching:
      - shared_platforms: white-label storefronts hosting multiple unrelated advertisers
        on the same product URL (pideelo.co showed 4 different brands on one identical URL).
      - marketplace_domains: the ad's own page_name looks like an independent brand (e.g.
        "seltz"), but the landing URL is a major retailer's own domain (costco.com.mx) —
        the advertiser doesn't have their own store, they're just promoting a marketplace
        listing.
    """
    domain = extract_domain(store_url)
    if not domain:
        return False, None
    settings = get_settings()
    for reason, key in (("shared_platform", "shared_platforms"), ("marketplace_domain", "marketplace_domains")):
        domains = settings.excluded_brands.get(key, [])
        if any(p.lower() == domain.lower() for p in domains):
            return True, reason
    return False, None

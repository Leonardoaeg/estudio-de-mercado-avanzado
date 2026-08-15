"""Niche/subniche classifier — sections 8/9. Wraps the seed taxonomy in config/niches.yaml.

Top-level niche is usually known already (it's what the run searched for), so this module
mainly resolves the *subniche* and its confidence from ad text, plus lets the discovery
engine register subniches that don't match any seed (kept as `subniche=None`,
`classification_confidence=0.0`, never forced into the nearest seed).
"""

from __future__ import annotations

from eci.config import get_settings


def get_niche_labels() -> dict[str, str]:
    settings = get_settings()
    return {key: value.get("label", key) for key, value in settings.niches.items()}


def get_subniche_seeds(niche: str) -> dict[str, list[str]]:
    """Returns {subniche: [seed_terms]} where each seed subniche name is itself used as
    its own single keyword (underscores -> spaces), since niches.yaml stores subniches as
    a flat list rather than subniche->keywords. Kept as a dict for classify_subniche's API."""
    settings = get_settings()
    niche_cfg = settings.niches.get(niche.upper(), {})
    subniches = niche_cfg.get("subniches", [])
    return {sub: [sub] for sub in subniches}


def classify_subniche_for_niche(text: str, niche: str) -> tuple[str | None, float]:
    from eci.discovery.keyword_engine import classify_subniche

    seeds = get_subniche_seeds(niche)
    return classify_subniche(text, seeds)

"""Data Confidence Score — section 23. Kept strictly separate from Scale Signal Score: a
brand can have huge advertising presence (high Scale Signal) but incomplete/unverified
data about it (low Confidence), and the report must show both numbers, never blend them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from eci.config import get_settings

DEFAULT_WEIGHTS = {
    "field_completeness": 0.40,
    "source_reliability": 0.25,
    "sample_freshness": 0.20,
    "cross_signal_agreement": 0.15,
}

SOURCE_RELIABILITY = {
    "meta_graph_api": 1.0,
    "meta_web_scraper": 0.7,
    "mock": 0.3,  # never presented as real market data — see IMPLEMENTATION_PLAN.md
}

EXPECTED_FIELDS = (
    "page_name",
    "fanpage_url",
    "store_url",
    "final_store_url",
    "instagram_url",
    "country",
    "oldest_active_ad_url",
    "oldest_active_ad_date",
    "dominant_format",
    "dominant_hook",
    "dominant_angle",
    "dominant_offer",
)


@dataclass
class ConfidenceInputs:
    advertiser_fields: dict  # {field_name: value_or_None}
    source_name: str
    last_verified_at: datetime
    cross_signals_agree: bool | None  # None when there weren't enough signals to compare


def _field_completeness(fields: dict) -> float:
    present = sum(
        1
        for name in EXPECTED_FIELDS
        if fields.get(name) not in (None, "", "unknown", "not_available", "not_verified")
    )
    return present / len(EXPECTED_FIELDS)


def _freshness_score(last_verified_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    if last_verified_at.tzinfo is None:
        last_verified_at = last_verified_at.replace(tzinfo=timezone.utc)
    hours = max((now - last_verified_at).total_seconds() / 3600, 0)
    if hours <= 24:
        return 1.0
    if hours <= 24 * 7:
        return 0.7
    if hours <= 24 * 30:
        return 0.4
    return 0.15


def calculate_confidence_score(inputs: ConfidenceInputs, *, weights: dict | None = None) -> tuple[float, dict]:
    settings = get_settings()
    weights = weights or settings.scoring.get("confidence_weights", DEFAULT_WEIGHTS)

    completeness = _field_completeness(inputs.advertiser_fields)
    reliability = SOURCE_RELIABILITY.get(inputs.source_name, 0.5)
    freshness = _freshness_score(inputs.last_verified_at)
    agreement = 1.0 if inputs.cross_signals_agree else (0.5 if inputs.cross_signals_agree is None else 0.0)

    breakdown = {
        "field_completeness": round(completeness, 3),
        "source_reliability": round(reliability, 3),
        "sample_freshness": round(freshness, 3),
        "cross_signal_agreement": round(agreement, 3),
    }
    score = sum(breakdown[k] * weights.get(k, 0) for k in breakdown) * 100
    return round(score, 1), breakdown

"""Longevity metrics — sections 18 + the operator's explicit 30-90 day reference window.

Pure functions over a list of per-ad facts, so they're trivially unit-testable and don't
care whether the ads came from Mock/Graph API/scraper.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class AdLongevityFact:
    ad_id: str
    age_days: int | None
    ad_library_url: str | None = None
    start_date: str | None = None
    format: str | None = None
    hook_type: str | None = None
    product: str | None = None


@dataclass
class LongevitySummary:
    oldest_active_ad_id: str | None
    oldest_active_ad_url: str | None
    oldest_active_ad_date: str | None
    oldest_active_ad_age_days: int | None
    median_ad_age: float | None
    average_ad_age: float | None
    ads_over_14_days: int
    ads_over_30_days: int
    ads_over_60_days: int
    ads_over_90_days: int
    ads_in_reference_window: int
    reference_window_ratio: float
    total_ads_with_known_age: int


def summarize_longevity(
    facts: list[AdLongevityFact],
    *,
    reference_min_age_days: int = 30,
    reference_max_age_days: int = 90,
) -> LongevitySummary:
    known = [f for f in facts if f.age_days is not None]
    if not known:
        return LongevitySummary(
            oldest_active_ad_id=None,
            oldest_active_ad_url=None,
            oldest_active_ad_date=None,
            oldest_active_ad_age_days=None,
            median_ad_age=None,
            average_ad_age=None,
            ads_over_14_days=0,
            ads_over_30_days=0,
            ads_over_60_days=0,
            ads_over_90_days=0,
            ads_in_reference_window=0,
            reference_window_ratio=0.0,
            total_ads_with_known_age=0,
        )

    ages = [f.age_days for f in known]  # type: ignore[misc]
    oldest = max(known, key=lambda f: f.age_days)  # type: ignore[arg-type]

    in_window = sum(1 for a in ages if reference_min_age_days <= a <= reference_max_age_days)

    return LongevitySummary(
        oldest_active_ad_id=oldest.ad_id,
        oldest_active_ad_url=oldest.ad_library_url,
        oldest_active_ad_date=oldest.start_date,
        oldest_active_ad_age_days=oldest.age_days,
        median_ad_age=round(statistics.median(ages), 1),
        average_ad_age=round(statistics.mean(ages), 1),
        ads_over_14_days=sum(1 for a in ages if a >= 14),
        ads_over_30_days=sum(1 for a in ages if a >= 30),
        ads_over_60_days=sum(1 for a in ages if a >= 60),
        ads_over_90_days=sum(1 for a in ages if a >= 90),
        ads_in_reference_window=in_window,
        reference_window_ratio=round(in_window / len(ages), 3),
        total_ads_with_known_age=len(ages),
    )


def dominant_value(values: list[str | None]) -> str | None:
    """Most frequent non-null value, used for dominant_format/hook/angle/offer. None if
    every value is missing (never fabricates a "dominant" when there's no data)."""
    known = [v for v in values if v]
    if not known:
        return None
    counts: dict[str, int] = {}
    for v in known:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda k: counts[k])

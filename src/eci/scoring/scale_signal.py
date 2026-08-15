"""Scale Signal Score — section 22. 0-100. Explicitly a proxy for advertising presence,
never a proxy for sales/ROAS/profitability (section 3's objectivity rule). Volume is
log-normalized then percentile-scaled within the run's cohort, never used raw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from eci.config import get_settings
from eci.metrics.longevity import LongevitySummary

DEFAULT_WEIGHTS = {
    "active_ads_volume": 0.35,
    "persistence": 0.25,
    "creative_diversity": 0.15,
    "format_diversity": 0.10,
    "historical_presence": 0.10,
    "ecommerce_verification": 0.05,
}


@dataclass
class ScaleSignalInputs:
    active_ad_count: int
    cohort_active_ad_counts: list[int]  # every advertiser's active_ad_count in this run, for percentile scaling
    longevity: LongevitySummary
    n_creative_families: int
    n_total_ads: int
    format_distribution_pct: dict[str, float]  # {"video": %, "image": %, "carousel": %, "unknown": %}
    snapshots_observed: int  # how many historical snapshots exist for this advertiser
    ecommerce_score: float  # 0-100


def _percentile_rank(value: float, cohort: list[float]) -> float:
    """Fraction of the cohort that `value` is >= to, in [0, 1]. With a cohort of 1 (itself),
    returns 1.0 — there's nothing to rank against, so we don't penalize a lone advertiser."""
    if not cohort:
        return 0.0
    at_or_below = sum(1 for v in cohort if v <= value)
    return at_or_below / len(cohort)


def _log_normalize(value: int, cohort: list[int]) -> float:
    log_value = math.log10(1 + max(value, 0))
    log_cohort = [math.log10(1 + max(v, 0)) for v in cohort] or [log_value]
    return _percentile_rank(log_value, log_cohort)


def _persistence_score(longevity: LongevitySummary, *, min_age: int, max_age: int, weights: dict) -> float:
    total = longevity.total_ads_with_known_age
    if total == 0:
        return 0.0
    reference_share = longevity.ads_in_reference_window / total
    long_tail_share = longevity.ads_over_90_days / total
    recent_count = total - longevity.ads_over_30_days  # ads younger than the reference window's min age
    recent_share = recent_count / total

    return (
        reference_share * weights.get("reference_window_weight", 0.6)
        + long_tail_share * weights.get("long_tail_weight", 0.25)
        + recent_share * weights.get("recent_weight", 0.15)
    )


def _format_diversity_score(distribution_pct: dict[str, float]) -> float:
    """1 - (share of the single dominant format), so an advertiser using only video scores
    low diversity (0) and one spread evenly across 3 formats scores near-max (~0.67)."""
    shares = [v / 100 for k, v in distribution_pct.items() if k != "unknown"]
    if not shares:
        return 0.0
    return round(1 - max(shares), 3)


def calculate_scale_signal_score(inputs: ScaleSignalInputs, *, weights: dict | None = None) -> tuple[float, dict]:
    settings = get_settings()
    scoring_cfg = settings.scoring
    weights = weights or scoring_cfg.get("scale_signal_weights", DEFAULT_WEIGHTS)
    window_cfg = scoring_cfg.get("longevity_reference_window", {})
    min_age = window_cfg.get("min_age_days", 30)
    max_age = window_cfg.get("max_age_days", 90)

    volume_component = _log_normalize(inputs.active_ad_count, inputs.cohort_active_ad_counts)
    persistence_component = _persistence_score(inputs.longevity, min_age=min_age, max_age=max_age, weights=window_cfg)
    diversity_component = (
        (inputs.n_creative_families / inputs.n_total_ads) if inputs.n_total_ads else 0.0
    )
    diversity_component = min(diversity_component, 1.0)
    format_component = _format_diversity_score(inputs.format_distribution_pct)
    historical_component = min(inputs.snapshots_observed / 8, 1.0)  # 8 weekly snapshots = full score
    ecommerce_component = max(0.0, min(inputs.ecommerce_score / 100, 1.0))

    breakdown = {
        "active_ads_volume": round(volume_component, 3),
        "persistence": round(persistence_component, 3),
        "creative_diversity": round(diversity_component, 3),
        "format_diversity": round(format_component, 3),
        "historical_presence": round(historical_component, 3),
        "ecommerce_verification": round(ecommerce_component, 3),
    }

    score = sum(breakdown[k] * weights.get(k, 0) for k in breakdown) * 100
    return round(score, 1), breakdown

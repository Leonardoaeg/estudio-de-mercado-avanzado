from datetime import datetime, timedelta, timezone

from eci.metrics.longevity import AdLongevityFact, dominant_value, summarize_longevity
from eci.scoring.confidence import ConfidenceInputs, calculate_confidence_score
from eci.scoring.scale_signal import ScaleSignalInputs, calculate_scale_signal_score


def _facts(ages):
    return [AdLongevityFact(ad_id=f"a{i}", age_days=age) for i, age in enumerate(ages)]


def test_summarize_longevity_basic_buckets():
    summary = summarize_longevity(_facts([5, 20, 35, 65, 95]))
    assert summary.oldest_active_ad_age_days == 95
    assert summary.ads_over_14_days == 4
    assert summary.ads_over_30_days == 3
    assert summary.ads_over_60_days == 2
    assert summary.ads_over_90_days == 1
    assert summary.total_ads_with_known_age == 5


def test_summarize_longevity_reference_window_30_90():
    summary = summarize_longevity(_facts([10, 30, 50, 90, 91, 200]), reference_min_age_days=30, reference_max_age_days=90)
    assert summary.ads_in_reference_window == 3  # 30, 50, 90
    assert round(summary.reference_window_ratio, 2) == round(3 / 6, 2)


def test_summarize_longevity_empty_returns_nones():
    summary = summarize_longevity([])
    assert summary.oldest_active_ad_age_days is None
    assert summary.median_ad_age is None
    assert summary.total_ads_with_known_age == 0


def test_summarize_longevity_ignores_unknown_ages():
    summary = summarize_longevity(_facts([10, None, 50]))
    assert summary.total_ads_with_known_age == 2


def test_dominant_value():
    assert dominant_value(["video", "video", "image"]) == "video"
    assert dominant_value([None, None]) is None
    assert dominant_value([]) is None


def test_scale_signal_higher_volume_scores_higher_within_cohort():
    longevity = summarize_longevity(_facts([40, 45, 50]))
    small = ScaleSignalInputs(
        active_ad_count=10, cohort_active_ad_counts=[10, 50, 100], longevity=longevity,
        n_creative_families=3, n_total_ads=10,
        format_distribution_pct={"video": 60, "image": 40, "carousel": 0, "unknown": 0},
        snapshots_observed=0, ecommerce_score=80,
    )
    large = ScaleSignalInputs(
        active_ad_count=100, cohort_active_ad_counts=[10, 50, 100], longevity=longevity,
        n_creative_families=3, n_total_ads=100,
        format_distribution_pct={"video": 60, "image": 40, "carousel": 0, "unknown": 0},
        snapshots_observed=0, ecommerce_score=80,
    )
    small_score, _ = calculate_scale_signal_score(small)
    large_score, _ = calculate_scale_signal_score(large)
    assert large_score > small_score


def test_scale_signal_score_bounded_0_100():
    longevity = summarize_longevity(_facts([100, 100, 100]))
    inputs = ScaleSignalInputs(
        active_ad_count=1000, cohort_active_ad_counts=[1000], longevity=longevity,
        n_creative_families=1000, n_total_ads=1000,
        format_distribution_pct={"video": 34, "image": 33, "carousel": 33, "unknown": 0},
        snapshots_observed=100, ecommerce_score=100,
    )
    score, breakdown = calculate_scale_signal_score(inputs)
    assert 0 <= score <= 100


def test_confidence_score_penalizes_missing_fields():
    now = datetime.now(timezone.utc)
    complete = ConfidenceInputs(
        advertiser_fields={
            "page_name": "X", "fanpage_url": "y", "store_url": "z", "final_store_url": "z",
            "instagram_url": "i", "country": "CO", "oldest_active_ad_url": "u",
            "oldest_active_ad_date": "2026-01-01", "dominant_format": "video",
            "dominant_hook": "offer", "dominant_angle": "ahorro", "dominant_offer": "percentage_discount",
        },
        source_name="meta_graph_api", last_verified_at=now, cross_signals_agree=True,
    )
    sparse = ConfidenceInputs(
        advertiser_fields={"page_name": "X"},
        source_name="mock", last_verified_at=now - timedelta(days=60), cross_signals_agree=None,
    )
    complete_score, _ = calculate_confidence_score(complete)
    sparse_score, _ = calculate_confidence_score(sparse)
    assert complete_score > sparse_score
    assert 0 <= sparse_score <= 100


def test_confidence_score_bounded():
    now = datetime.now(timezone.utc)
    inputs = ConfidenceInputs(advertiser_fields={}, source_name="unknown_source", last_verified_at=now, cross_signals_agree=False)
    score, _ = calculate_confidence_score(inputs)
    assert 0 <= score <= 100

from eci.insights.insight_engine import (
    build_niche_insights,
    insight_boolean_flag_share,
    insight_dominant_label_share,
    insight_early_seconds_pattern,
)


def test_insight_boolean_flag_share_basic():
    insight = insight_boolean_flag_share("UGC", [True, True, False, None], sample_label="anuncios")
    assert insight is not None
    assert "2 de 3 anuncios" in insight.statement
    assert insight.evidence_level == "INFERENCIA"


def test_insight_boolean_flag_share_none_when_all_unknown():
    assert insight_boolean_flag_share("UGC", [None, None]) is None


def test_insight_boolean_flag_share_empty_list():
    assert insight_boolean_flag_share("UGC", []) is None


def test_insight_dominant_label_share_zero_total():
    assert insight_dominant_label_share("hook", "offer", 0, 0) is None


def test_insight_early_seconds_pattern():
    insight = insight_early_seconds_pattern(93, 100)
    assert "93 de 100" in insight.statement


def test_build_niche_insights_never_makes_causal_claims():
    stats = {
        "ugc_flags": [True, False, True],
        "demonstration_flags": [True, True],
        "testimonial_flags": [False, False],
        "total_ads": 10,
        "dominant_hook_label": "offer",
        "dominant_hook_count": 4,
        "hook_pattern_matches": 8,
    }
    insights = build_niche_insights(stats)
    assert len(insights) > 0
    for insight in insights:
        assert "mejor" not in insight.statement.lower()
        assert "garantiza" not in insight.statement.lower()


def test_build_niche_insights_empty_stats_returns_no_insights():
    assert build_niche_insights({}) == []

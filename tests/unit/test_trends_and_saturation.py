from eci.trends.saturation_engine import creative_saturation, product_saturation
from eci.trends.trend_engine import compare_counts


def test_compare_counts_detects_new_entrant():
    results = compare_counts("product", baseline_counts={}, current_counts={"creatina gummies": 9})
    assert len(results) == 1
    assert results[0].is_new is True
    assert results[0].variation_percentage is None


def test_compare_counts_computes_variation_percentage():
    results = compare_counts("product", baseline_counts={"creatina gummies": 9}, current_counts={"creatina gummies": 26})
    assert results[0].variation_percentage == round((26 - 9) / 9 * 100, 1)


def test_compare_counts_filters_noise_below_minimum():
    results = compare_counts("product", baseline_counts={}, current_counts={"raro": 1}, min_current_count=2)
    assert results == []


def test_compare_counts_new_entrants_ranked_first():
    results = compare_counts(
        "product",
        baseline_counts={"a": 10, "b": 10},
        current_counts={"a": 12, "b": 10, "c": 5},  # c is new
    )
    assert results[0].label == "c"
    assert results[0].is_new is True


def test_product_saturation_classifies_alta_media_baja():
    ads_by_product = {
        "leggings": [{"page_id": f"p{i}"} for i in range(12)],  # 12 brands -> ALTA
        "faja": [{"page_id": "p1"}, {"page_id": "p1"}, {"page_id": "p2"}],  # 2 brands, few ads -> BAJA
    }
    results = product_saturation(ads_by_product)
    levels = {r.label: r.level for r in results}
    assert levels["leggings"] == "ALTA"
    assert levels["faja"] == "BAJA"


def test_creative_saturation_counts_distinct_brands():
    ads_by_combo = {"offer+ahorro": [{"page_id": "p1"}, {"page_id": "p2"}, {"page_id": "p1"}]}
    results = creative_saturation(ads_by_combo)
    assert results[0].distinct_brands == 2
    assert results[0].total_ads == 3

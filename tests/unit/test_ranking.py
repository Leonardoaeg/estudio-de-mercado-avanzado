from eci.ranking.rankers import rank_by_acceleration, rank_by_presence


def test_rank_by_presence_sorted_desc_by_scale_signal():
    advertisers = [
        {"page_id": "a", "page_name": "A", "scale_signal_score": 50, "active_ad_count": 60},
        {"page_id": "b", "page_name": "B", "scale_signal_score": 90, "active_ad_count": 55},
        {"page_id": "c", "page_name": "C", "scale_signal_score": 70, "active_ad_count": 200},
    ]
    ranked = rank_by_presence(advertisers, top_n=10)
    assert [r.page_id for r in ranked] == ["b", "c", "a"]
    assert ranked[0].rank == 1


def test_rank_by_presence_respects_top_n():
    advertisers = [{"page_id": str(i), "page_name": str(i), "scale_signal_score": i, "active_ad_count": i} for i in range(20)]
    ranked = rank_by_presence(advertisers, top_n=5)
    assert len(ranked) == 5
    assert ranked[0].page_id == "19"


def test_rank_by_acceleration_excludes_advertisers_without_baseline():
    advertisers = [
        {"page_id": "a", "page_name": "A", "acceleration_score": 10, "growth_percentage": 5},
        {"page_id": "b", "page_name": "B", "acceleration_score": 0, "growth_percentage": None},
    ]
    ranked = rank_by_acceleration(advertisers)
    assert len(ranked) == 1
    assert ranked[0].page_id == "a"


def test_rank_by_acceleration_empty_when_no_baselines():
    advertisers = [{"page_id": "a", "page_name": "A", "acceleration_score": 0, "growth_percentage": None}]
    assert rank_by_acceleration(advertisers) == []

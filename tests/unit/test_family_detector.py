from eci.creative.family_detector import ad_to_family_map, build_families


def _ad(ad_id, page_id, text, hook="offer", product="vestido"):
    return {
        "ad_id": ad_id, "page_id": page_id, "primary_text": text, "hook": hook,
        "product": product, "landing_url": "https://store.com/p", "cta": "comprar",
        "format": "video", "hook_type": hook,
    }


def test_near_duplicate_ads_grouped_into_same_family():
    ads = [
        _ad("1", "p1", "Oferta especial 20% off en vestidos hoy mismo"),
        _ad("2", "p1", "Oferta especial 20% off en vestidos hoy mismo!!"),
        _ad("3", "p1", "Oferta especial 20% off en vestidos, hoy mismo."),
    ]
    families = build_families(ads, similarity_threshold=0.8)
    assert len(families) == 1
    mapping = ad_to_family_map(families)
    assert mapping["1"] == mapping["2"] == mapping["3"]


def test_distinct_concepts_get_distinct_families():
    ads = [
        _ad("1", "p1", "Oferta especial 20% off en vestidos hoy"),
        _ad("2", "p1", "Testimonio real de clienta satisfecha con nuestra faja moldeadora"),
    ]
    families = build_families(ads, similarity_threshold=0.8)
    assert len(families) == 2


def test_families_are_scoped_per_page():
    ads = [
        _ad("1", "p1", "Mismo texto exacto de anuncio"),
        _ad("2", "p2", "Mismo texto exacto de anuncio"),
    ]
    families = build_families(ads, similarity_threshold=0.8)
    mapping = ad_to_family_map(families)
    assert mapping["1"] != mapping["2"]


def test_empty_ads_returns_no_families():
    assert build_families([]) == {}

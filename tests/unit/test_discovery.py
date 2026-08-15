from eci.discovery.keyword_engine import classify_subniche, expand_keywords
from eci.models.schemas import AdFormat, NormalizedAd


def _ad(product, headline=None, primary_text=None):
    return NormalizedAd(
        ad_id="x", source_name="mock", page_id="p1", page_name="Store", ad_library_url=None,
        active=True, start_date=None, age_days=None, format=AdFormat.VIDEO,
        primary_text=primary_text, headline=headline, description=None, cta=None,
        landing_url=None, final_landing_url=None, product=product, product_category=None,
        price=None, old_price=None, discount=None, offer_type=None, hook=None, hook_type=None,
        creative_angle=None, creative_style=None, ugc_detected=None, testimonial_detected=None,
        demonstration_detected=None, problem_solution_detected=None, comparison_detected=None,
        creative_fingerprint=None, claims_risk_flags=[], niche="TEXTIL", subniche=None, confidence=0.0,
    )


def test_expand_keywords_finds_frequent_new_terms():
    ads = [_ad("leggings seamless", headline="leggings seamless") for _ in range(3)]
    new_keywords = expand_keywords(ads, existing_keywords={"vestido"}, min_frequency=2)
    assert any("leggings" in kw for kw in new_keywords)


def test_expand_keywords_excludes_existing():
    ads = [_ad("vestido azul", headline="vestido azul") for _ in range(3)]
    new_keywords = expand_keywords(ads, existing_keywords={"vestido azul"}, min_frequency=2)
    assert "vestido azul" not in new_keywords


def test_expand_keywords_respects_cap():
    ads = []
    for i in range(30):
        ads.extend([_ad(f"producto{i}", headline=f"producto{i} especial")] * 2)
    new_keywords = expand_keywords(ads, existing_keywords=set(), max_new_keywords=5, min_frequency=2)
    assert len(new_keywords) <= 5


def test_classify_subniche_by_seed_overlap():
    seeds = {"vestidos": ["vestido"], "jeans": ["jean", "levanta cola"]}
    subniche, confidence = classify_subniche("Este jean levanta cola es una maravilla", seeds)
    assert subniche == "jeans"
    assert confidence > 0


def test_classify_subniche_no_match():
    seeds = {"vestidos": ["vestido"]}
    subniche, confidence = classify_subniche("un texto totalmente distinto", seeds)
    assert subniche is None
    assert confidence == 0.0


def test_classify_subniche_tolerates_singular_plural_mismatch():
    """Regression test: niches.yaml stores seeds plural ("chaquetas"), but a user
    describing a product to sell writes singular ("chaqueta rompevientos unisex") — a
    plain substring check never matched either direction (found via product_viability.py,
    2026-08-14)."""
    seeds = {"chaquetas": ["chaquetas"]}
    subniche, confidence = classify_subniche("chaqueta rompevientos unisex, tela impermeable", seeds)
    assert subniche == "chaquetas"
    assert confidence > 0


def test_classify_subniche_empty_text():
    subniche, confidence = classify_subniche("", {"vestidos": ["vestido"]})
    assert subniche is None
    assert confidence == 0.0

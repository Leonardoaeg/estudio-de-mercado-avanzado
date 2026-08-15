"""Smoke test for the report generator: builds a tiny synthetic bundle and checks every
output file gets produced with the expected section structure. Writes to a tmp_path
(via monkeypatch on REPORTS_DIR) instead of the real reports/ directory, so running the
test suite never clutters real research output.
"""

from eci.models.schemas import AdFormat, NormalizedAd
from eci.ranking.rankers import RankedAdvertiser
from eci.reports import generator as generator_module
from eci.reports.generator import ReportBundle, write_reports


def _ad(ad_id, page_id, age_days, format_=AdFormat.VIDEO, hook_type="offer", angle="ahorro"):
    return NormalizedAd(
        ad_id=ad_id, source_name="mock", page_id=page_id, page_name="Test Store",
        ad_library_url=f"https://example.com/{ad_id}", active=True, start_date=None, age_days=age_days,
        format=format_, primary_text="Oferta especial 20% off", headline="Producto X", description=None,
        cta="Comprar", landing_url=None, final_landing_url=None, product="Producto X", product_category=None,
        price=None, old_price=None, discount=20.0, offer_type="percentage_discount", hook="Oferta especial",
        hook_type=hook_type, creative_angle=angle, creative_style=None, ugc_detected=True,
        testimonial_detected=False, demonstration_detected=True, problem_solution_detected=False,
        comparison_detected=False, creative_fingerprint="abc123", claims_risk_flags=[], niche="TEXTIL",
        subniche="vestidos", confidence=0.6,
    )


def test_write_reports_produces_all_four_formats(tmp_path, monkeypatch):
    monkeypatch.setattr(generator_module, "REPORTS_DIR", tmp_path)

    ads = [_ad(f"a{i}", "p1", age_days=40 + i) for i in range(5)]
    advertiser_row = {
        "page_id": "p1", "page_name": "Test Store", "fanpage_url": "https://facebook.com/p1",
        "store_url": "https://teststore.com", "niche": "TEXTIL", "subniche": "vestidos",
        "active_ad_count": 5, "video_count": 5, "image_count": 0, "carousel_count": 0,
        "unknown_format_count": 0, "oldest_active_ad_url": "https://example.com/a4",
        "oldest_active_ad_age_days": 44, "median_ad_age": 42, "average_ad_age": 42,
        "ads_over_14_days": 5, "ads_over_30_days": 5, "ads_over_60_days": 0, "ads_over_90_days": 0,
        "ads_in_reference_window": 5, "reference_window_ratio": 1.0,
        "dominant_format": "video", "dominant_hook": "offer", "dominant_angle": "ahorro",
        "dominant_offer": "percentage_discount", "shopify_detected": True, "ecommerce_score": 85.0,
        "scale_signal_score": 72.5, "confidence_score": 60.0, "growth_percentage": None,
        "_ads": ads,
    }

    bundle = ReportBundle(
        niche="TEXTIL", market="CO", run_uuid="test-run", source_name="mock",
        pages_discovered=1, pages_analyzed=1, ecommerce_verified=1, stores_over_threshold=1,
        minimum_active_ads=5, advertisers=[advertiser_row], all_advertisers=[advertiser_row],
        presence_ranking=[RankedAdvertiser(rank=1, page_id="p1", page_name="Test Store", score=72.5)],
        acceleration_ranking=[], format_counts={"video": 5, "image": 0, "carousel": 0, "unknown": 0},
    )

    md_path = write_reports(bundle)
    run_dir = md_path.parent

    assert (run_dir / "report.md").exists()
    assert (run_dir / "report.html").exists()
    assert (run_dir / "advertisers.csv").exists()
    assert (run_dir / "report.json").exists()

    md_content = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "META ADS CREATIVE INTELLIGENCE" in md_content
    assert "Top 10 — Highest Advertising Presence" in md_content
    assert "Deep Dive — Top 10" in md_content
    assert "Test Store" in md_content
    assert "HIPÓTESIS" in md_content  # objectivity language present

    html_content = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "<table>" in html_content

    import json
    payload = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["niche"] == "TEXTIL"
    assert payload["advertisers"][0]["page_id"] == "p1"
    assert "_ads" not in payload["advertisers"][0]  # internal helper key never leaks into JSON


def test_write_reports_claims_sensitive_niche_shows_annex(tmp_path, monkeypatch):
    monkeypatch.setattr(generator_module, "REPORTS_DIR", tmp_path)

    risky_ad = _ad("r1", "p2", age_days=10)
    risky_ad.claims_risk_flags = ["cura_enfermedad"]
    advertiser_row = {
        "page_id": "p2", "page_name": "Salud Store", "fanpage_url": None, "store_url": None,
        "niche": "SALUD", "subniche": None, "active_ad_count": 1, "video_count": 1, "image_count": 0,
        "carousel_count": 0, "unknown_format_count": 0, "oldest_active_ad_url": None,
        "oldest_active_ad_age_days": 10, "median_ad_age": 10, "average_ad_age": 10,
        "ads_over_14_days": 0, "ads_over_30_days": 0, "ads_over_60_days": 0, "ads_over_90_days": 0,
        "ads_in_reference_window": 0, "reference_window_ratio": 0.0, "dominant_format": "video",
        "dominant_hook": None, "dominant_angle": None, "dominant_offer": None, "shopify_detected": None,
        "ecommerce_score": 80.0, "scale_signal_score": 40.0, "confidence_score": 30.0,
        "growth_percentage": None, "_ads": [risky_ad],
    }
    bundle = ReportBundle(
        niche="SALUD", market="CO", run_uuid="test-run-2", source_name="mock",
        pages_discovered=1, pages_analyzed=1, ecommerce_verified=1, stores_over_threshold=1,
        minimum_active_ads=1, advertisers=[advertiser_row], all_advertisers=[advertiser_row],
        presence_ranking=[RankedAdvertiser(rank=1, page_id="p2", page_name="Salud Store", score=40.0)],
        acceleration_ranking=[], format_counts={"video": 1, "image": 0, "carousel": 0, "unknown": 0},
    )
    md_path = write_reports(bundle)
    content = md_path.read_text(encoding="utf-8")
    assert "Claims / Policy Risk" in content
    assert "cura_enfermedad" in content

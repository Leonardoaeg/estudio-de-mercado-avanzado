from pathlib import Path

from eci.ecommerce.validator import score_html

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_shopify_store_scores_high_ecommerce():
    html = (FIXTURES / "shopify_store.html").read_text(encoding="utf-8")
    score, signals = score_html(html)
    assert score >= 70
    assert signals.has_price_pattern
    assert signals.has_add_to_cart
    assert signals.has_checkout_or_cart_path


def test_non_shopify_ecommerce_still_scores_reasonably():
    html = (FIXTURES / "non_shopify_ecommerce.html").read_text(encoding="utf-8")
    score, signals = score_html(html)
    assert score >= 60


def test_agency_page_scores_low_and_is_capped():
    html = (FIXTURES / "agency_page.html").read_text(encoding="utf-8")
    score, signals = score_html(html)
    assert signals.agency_or_service_language_detected is True
    assert score <= 40


def test_empty_page_scores_zero():
    score, signals = score_html("<html><body></body></html>")
    assert score == 0.0

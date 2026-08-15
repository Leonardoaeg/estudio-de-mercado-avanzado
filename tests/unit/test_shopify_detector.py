from pathlib import Path

from eci.shopify.detector import detect_from_html

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_detects_shopify_with_multiple_signals():
    html = (FIXTURES / "shopify_store.html").read_text(encoding="utf-8")
    detected, confidence, signals = detect_from_html(html)
    assert detected is True
    assert confidence > 0.5
    assert signals.matched_count >= 2


def test_non_shopify_page_not_detected():
    html = (FIXTURES / "non_shopify_ecommerce.html").read_text(encoding="utf-8")
    detected, confidence, signals = detect_from_html(html)
    assert detected is False


def test_single_weak_signal_never_affirms_shopify():
    html = '<html><body><div class="shopify-section">hello</div></body></html>'
    detected, confidence, signals = detect_from_html(html, min_signals=2)
    assert detected is False
    assert signals.matched_count == 1


def test_two_signals_are_enough():
    html = (
        '<html><body><script src="https://cdn.shopify.com/x.js"></script>'
        '<div class="shopify-section">x</div></body></html>'
    )
    detected, confidence, signals = detect_from_html(html, min_signals=2)
    assert detected is True

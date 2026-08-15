"""Live integration tests — hit the real network. Skipped by default (see pyproject.toml
`addopts = -m "not live"`). Run explicitly with: pytest tests/integration -m live
"""

import pytest

from eci.ecommerce.validator import validate_store
from eci.shopify.detector import detect_store
from eci.utils.http import fetch


@pytest.mark.live
def test_fetch_real_url_succeeds():
    result = fetch("https://www.google.com")
    assert result.ok
    assert result.status_code == 200


@pytest.mark.live
def test_validate_real_shopify_store():
    # allbirds.com is a well-known public Shopify store, used as a live fixture. Some sandboxed
    # CI/dev environments restrict outbound HTTPS to arbitrary third-party domains (only a small
    # allowlist, e.g. google.com, is reachable) — that shows up as a TLS ConnectError, not a bug
    # in our code, so we skip rather than fail when this specific environment can't reach it.
    report = validate_store("https://www.allbirds.com")
    if report["reason"] and "transport_error" in str(report["reason"]):
        pytest.skip(f"Outbound network to third-party domains unavailable in this environment: {report['reason']}")
    assert report["ecommerce_score"] > 0


@pytest.mark.live
def test_detect_shopify_on_real_shopify_store():
    report = detect_store("https://www.allbirds.com")
    if report["reason"] and "transport_error" in str(report["reason"]):
        pytest.skip(f"Outbound network to third-party domains unavailable in this environment: {report['reason']}")
    assert report["shopify_detected"] is True
    assert report["shopify_confidence"] > 0

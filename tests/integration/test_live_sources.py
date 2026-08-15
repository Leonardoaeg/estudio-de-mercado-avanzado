"""Live integration tests for the Meta Ad Library sources. Skipped by default (see
pyproject.toml `addopts = -m "not live"`). Run explicitly with: pytest tests/integration -m live

These exercise `is_available()` regardless of whether credentials/browsers are actually
present (that's the point: a controlled "unavailable" is a passing test, not an error),
and only attempt a real network call when the precondition is met.
"""

import pytest

from eci.sources.meta_graph_api import MetaGraphAPISource
from eci.sources.meta_web_scraper import MetaWebScraperSource


@pytest.mark.live
def test_meta_graph_api_reports_missing_token_cleanly():
    source = MetaGraphAPISource()
    available, reason = source.is_available()
    if not available:
        assert "token" in (reason or "").lower()
        outcome = source.search_ads("vestido", "CO")
        assert outcome.ok is False
        assert outcome.exhausted is True
    else:
        outcome = source.search_ads("vestido", "CO")
        assert outcome.ok in (True, False)  # a real, non-crashing response either way


@pytest.mark.live
def test_meta_web_scraper_reports_availability_cleanly():
    source = MetaWebScraperSource()
    available, reason = source.is_available()
    if not available:
        assert reason is not None
    else:
        outcome = source.search_ads("vestido", "CO")
        assert outcome.ok is True  # scraper should not crash even if it finds 0 ads

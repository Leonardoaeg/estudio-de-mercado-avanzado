from eci.utils.urls import (
    canonical_store_key,
    extract_ad_id,
    extract_domain,
    meta_ad_library_ad_url_with_context,
    meta_ad_library_page_url,
    meta_ad_library_store_search_url,
    normalize_url,
)


def test_normalize_url_adds_scheme():
    assert normalize_url("example.com/product") == "https://example.com/product"


def test_normalize_url_strips_www_and_trailing_slash():
    assert normalize_url("https://www.example.com/products/") == "https://example.com/products"


def test_normalize_url_strips_tracking_params_and_sorts_query():
    result = normalize_url("https://example.com/p?b=2&utm_source=fb&a=1&fbclid=xyz")
    assert result == "https://example.com/p?a=1&b=2"


def test_normalize_url_none_and_empty():
    assert normalize_url(None) is None
    assert normalize_url("") is None
    assert normalize_url("   ") is None


def test_normalize_url_malformed_does_not_raise():
    assert normalize_url("not a url at all ::::") is None or isinstance(normalize_url("not a url at all ::::"), str)


def test_extract_domain():
    assert extract_domain("https://www.mystore.com/products/x?utm_source=fb") == "mystore.com"


def test_canonical_store_key_dedups_same_domain_different_paths():
    a = canonical_store_key("https://mystore.com/products/vestido-1")
    b = canonical_store_key("https://www.mystore.com/products/vestido-2?utm_source=meta")
    assert a == b == "mystore.com"


def test_canonical_store_key_none_on_missing():
    assert canonical_store_key(None) is None


def test_meta_ad_library_page_url_real_numeric_id():
    url = meta_ad_library_page_url("123456789")
    assert url is not None
    assert "view_all_page_id=123456789" in url


def test_meta_ad_library_page_url_none_for_fake_ids():
    # MockSource and the web scraper use non-numeric synthetic IDs (mock_..., scraped_...)
    # since neither exposes a real Facebook numeric Page ID — must never fabricate a link.
    assert meta_ad_library_page_url("mock_vestido_colombiano_2") is None
    assert meta_ad_library_page_url("scraped_zasha_jeans") is None
    assert meta_ad_library_page_url(None) is None
    assert meta_ad_library_page_url("") is None


def test_extract_ad_id_from_library_url():
    assert extract_ad_id("https://www.facebook.com/ads/library/?id=900858399742587") == "900858399742587"


def test_extract_ad_id_none_when_missing():
    assert extract_ad_id("https://www.facebook.com/ads/library/") is None
    assert extract_ad_id(None) is None


def test_meta_ad_library_ad_url_with_context_includes_search_seed():
    url = meta_ad_library_ad_url_with_context("123", market="CO", keyword="One4vice")
    assert "id=123" in url
    assert "q=One4vice" in url
    assert "country=CO" in url


def test_meta_ad_library_ad_url_with_context_falls_back_without_market_or_keyword():
    url = meta_ad_library_ad_url_with_context("123", market=None, keyword="One4vice")
    assert url == "https://www.facebook.com/ads/library/?id=123"
    url2 = meta_ad_library_ad_url_with_context("123", market="CO", keyword=None)
    assert url2 == "https://www.facebook.com/ads/library/?id=123"


def test_meta_ad_library_store_search_url_has_no_id_param():
    url = meta_ad_library_store_search_url("ICON", "ES")
    assert "id=" not in url
    assert "q=ICON" in url
    assert "country=ES" in url

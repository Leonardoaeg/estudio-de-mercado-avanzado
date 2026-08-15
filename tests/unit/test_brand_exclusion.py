from eci.classifiers.brand_exclusion import is_excluded_brand, is_excluded_domain


def test_excludes_known_marketplace():
    excluded, reason = is_excluded_brand("Mercado Libre Colombia")
    assert excluded is True
    assert reason == "marketplace"


def test_excludes_shein_case_insensitive():
    excluded, reason = is_excluded_brand("shein curve")
    assert excluded is True
    assert reason in ("marketplace", "mega_brand")


def test_does_not_exclude_small_store():
    excluded, reason = is_excluded_brand("Enterizo Dama Store 2")
    assert excluded is False
    assert reason is None


def test_handles_none_and_empty():
    assert is_excluded_brand(None) == (False, None)
    assert is_excluded_brand("") == (False, None)


def test_substring_match_within_longer_page_name():
    excluded, reason = is_excluded_brand("SHEIN Colombia Oficial")
    assert excluded is True


def test_excludes_shared_platform_domain():
    excluded, reason = is_excluded_domain("https://pideelo.co/products/x")
    assert excluded is True
    assert reason == "shared_platform"


def test_excludes_marketplace_domain():
    excluded, reason = is_excluded_domain("https://costco.com.mx/producto/x")
    assert excluded is True
    assert reason == "marketplace_domain"


def test_does_not_exclude_independent_domain():
    excluded, reason = is_excluded_domain("https://mitiendaindependiente.com/products/x")
    assert excluded is False
    assert reason is None


def test_is_excluded_domain_handles_none():
    assert is_excluded_domain(None) == (False, None)

"""Tests for the product viability / competitor analysis module."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eci.analysis.product_viability import analyze_product, extract_prices
from eci.database.models import Ad, Advertiser, Base


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = SessionLocal()
    yield s
    s.close()


def _advertiser(session, page_id, page_name, *, active_ad_count=5, subniche=None, country="CO", niche="TEXTIL", store_url=None):
    adv = Advertiser(
        page_id=page_id, page_name=page_name, niche=niche, subniche=subniche, country=country,
        active_ad_count=active_ad_count, store_url=store_url or f"https://{page_id}.com",
        ecommerce_score=85.0, shopify_detected=True, scale_signal_score=70.0, confidence_score=60.0,
        last_verified_at=datetime.now(timezone.utc),
    )
    session.add(adv)
    session.flush()
    return adv


def _ad(session, page_id, ad_id, *, primary_text="Oferta especial"):
    ad = Ad(ad_id=ad_id, source_name="meta_web_scraper", page_id=page_id, page_name=page_id, active=True,
            age_days=10, format="image", primary_text=primary_text)
    session.add(ad)
    session.flush()
    return ad


class TestExtractPrices:
    def test_extracts_dollar_amount_with_thousands_comma(self):
        assert extract_prices("Oferta especial $1,490 MXN hoy") == [1490.0]

    def test_extracts_multiple_prices(self):
        prices = extract_prices("$2,490 hoy ($4,200 antes)")
        assert prices == [2490.0, 4200.0]

    def test_ignores_percentages(self):
        assert extract_prices("50% de descuento en todo") == []

    def test_handles_decimal_cents(self):
        assert extract_prices("Solo $45.50 USD") == [45.5]

    def test_returns_empty_for_no_text(self):
        assert extract_prices(None) == []
        assert extract_prices("") == []

    def test_ignores_implausibly_large_numbers(self):
        # a phone number or id shouldn't be mistaken for a price
        assert extract_prices("$12,345,678,901 contacto") == []

    def test_parses_thousands_without_separators(self):
        assert extract_prices("Precio $100000 COP") == [100000.0]


class TestAnalyzeProduct:
    def test_no_data_available_flags_warning(self, session):
        result = analyze_product("TEXTIL", ["CO"], session, product_description="chaqueta impermeable")
        assert result.data_available is False
        assert result.total_competitors == 0
        assert any("corré" in w for w in result.warnings)

    def test_counts_competitors_and_scale_tiers(self, session):
        _advertiser(session, "p1", "Store A", active_ad_count=60)  # alta
        _advertiser(session, "p2", "Store B", active_ad_count=20)  # media
        _advertiser(session, "p3", "Store C", active_ad_count=5)  # emergente
        session.commit()

        result = analyze_product("TEXTIL", ["CO"], session, product_description="vestido casual")
        assert result.total_competitors == 3
        assert result.scale_alta_count == 1
        assert result.scale_media_count == 1
        assert result.scale_emergente_count == 1
        assert result.data_available is True

    def test_flags_mega_brand_competitors_separately(self, session):
        _advertiser(session, "p1", "Mercado Libre Colombia", active_ad_count=200)
        _advertiser(session, "p2", "Tienda Independiente", active_ad_count=10)
        session.commit()

        result = analyze_product("TEXTIL", ["CO"], session, product_description="jeans")
        assert result.total_competitors == 2
        assert result.mega_brand_competitors == 1

    def test_extracts_market_price_range_from_competitor_ads(self, session):
        _advertiser(session, "p1", "Store A", active_ad_count=10)
        _ad(session, "p1", "a1", primary_text="Chaqueta impermeable $80,000 COP")
        _ad(session, "p1", "a2", primary_text="Oferta especial $120,000 COP antes $150,000")
        session.commit()

        result = analyze_product("TEXTIL", ["CO"], session, product_description="chaqueta impermeable")
        assert result.market_price_min == 80000.0
        assert result.market_price_max == 150000.0
        assert result.market_price_median is not None

    def test_drops_outlier_prices_far_from_the_rest_of_the_sample(self, session):
        """Regression test: a real live run found a stray "$10" (not a real price — some
        other number in the copy) sitting next to a $74,900 median, visibly wrong. Anything
        more than 50x below/above the rest of the sample must be filtered out."""
        _advertiser(session, "p1", "Store A", active_ad_count=10)
        _ad(session, "p1", "a1", primary_text="Chaqueta $74,900 COP")
        _ad(session, "p1", "a2", primary_text="Chaqueta $80,000 COP")
        _ad(session, "p1", "a3", primary_text="Chaqueta $70,000 COP")
        _ad(session, "p1", "a4", primary_text="Descuento adicional de $10 en tu compra")
        session.commit()

        result = analyze_product("TEXTIL", ["CO"], session, product_description="chaqueta")
        assert result.market_price_min == 70000.0
        assert any("descartaron" in w for w in result.warnings)

    def test_price_position_cheaper_than_market(self, session):
        _advertiser(session, "p1", "Store A", active_ad_count=10)
        for i in range(4):
            _ad(session, "p1", f"a{i}", primary_text=f"Precio ${100000 + i * 10000} COP")
        session.commit()

        result = analyze_product(
            "TEXTIL", ["CO"], session, product_description="producto",
            target_price=50000.0,
        )
        assert result.price_position == "más barato que la mayoría del mercado"

    def test_margin_calculation_and_low_margin_warning(self, session):
        result = analyze_product(
            "TEXTIL", ["CO"], session, product_description="producto",
            cost_price=90.0, target_price=100.0,
        )
        assert result.margin_pct == 10.0
        assert "bajo" in result.margin_label

    def test_healthy_margin_label(self, session):
        result = analyze_product(
            "TEXTIL", ["CO"], session, product_description="producto",
            cost_price=40.0, target_price=100.0,
        )
        assert result.margin_pct == 60.0
        assert result.margin_label == "margen saludable"

    def test_low_saturation_and_healthy_margin_is_high_viability(self, session):
        _advertiser(session, "p1", "Store A", active_ad_count=3)
        session.commit()
        result = analyze_product(
            "TEXTIL", ["CO"], session, product_description="producto nuevo",
            cost_price=40.0, target_price=100.0,
        )
        assert result.saturation_level == "BAJA"
        assert result.viability_label == "Alta viabilidad"

    def test_high_saturation_and_bad_margin_is_low_viability(self, session):
        for i in range(20):
            _advertiser(session, f"p{i}", f"Store {i}", active_ad_count=60)
        session.commit()
        result = analyze_product(
            "TEXTIL", ["CO"], session, product_description="producto saturado",
            cost_price=95.0, target_price=100.0,
        )
        assert result.saturation_level == "ALTA"
        assert result.viability_label == "Baja viabilidad"

    def test_subniche_classification_used_to_filter_competitors(self, session):
        _advertiser(session, "p1", "Vestidos Store", active_ad_count=10, subniche="vestidos")
        _advertiser(session, "p2", "Jeans Store", active_ad_count=10, subniche="jeans")
        session.commit()

        result = analyze_product("TEXTIL", ["CO"], session, product_description="quiero vender vestidos de fiesta")
        assert result.subniche == "vestidos"
        assert result.total_competitors == 1
        assert result.top_competitors[0].page_name == "Vestidos Store"

    def test_falls_back_to_whole_niche_when_subniche_pocket_is_empty(self, session):
        _advertiser(session, "p1", "Jeans Store", active_ad_count=10, subniche="jeans")
        session.commit()

        result = analyze_product("TEXTIL", ["CO"], session, product_description="quiero vender vestidos de fiesta")
        assert result.subniche == "vestidos"
        assert result.total_competitors == 1  # fell back to the whole niche
        assert any("se amplió la búsqueda" in w for w in result.warnings)

"""Tests for the "Biblioteca de Referentes" builder — isolated in-memory DB, no network."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eci.database.models import Ad, Advertiser, Base
from eci.reports import library as library_module


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(library_module, "LIBRARY_DIR", tmp_path)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = SessionLocal()
    yield s
    s.close()


def _advertiser(session, page_id, page_name, *, ecommerce_score=85.0, subniche=None, country="CO", niche="TEXTIL"):
    adv = Advertiser(
        page_id=page_id, page_name=page_name, niche=niche, subniche=subniche, country=country,
        active_ad_count=5, store_url=f"https://{page_id}.com/product", ecommerce_score=ecommerce_score,
        shopify_detected=True, scale_signal_score=70.0, confidence_score=60.0,
        oldest_active_ad_age_days=94, last_verified_at=datetime.now(timezone.utc),
    )
    session.add(adv)
    session.flush()
    return adv


def _ad(session, page_id, ad_id, age_days, *, hook_type="offer", angle="ahorro", offer="percentage_discount", format="image", claims_risk_flags=None, primary_text="Oferta especial de referencia"):
    ad = Ad(
        ad_id=ad_id, source_name="meta_web_scraper", page_id=page_id, page_name=page_id, active=True,
        age_days=age_days, format=format, hook_type=hook_type, creative_angle=angle, offer_type=offer,
        primary_text=primary_text, claims_risk_flags=claims_risk_flags or [],
        ad_library_url=f"https://www.facebook.com/ads/library/?id={ad_id}",
    )
    session.add(ad)
    session.flush()
    return ad


def test_only_brands_with_30plus_day_ad_are_included(session):
    _advertiser(session, "p1", "Tienda Nueva")
    _ad(session, "p1", "a1", age_days=5)  # too new — shouldn't qualify

    _advertiser(session, "p2", "Tienda Establecida")
    _ad(session, "p2", "a2", age_days=45)  # qualifies
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "Tienda Establecida" in html
    assert "Tienda Nueva" not in html


def test_excludes_known_mega_brands(session):
    _advertiser(session, "p1", "SHEIN Colombia")
    _ad(session, "p1", "a1", age_days=60)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    # "SHEIN" legitimately appears in the page's own explanatory criteria text ("nunca
    # SHEIN, Temu, ...") — the real assertion is that it never gets its own card.
    assert "<h3>SHEIN Colombia</h3>" not in html
    assert "sin marcas que cumplan el criterio" in html.lower()  # zero qualifying brands


def test_deduplicates_same_store_across_markets(session):
    adv_co = _advertiser(session, "p1co", "Misma Tienda", country="CO")
    adv_co.store_url = "https://mismatienda.com/product-a"
    _ad(session, "p1co", "a1", age_days=40)

    adv_mx = _advertiser(session, "p1mx", "Misma Tienda", country="MX")
    adv_mx.store_url = "https://mismatienda.com/product-b"
    _ad(session, "p1mx", "a2", age_days=50)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO", "MX"], session)
    html = path.read_text(encoding="utf-8")
    assert html.count("Misma Tienda") == 1


def test_dedup_keeps_the_highest_volume_account_for_a_domain(session):
    """Regression test: a live run found the same store (icon-amsterdam.com) posting both
    as its main brand Page (42 ads) and as ~10 separate 1-ad creator/influencer collab
    Pages. Dedup must keep the real brand account, not whichever row happens to be
    inserted first."""
    creator = _advertiser(session, "creator1", "Some Creator con ICON")
    creator.store_url = "https://icon-amsterdam.com/products/x"
    creator.active_ad_count = 1
    _ad(session, "creator1", "c1", age_days=35)

    main = _advertiser(session, "iconmain", "ICON")
    main.store_url = "https://icon-amsterdam.com/collections/best-selling"
    main.active_ad_count = 42
    _ad(session, "iconmain", "m1", age_days=52)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert html.count("<h3>ICON</h3>") + html.count("<h3>Some Creator con ICON</h3>") == 1
    assert "42 anuncios activos" in html


def test_low_ecommerce_score_excluded(session):
    _advertiser(session, "p1", "Tienda Dudosa", ecommerce_score=40.0)
    _ad(session, "p1", "a1", age_days=60)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session, min_ecommerce_score=70.0)
    html = path.read_text(encoding="utf-8")
    assert "Tienda Dudosa" not in html


def test_groups_by_subniche(session):
    _advertiser(session, "p1", "Jean Store", subniche="jeans")
    _ad(session, "p1", "a1", age_days=40)
    _advertiser(session, "p2", "Vestido Store", subniche="vestidos")
    _ad(session, "p2", "a2", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "jeans" in html
    assert "vestidos" in html


def test_filters_off_topic_service_businesses(session):
    """Regression test: a live run surfaced "Dogs4motion Academy" (a dog-agility training
    course, not apparel) via a keyword-search false positive. Service/course businesses
    should never get a card even if they score as ecommerce and have a 30+ day ad."""
    _advertiser(session, "p1", "Dogs4motion Academy for active dogs")
    _ad(session, "p1", "a1", age_days=60)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Dogs4motion" not in html


def test_creative_notes_merged_by_domain(session, monkeypatch, tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "TEXTIL.yaml").write_text(
        "misatienda.com:\n  video: \"Modelo hablando a cámara, sin música de fondo.\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(library_module, "CREATIVE_NOTES_DIR", notes_dir)

    adv = _advertiser(session, "p1", "Mi Tienda")
    adv.store_url = "https://misatienda.com/product"
    _ad(session, "p1", "a1", age_days=40, format="video")
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Modelo hablando a c" in html


def test_missing_creative_notes_file_is_not_an_error(session):
    path = library_module.build_library("SALUD", ["CO"], session)  # no SALUD.yaml exists
    assert path.exists()


def test_caps_to_top_n_and_force_includes_requested_brands(session):
    for i in range(15):
        _advertiser(session, f"p{i}", f"Store {i}")
        s = session.query(Advertiser).filter_by(page_id=f"p{i}").one()
        s.active_ad_count = 20 - i  # descending, so p14 has the fewest ads
        _ad(session, f"p{i}", f"a{i}", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session, top_n=10, must_include_domains=["p14.com"])
    html = path.read_text(encoding="utf-8")
    brand_cards = [f"<h3>Store {i}</h3>" for i in range(15) if f"<h3>Store {i}</h3>" in html]
    assert len(brand_cards) == 11  # 10 natural top + 1 forced (p14 wasn't in the natural top 10)
    assert "Store 14" in html  # the force-included, low-volume brand made it in
    assert "Store 10" not in html  # p10 ranked #11 naturally and wasn't forced — excluded


def test_excludes_multi_vendor_affiliate_pages(session):
    """Regression test: a live run found "NexaMarket" running the exact same ad copy
    landing on 3 unrelated domains (bedsheet, vitamin-B store, multivitamin store) — an
    affiliate/media-buyer, not a store of its own."""
    _advertiser(session, "p1", "NexaMarket")
    a1 = _ad(session, "p1", "a1", age_days=40)
    a1.landing_url = "https://storea.com/x"
    a2 = _ad(session, "p1", "a2", age_days=41)
    a2.landing_url = "https://storeb.com/y"
    a3 = _ad(session, "p1", "a3", age_days=42)
    a3.landing_url = "https://storec.com/z"
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "NexaMarket" not in html


def test_dominant_domain_survives_a_few_stray_misaligned_links(session):
    """Regression test: a live run found ICON Amsterdam's real 42-ad page wrongly excluded
    over just 4 of 38 ads whose landing_url pointed at a hotel site / an accessories store /
    an AI tool — none related to ICON, all clearly the scraper's positional href-pairing
    grabbing a NEIGHBORING ad's link, not a second business. One dominant domain (34/38)
    must survive even though 3 distinct stray domains show up."""
    _advertiser(session, "p1", "ICON Amsterdam")
    for i in range(34):
        a = _ad(session, "p1", f"a{i}", age_days=40 + i)
        a.landing_url = "https://icon-amsterdam.com/collections/best-selling"
    stray_domains = ["https://www.leonardo-hotels.com/x", "https://alcanside.com/y", "https://www.arcads.ai/"]
    for i, url in enumerate(stray_domains):
        a = _ad(session, "p1", f"stray{i}", age_days=10)
        a.landing_url = url
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "ICON Amsterdam" in html


def test_single_vendor_with_multiple_ads_still_included(session):
    _advertiser(session, "p1", "Tienda Legit")
    a1 = _ad(session, "p1", "a1", age_days=40)
    a1.landing_url = "https://tiendalegit.com/product-a"
    a2 = _ad(session, "p1", "a2", age_days=41)
    a2.landing_url = "https://tiendalegit.com/product-b"
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Tienda Legit" in html


def test_whatsapp_cta_link_does_not_trigger_multi_vendor_exclusion(session):
    """Regression test: a live run wrongly excluded "Madelic" (dulcehogar55.myshopify.com,
    4 real active ads) because one ad's landing_url was a WhatsApp CTA link
    (api.whatsapp.com) rather than the product page — that's a normal contact button, not
    a second unrelated business, and must not count as a distinct "store domain"."""
    _advertiser(session, "p1", "Madelic")
    a1 = _ad(session, "p1", "a1", age_days=40)
    a1.landing_url = "https://dulcehogar55.myshopify.com/products/pantys"
    a2 = _ad(session, "p1", "a2", age_days=41)
    a2.landing_url = "https://api.whatsapp.com/send?phone=573001234567"
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Madelic" in html


def test_link_shortener_domains_never_collide_across_unrelated_brands(session):
    """Regression test: a live run found 3 unrelated advertisers all using bit.ly as their
    store_url (a generic link shortener) — domain-based dedup was silently collapsing them
    into a single card since "bit.ly" looked like a shared domain."""
    a = _advertiser(session, "p1", "Brand A")
    a.store_url = "https://bit.ly/aaa111"
    _ad(session, "p1", "a1", age_days=40)

    b = _advertiser(session, "p2", "Brand B")
    b.store_url = "https://bit.ly/bbb222"
    _ad(session, "p2", "a2", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Brand A" in html
    assert "Brand B" in html


def test_excludes_shared_dropshipping_platform_domain(session):
    adv = _advertiser(session, "p1", "Seller A")
    adv.store_url = "https://pideelo.co/products/x"
    _ad(session, "p1", "a1", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Seller A" not in html


def test_excludes_shared_dropshipping_platform_kilayu(session):
    """Regression test: a live run found SIX different page_names (Kilayu, Floralshe,
    CurveShe, Elmejorr shop, Ohcomfy, Coraçao) all pointing at the identical product URL
    kilayu.com/products/tsb — a shared storefront platform, not one real brand."""
    adv = _advertiser(session, "p1", "Ohcomfy")
    adv.store_url = "https://kilayu.com/products/tsb"
    _ad(session, "p1", "a1", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Ohcomfy" not in html


def test_format_statistics_computed_across_curated_brands(session):
    _advertiser(session, "p1", "Video Store")
    _ad(session, "p1", "a1", age_days=40, format="video")
    _ad(session, "p1", "a2", age_days=35, format="video")
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Video · 100.0%" in html


def test_claims_risk_banner_and_badge_shown_for_salud(session):
    _advertiser(session, "p1", "Salud Store", niche="SALUD")
    _ad(session, "p1", "a1", age_days=40, claims_risk_flags=["cura_enfermedad"], primary_text="Esto cura la diabetes")
    session.commit()

    path = library_module.build_library("SALUD", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "claims de salud" in html.lower()
    assert "cura_enfermedad" in html
    assert "no recomendado copiar" in html.lower()


def test_no_claims_banner_for_non_sensitive_niche(session):
    _advertiser(session, "p1", "Textil Store", niche="TEXTIL")
    _ad(session, "p1", "a1", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "claims de salud" not in html.lower()


def test_empty_result_renders_placeholder_not_error(session):
    path = library_module.build_library("TEXTIL", ["CO"], session)
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "sin marcas que cumplan el criterio" in html.lower()


def test_all_active_ads_are_listed_not_capped_at_three(session):
    """Operator (2026-08-14): "debes de colocar todos los anuncios activos que tenga la
    tienda... el limite solo es al evaluar los creativos en cuanto videos" — the 30+-day
    `long_running_ads` reference set stays capped at 3 (that's the manual-video-review
    budget), but the store's real, full active-ad inventory must never be truncated."""
    _advertiser(session, "p1", "Tienda Escalando", ecommerce_score=85.0)
    _ad(session, "p1", "ref", age_days=40)  # clears the 30+ day bar
    for i in range(24):
        _ad(session, "p1", f"a{i}", age_days=5 + i)  # 24 more active ads, mostly <30 days
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    json_path = path.with_suffix(".json")

    assert "Todos los anuncios activos (25)" in html

    import json

    data = json.loads(json_path.read_text(encoding="utf-8"))
    brand = data["brands"][0]
    assert brand["all_active_ads_count"] == 25
    assert len(brand["all_active_ads"]) == 25
    # the 30+ day reference set is a separate, still-capped subset
    assert len(brand["long_running_ads"]) == 1


def test_detail_panel_shows_dominant_pattern_and_format_breakdown(session):
    """The 'Más detalle' panel is a Level-Up-Suite-style expandable drawer — must surface
    the advertiser's dominant hook/angle/offer and per-format ad counts, all sourced from
    fields the pipeline already computes (metrics/scoring.py), not invented for the panel."""
    adv = _advertiser(session, "p1", "Tienda Detallada")
    adv.dominant_hook = "curiosidad"
    adv.dominant_angle = "ahorro"
    adv.dominant_offer = "envio_gratis"
    adv.video_count = 4
    adv.image_count = 1
    adv.carousel_count = 0
    session.add(adv)
    _ad(session, "p1", "a1", age_days=40)
    session.commit()

    path = library_module.build_library("TEXTIL", ["CO"], session)
    html = path.read_text(encoding="utf-8")
    assert "Más detalle" in html
    assert "curiosidad" in html
    assert "ahorro" in html
    assert "envio_gratis" in html
    assert "4 video" in html
    assert "1 imagen" in html


def test_json_export_written_alongside_html(session):
    """The curated biblioteca is also meant to be consumed by an application, not just
    browsed — every build must produce a machine-readable JSON twin next to the HTML."""
    import json

    _advertiser(session, "p1", "Tienda Establecida", subniche="vestidos")
    _ad(session, "p1", "a1", age_days=45, format="video", hook_type="curiosidad")
    session.commit()

    html_path = library_module.build_library("TEXTIL", ["CO"], session)
    json_path = html_path.with_suffix(".json")
    assert json_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["niche"] == "TEXTIL"
    assert data["total_brands"] == 1
    assert data["brands"][0]["page_name"] == "Tienda Establecida"
    assert "page_id" in data["brands"][0]
    assert not any(k.startswith("_") for k in data["brands"][0])
    assert data["brands"][0]["long_running_ads"][0]["hook_type"] == "curiosidad"
    assert "format_stats" in data and "format_percentages" in data

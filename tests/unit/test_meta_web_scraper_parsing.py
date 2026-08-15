"""Tests for the pure text-parsing logic in meta_web_scraper.py — no Playwright/network
involved. The Spanish fixture is trimmed real text captured from a live Meta Ad Library
session (browsed from Colombia) on 2026-08-14; see IMPLEMENTATION_PLAN.md.
"""

from pathlib import Path

from eci.sources.meta_web_scraper import decode_landing_url, parse_ad_library_text

FIXTURES = Path(__file__).parent.parent / "fixtures"

_ENGLISH_SAMPLE = """
Active
Library ID: 9988776655
Started running on Jul 6, 2026
Platforms
This ad has multiple versions
Open Drop-down
See ad details
Acme Store
Sponsored
Best deals of the week, shop now and save big
ACMESTORE.COM
Acme Wireless Headphones Noise Cancelling
Learn More
"""


def test_parses_spanish_ad_library_page():
    text = (FIXTURES / "meta_ad_library_sample_es.txt").read_text(encoding="utf-8")
    ads = parse_ad_library_text(text)
    assert len(ads) == 3

    shein = next(a for a in ads if a["ad_id"] == "2160719207835594")
    assert shein["page_name"] == "SHEIN"
    assert shein["active"] is True
    assert shein["start_date_raw"] == "6 jul 2026"
    assert shein["domain"] == "M.SHEIN.COM.CO"
    assert "Vestido Midi" in shein["headline"]
    assert shein["cta"] == "Shop Now"

    mercadolibre = next(a for a in ads if a["ad_id"] == "1536777887804604")
    assert mercadolibre["page_name"] == "Mercado Libre"
    assert mercadolibre["domain"] == "MERCADOLIBRE.COM.CO"
    # multi-line primary text before the domain line should be joined, not truncated
    assert "Encuéntralo" in mercadolibre["primary_text"]
    assert "Devolvemos" in mercadolibre["primary_text"]

    faja = next(a for a in ads if a["ad_id"] == "962468780003491")
    assert faja["page_name"] == "Faja Colombiana Store"
    assert faja["domain"] == "FAJACOLOMBIANASTORE.COM"


def test_parses_english_ad_library_page():
    ads = parse_ad_library_text(_ENGLISH_SAMPLE)
    assert len(ads) == 1
    ad = ads[0]
    assert ad["ad_id"] == "9988776655"
    assert ad["page_name"] == "Acme Store"
    assert ad["domain"] == "ACMESTORE.COM"
    assert ad["start_date_raw"] == "Jul 6, 2026"
    assert ad["cta"] == "Learn More"


def test_ignores_non_ad_boilerplate_text():
    text = "Biblioteca de anuncios\n~22.000 resultados\nFiltros\nOrdenar\n"
    assert parse_ad_library_text(text) == []


def test_empty_text_returns_empty_list():
    assert parse_ad_library_text("") == []


def test_missing_domain_keeps_everything_as_primary_text_without_guessing():
    text = "Activo\nIdentificador de la biblioteca: 111\nEn circulación desde el 1 ene 2026\nMi Tienda\nPublicidad\nUn texto cualquiera sin dominio reconocible\n"
    ads = parse_ad_library_text(text)
    assert len(ads) == 1
    assert ads[0]["domain"] is None
    assert ads[0]["headline"] is None
    assert "Un texto cualquiera" in ads[0]["primary_text"]


def test_detects_video_format_via_duration_scrubber():
    text = (
        "Activo\n"
        "Identificador de la biblioteca: 900858399742587\n"
        "En circulación desde el 21 jun 2026\n"
        "Plataformas\n"
        "Ver detalles del anuncio\n"
        "One4Vice Punto Fabrica\n"
        "Publicidad\n"
        "COMODIDAD EN CADA DIA Boxers sin costuras\n"
        "0:00 / 0:18\n"
    )
    ads = parse_ad_library_text(text)
    assert len(ads) == 1
    assert ads[0]["format_hint"] == "video"
    assert "0:00" not in (ads[0]["primary_text"] or "")


def test_no_duration_scrubber_means_no_format_hint():
    text = (
        "Activo\nIdentificador de la biblioteca: 111\nEn circulación desde el 1 ene 2026\n"
        "Mi Tienda\nPublicidad\nUn texto cualquiera\nMITIENDA.CO\nProducto\nComprar\n"
    )
    ads = parse_ad_library_text(text)
    assert ads[0]["format_hint"] is None


def test_decode_landing_url_from_facebook_link_shim():
    href = "https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.example.com%2Fproducts%2Fx%3Fref%3Dad&h=xyz"
    assert decode_landing_url(href) == "https://www.example.com/products/x?ref=ad"


def test_decode_landing_url_malformed_returns_none():
    assert decode_landing_url("not a url") is None
    assert decode_landing_url("https://l.facebook.com/l.php?h=xyz") is None


def test_unfamiliar_disclaimer_lines_do_not_get_mistaken_for_page_name():
    """Regression test: a live run against the real Ad Library showed cards with disclaimer
    lines we hadn't seen before ("3 anuncios usan este contenido y texto", "Número de
    impresiones bajo", "Transparencia de la UE" on EU-targeted ads) landing in `page_name`
    instead of the real advertiser. The fix anchors on "Publicidad"/"Sponsored" instead of
    an exhaustive boilerplate list, so any number of unfamiliar disclaimer lines before it
    should be skipped correctly."""
    text = (
        "Activo\n"
        "Identificador de la biblioteca: 555\n"
        "En circulación desde el 1 ene 2026\n"
        "Plataformas\n"
        "3 anuncios usan este contenido y texto\n"
        "Número de impresiones bajo\n"
        "Transparencia de la UE\n"
        "Abrir menú desplegable\n"
        "Ver detalles del anuncio\n"
        "ZASHA JEANS\n"
        "Publicidad\n"
        "Jeans colombianos de alta calidad\n"
        "DOLCE-FASHION.CO\n"
        "Jean levanta cola premium\n"
        "Shop Now\n"
    )
    ads = parse_ad_library_text(text)
    assert len(ads) == 1
    assert ads[0]["page_name"] == "ZASHA JEANS"
    assert ads[0]["domain"] == "DOLCE-FASHION.CO"

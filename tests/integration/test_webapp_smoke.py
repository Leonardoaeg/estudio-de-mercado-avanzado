"""Smoke tests for the live ECI Suite dashboard (src/eci/webapp/app.py). Runs against the
REAL project database (same one every other CLI command uses) — the point is to verify
the actual running app against actual data ("100% funcional sin errores"), not a synthetic
fixture. Marked `live` since it depends on the project's real data.db existing.
"""

import pytest
from fastapi.testclient import TestClient

from eci.webapp.app import app

pytestmark = pytest.mark.live

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dashboard_loads():
    r = client.get("/")
    assert r.status_code == 200
    assert "Panel de Mercado" in r.text
    assert "Analizar producto" in r.text


def test_niche_view_loads_for_known_niche():
    r = client.get("/nicho/TEXTIL")
    assert r.status_code == 200
    assert "Biblioteca de Referentes" in r.text
    assert "Textil" in r.text


def test_niche_view_404_for_unknown_niche():
    r = client.get("/nicho/NOEXISTE")
    assert r.status_code == 404


def test_product_form_loads():
    r = client.get("/producto")
    assert r.status_code == 200
    assert "<form" in r.text
    assert 'name="product"' in r.text


def test_product_analyze_post_returns_verdict():
    r = client.post(
        "/producto",
        data={
            "niche": "TEXTIL",
            "product": "chaqueta rompevientos unisex, tela impermeable",
            "market": ["CO"],
            "cost_price": "35000",
            "target_price": "89000",
            "currency": "COP",
        },
    )
    assert r.status_code == 200
    assert "Análisis de Producto" in r.text
    assert "Viable" in r.text or "viabilidad" in r.text.lower()


def test_product_analyze_post_rejects_non_numeric_price():
    r = client.post(
        "/producto",
        data={
            "niche": "TEXTIL",
            "product": "producto de prueba",
            "market": ["CO"],
            "cost_price": "no-es-un-numero",
            "target_price": "",
            "currency": "",
        },
    )
    assert r.status_code == 200
    assert "número" in r.text.lower()


def test_product_analyze_post_rejects_empty_description():
    r = client.post(
        "/producto",
        data={"niche": "TEXTIL", "product": "   ", "market": ["CO"], "cost_price": "", "target_price": "", "currency": ""},
    )
    assert r.status_code == 200
    assert "describ" in r.text.lower()

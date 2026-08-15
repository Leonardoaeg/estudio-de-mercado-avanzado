"""Tests for the HTML/JSON rendering of the product viability analysis."""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eci.database.models import Advertiser, Base
from eci.reports import product_report


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(product_report, "PRODUCT_REPORTS_DIR", tmp_path)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = SessionLocal()
    yield s
    s.close()


def _advertiser(session, page_id, page_name, *, active_ad_count=5, country="CO", niche="TEXTIL"):
    adv = Advertiser(
        page_id=page_id, page_name=page_name, niche=niche, country=country,
        active_ad_count=active_ad_count, store_url=f"https://{page_id}.com",
        ecommerce_score=85.0, shopify_detected=True, scale_signal_score=70.0, confidence_score=60.0,
        last_verified_at=datetime.now(timezone.utc),
    )
    session.add(adv)
    session.flush()
    return adv


def test_build_product_report_writes_html_and_json(session):
    _advertiser(session, "p1", "Competitor A", active_ad_count=12)
    session.commit()

    path = product_report.build_product_report(
        "TEXTIL", ["CO"], session,
        product_description="chaqueta impermeable unisex",
        cost_price=35000.0, target_price=89000.0, currency_note="Precios en COP",
    )
    assert path.exists()
    assert path.suffix == ".html"
    html = path.read_text(encoding="utf-8")
    assert "chaqueta impermeable unisex" in html
    assert "Competitor A" in html
    assert "Precios en COP" in html

    json_path = path.with_suffix(".json")
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total_competitors"] == 1
    assert data["competitors"][0]["page_name"] == "Competitor A"
    assert "top_competitors" not in data


def test_filename_is_slugified_and_scoped_to_niche(session):
    path = product_report.build_product_report(
        "SALUD", ["CO"], session,
        product_description="¡Faja Reductora Premium! 100% Algodón",
    )
    assert path.name.startswith("SALUD_")
    assert " " not in path.name
    assert "!" not in path.name

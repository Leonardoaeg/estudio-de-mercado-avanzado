"""Dedup/UPSERT tests — section 30: running the pipeline repeatedly must never duplicate
rows. Uses an isolated in-memory SQLite engine/session, independent of the app's cached
singleton in database/engine.py, so tests never touch data/eci.db.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from eci.database.models import Base
from eci.database.repository import upsert_ad, upsert_advertiser, upsert_store


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = SessionLocal()
    yield s
    s.close()


def _advertiser(page_id="p1", active_ad_count=10):
    return {
        "page_id": page_id,
        "page_name": "Store A",
        "niche": "TEXTIL",
        "country": "CO",
        "active_ad_count": active_ad_count,
        "last_verified_at": datetime.now(timezone.utc),
    }


def _ad(ad_id="a1", source_name="mock", page_id="p1"):
    return {
        "ad_id": ad_id, "source_name": source_name, "page_id": page_id,
        "page_name": "Store A", "active": True, "format": "video",
    }


def test_upsert_advertiser_does_not_duplicate(session):
    upsert_advertiser(session, _advertiser())
    upsert_advertiser(session, _advertiser(active_ad_count=25))
    session.commit()

    from eci.database.models import Advertiser
    rows = session.query(Advertiser).filter_by(page_id="p1").all()
    assert len(rows) == 1
    assert rows[0].active_ad_count == 25  # second call updates, doesn't insert a duplicate


def test_upsert_ad_dedups_by_ad_id_and_source(session):
    ad1, created1 = upsert_ad(session, _ad())
    ad2, created2 = upsert_ad(session, _ad())
    session.commit()

    from eci.database.models import Ad
    rows = session.query(Ad).filter_by(ad_id="a1", source_name="mock").all()
    assert len(rows) == 1
    assert created1 is True
    assert created2 is False


def test_upsert_ad_same_id_different_source_is_not_deduped(session):
    upsert_ad(session, _ad(source_name="mock"))
    upsert_ad(session, _ad(source_name="meta_graph_api"))
    session.commit()

    from eci.database.models import Ad
    rows = session.query(Ad).filter_by(ad_id="a1").all()
    assert len(rows) == 2


def test_upsert_ad_preserves_first_seen_across_updates(session):
    ad1, _ = upsert_ad(session, _ad())
    session.commit()
    first_seen = ad1.first_seen

    ad2, _ = upsert_ad(session, _ad())
    session.commit()
    assert ad2.first_seen == first_seen
    assert ad2.last_seen >= first_seen


def test_upsert_store_dedups_by_domain(session):
    upsert_store(session, "mystore.com", {"store_url": "https://mystore.com/p1", "advertiser_page_id": "p1", "ecommerce_score": 80.0})
    upsert_store(session, "mystore.com", {"store_url": "https://mystore.com/p2", "advertiser_page_id": "p1", "ecommerce_score": 85.0})
    session.commit()

    from eci.database.models import Store
    rows = session.query(Store).filter_by(domain="mystore.com").all()
    assert len(rows) == 1
    assert rows[0].ecommerce_score == 85.0


def test_repeated_pipeline_run_is_idempotent(session):
    """Simulates running the same collection twice: no duplicate ads or advertisers."""
    for _ in range(3):
        upsert_advertiser(session, _advertiser())
        upsert_ad(session, _ad(ad_id="a1"))
        upsert_ad(session, _ad(ad_id="a2"))
        session.commit()

    from eci.database.models import Ad, Advertiser
    assert session.query(Advertiser).count() == 1
    assert session.query(Ad).count() == 2

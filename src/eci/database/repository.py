"""Repository layer: UPSERT/dedup helpers so running the pipeline repeatedly never
duplicates rows — section 30. Uses SQLAlchemy's `Session.merge`-free pattern (explicit
get-then-update) so the dedup key is always obvious and testable, rather than relying on
opaque ON CONFLICT clauses that vary between SQLite and Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from eci.database.models import (
    Ad,
    Advertiser,
    CreativeFamily,
    ErrorRecord,
    KeywordRecord,
    RankingRecord,
    Snapshot,
    Store,
)


def upsert_advertiser(session: Session, data: dict) -> Advertiser:
    stmt = select(Advertiser).where(Advertiser.page_id == data["page_id"])
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        obj = Advertiser(**data)
        session.add(obj)
        session.flush()
        return obj
    for key, value in data.items():
        setattr(existing, key, value)
    existing.last_verified_at = datetime.now(timezone.utc)
    session.flush()
    return existing


def upsert_ad(session: Session, data: dict) -> tuple[Ad, bool]:
    """Returns (ad, created). Dedup key: (ad_id, source_name)."""
    stmt = select(Ad).where(Ad.ad_id == data["ad_id"], Ad.source_name == data["source_name"])
    existing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is None:
        data.setdefault("first_seen", now)
        data["last_seen"] = now
        obj = Ad(**data)
        session.add(obj)
        session.flush()
        return obj, True
    for key, value in data.items():
        if key == "first_seen":
            continue  # never overwrite the original first-seen timestamp
        setattr(existing, key, value)
    existing.last_seen = now
    session.flush()
    return existing, False


def upsert_store(session: Session, domain: str, data: dict) -> Store:
    stmt = select(Store).where(Store.domain == domain)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        obj = Store(domain=domain, **data)
        session.add(obj)
        session.flush()
        return obj
    for key, value in data.items():
        setattr(existing, key, value)
    existing.last_verified_at = datetime.now(timezone.utc)
    session.flush()
    return existing


def upsert_creative_family(session: Session, family_key: str, data: dict) -> CreativeFamily:
    stmt = select(CreativeFamily).where(CreativeFamily.family_key == family_key)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        obj = CreativeFamily(family_key=family_key, **data)
        session.add(obj)
        session.flush()
        return obj
    for key, value in data.items():
        setattr(existing, key, value)
    session.flush()
    return existing


def upsert_keyword(session: Session, keyword: str, niche: str, market: str, data: dict) -> KeywordRecord:
    stmt = select(KeywordRecord).where(
        KeywordRecord.keyword == keyword,
        KeywordRecord.niche == niche,
        KeywordRecord.market == market,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        return existing
    obj = KeywordRecord(keyword=keyword, niche=niche, market=market, **data)
    session.add(obj)
    session.flush()
    return obj


def record_error(session: Session, *, run_uuid: str | None, stage: str, entity_ref: str | None, message: str) -> None:
    session.add(ErrorRecord(run_uuid=run_uuid, stage=stage, entity_ref=entity_ref, message=message))
    session.flush()


def save_snapshot(session: Session, data: dict) -> Snapshot:
    obj = Snapshot(**data)
    session.add(obj)
    session.flush()
    return obj


def replace_rankings(session: Session, niche: str, market: str, ranking_type: str, rows: list[dict]) -> None:
    """Rankings are point-in-time views, not accumulating history, so we clear-and-replace
    rather than upsert-by-key. Historical ranking movement is derivable from snapshots instead."""
    existing = (
        session.query(RankingRecord)
        .filter_by(niche=niche, market=market, ranking_type=ranking_type)
        .all()
    )
    for row in existing:
        session.delete(row)
    session.flush()
    for row in rows:
        session.add(RankingRecord(niche=niche, market=market, ranking_type=ranking_type, **row))
    session.flush()

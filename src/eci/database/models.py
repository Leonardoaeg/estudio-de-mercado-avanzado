"""SQLAlchemy ORM models — section 28 of the spec.

Written against SQLAlchemy 2.0's typed declarative style. Uses plain column types
(String/Integer/Float/Boolean/DateTime/Text) that map identically on SQLite and
PostgreSQL, so switching `database_url` to a Postgres DSN requires no model changes
(the one exception, JSON columns, uses SQLAlchemy's generic `JSON` type which both
backends support).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ResearchRun(Base):
    """One execution of `eci research` — the observability record (section 45)."""

    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(String(64), unique=True)
    market: Mapped[str] = mapped_column(String(8))
    niche: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(32))
    minimum_active_ads: Mapped[int] = mapped_column(Integer, default=50)
    stage: Mapped[str] = mapped_column(String(32), default="PENDING")  # pipeline checkpoint
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0)
    pages_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    ecommerce_verified: Mapped[int] = mapped_column(Integer, default=0)
    stores_over_threshold: Mapped[int] = mapped_column(Integer, default=0)
    ads_collected: Mapped[int] = mapped_column(Integer, default=0)
    videos: Mapped[int] = mapped_column(Integer, default=0)
    images: Mapped[int] = mapped_column(Integer, default=0)
    carousels: Mapped[int] = mapped_column(Integer, default=0)
    unknown_format: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    report_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    database_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceRecord(Base):
    """A data source consulted during a run (meta_graph_api / meta_web_scraper / mock / store_page)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))  # ad_library_api | ad_library_scraper | store_html | mock
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)


class ErrorRecord(Base):
    """Section 45/31: every tolerated error is logged here instead of crashing the run."""

    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[str] = mapped_column(String(32))
    entity_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Advertiser(Base):
    """One Fan Page / advertiser — section 9 field list."""

    __tablename__ = "advertisers"
    __table_args__ = (UniqueConstraint("page_id", name="uq_advertiser_page_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(String(128), index=True)
    page_name: Mapped[str] = mapped_column(String(256))
    fanpage_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    instagram_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country: Mapped[str] = mapped_column(String(8), default="unknown")
    niche: Mapped[str] = mapped_column(String(64))
    subniche: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    active_ad_count: Mapped[int] = mapped_column(Integer, default=0)
    store_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    final_store_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    ecommerce_score: Mapped[float] = mapped_column(Float, default=0.0)
    ecommerce_signals: Mapped[dict] = mapped_column(JSON, default=dict)

    shopify_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    shopify_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    shopify_signals: Mapped[dict] = mapped_column(JSON, default=dict)

    video_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    carousel_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_format_count: Mapped[int] = mapped_column(Integer, default=0)

    oldest_active_ad_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    oldest_active_ad_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    oldest_active_ad_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    median_ad_age: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_ad_age: Mapped[float | None] = mapped_column(Float, nullable=True)
    ads_over_14_days: Mapped[int] = mapped_column(Integer, default=0)
    ads_over_30_days: Mapped[int] = mapped_column(Integer, default=0)
    ads_over_60_days: Mapped[int] = mapped_column(Integer, default=0)
    ads_over_90_days: Mapped[int] = mapped_column(Integer, default=0)
    ads_in_reference_window: Mapped[int] = mapped_column(Integer, default=0)  # 30-90d per operator request
    reference_window_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    dominant_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dominant_hook: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dominant_angle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dominant_offer: Mapped[str | None] = mapped_column(String(64), nullable=True)

    scale_signal_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    new_ads_since_last_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    removed_ads_since_last_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    growth_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    acceleration_score: Mapped[float] = mapped_column(Float, default=0.0)

    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    ads: Mapped[list["Ad"]] = relationship(back_populates="advertiser")


class Store(Base):
    """Deduplicated by canonical domain — section 30."""

    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("domain", name="uq_store_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(256))
    store_url: Mapped[str] = mapped_column(String(512))
    advertiser_page_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ecommerce_score: Mapped[float] = mapped_column(Float, default=0.0)
    shopify_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    landing_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Ad(Base):
    """One individual ad — section 10 field list."""

    __tablename__ = "ads"
    __table_args__ = (UniqueConstraint("ad_id", "source_name", name="uq_ad_id_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_id: Mapped[str] = mapped_column(String(128), index=True)
    source_name: Mapped[str] = mapped_column(String(32))
    page_id: Mapped[str] = mapped_column(String(128), index=True)
    page_name: Mapped[str] = mapped_column(String(256))
    advertiser_id: Mapped[int | None] = mapped_column(ForeignKey("advertisers.id"), nullable=True)

    ad_library_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    format: Mapped[str] = mapped_column(String(16), default="unknown")  # video|image|carousel|unknown
    primary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta: Mapped[str | None] = mapped_column(String(64), nullable=True)

    landing_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    final_landing_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    product: Mapped[str | None] = mapped_column(String(256), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    offer_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    hook: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hook_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creative_angle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creative_style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    visual_description: Mapped[str | None] = mapped_column(String(64), default="not_available")

    ugc_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    testimonial_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    demonstration_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    problem_solution_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comparison_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    creative_family_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    creative_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)

    claims_risk_flags: Mapped[list] = mapped_column(JSON, default=list)

    niche: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subniche: Mapped[str | None] = mapped_column(String(64), nullable=True)

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    advertiser: Mapped["Advertiser | None"] = relationship(back_populates="ads")


class CreativeFamily(Base):
    """A group of near-duplicate ads representing one creative concept — section 17."""

    __tablename__ = "creative_families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    page_id: Mapped[str] = mapped_column(String(128), index=True)
    representative_ad_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    dominant_hook: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dominant_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    structure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CreativeAnalysis(Base):
    """Optional deeper per-ad analysis payload (kept separate from `ads` so v1's text-only
    heuristics and a future vision-based analyzer can both write here without a schema clash).
    """

    __tablename__ = "creative_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_id: Mapped[str] = mapped_column(String(128), index=True)
    analyzer: Mapped[str] = mapped_column(String(32))  # text_heuristic | vision (future)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Snapshot(Base):
    """A point-in-time capture of one advertiser's ad set — section 19."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(String(128), index=True)
    niche: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(8))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    active_ad_count: Mapped[int] = mapped_column(Integer, default=0)
    ad_ids: Mapped[list] = mapped_column(JSON, default=list)
    creative_family_ids: Mapped[list] = mapped_column(JSON, default=list)
    products: Mapped[list] = mapped_column(JSON, default=list)
    scale_signal_score: Mapped[float] = mapped_column(Float, default=0.0)


class KeywordRecord(Base):
    """Discovery engine state — section 7: seeds plus discovered generations."""

    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("keyword", "niche", "market", name="uq_keyword_niche_market"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(256))
    niche: Mapped[str] = mapped_column(String(64))
    subniche: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market: Mapped[str] = mapped_column(String(8))
    generation: Mapped[int] = mapped_column(Integer, default=0)  # 0=seed, 1+=discovered
    discovered_from_page_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TrendRecord(Base):
    """Advertising Trend (not Sales Trend) — section 24."""

    __tablename__ = "trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    niche: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(8))
    dimension: Mapped[str] = mapped_column(String(32))  # product|keyword|subniche|hook|angle|format|offer
    label: Mapped[str] = mapped_column(String(256))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    baseline_count: Mapped[int] = mapped_column(Integer, default=0)
    current_count: Mapped[int] = mapped_column(Integer, default=0)
    variation_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RankingRecord(Base):
    """Persisted ranking rows — section 21 (two rankings per niche)."""

    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    niche: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(8))
    ranking_type: Mapped[str] = mapped_column(String(32))  # presence | acceleration
    rank: Mapped[int] = mapped_column(Integer)
    page_id: Mapped[str] = mapped_column(String(128))
    page_name: Mapped[str] = mapped_column(String(256))
    score: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

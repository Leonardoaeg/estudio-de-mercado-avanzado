"""Domain-level Pydantic schemas used to move data between pipeline stages, decoupled
from the SQLAlchemy ORM models (database/models.py). Sources produce `RawAd`; the
pipeline enriches it into `NormalizedAd` before it is persisted.

Every "unknown at this stage" field uses the literal string constants below rather than
None, so reports never confuse "we don't know" with "we know it's empty" (section 3).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

NOT_AVAILABLE = "not_available"
UNKNOWN = "unknown"
NOT_VERIFIED = "not_verified"


class AdFormat(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    CAROUSEL = "carousel"
    UNKNOWN = "unknown"


class EvidenceLevel(str, Enum):
    """Section 3: never blur fact, inference, and hypothesis."""

    HECHO = "HECHO"
    INFERENCIA = "INFERENCIA"
    HIPOTESIS = "HIPOTESIS"


class RawAd(BaseModel):
    """What a source (Meta Graph API / scraper / mock) hands back, before enrichment."""

    ad_id: str
    source_name: str
    page_id: str
    page_name: str
    ad_library_url: str | None = None
    active: bool = True
    start_date: str | None = None
    format_hint: str | None = None  # source's own hint, refined later by format_classifier
    primary_text: str | None = None
    headline: str | None = None
    description: str | None = None
    cta: str | None = None
    landing_url: str | None = None
    raw_payload: dict = Field(default_factory=dict)


class NormalizedAd(BaseModel):
    ad_id: str
    source_name: str
    page_id: str
    page_name: str
    ad_library_url: str | None
    active: bool
    start_date: datetime | None
    age_days: int | None
    format: AdFormat
    primary_text: str | None
    headline: str | None
    description: str | None
    cta: str | None
    landing_url: str | None
    final_landing_url: str | None
    product: str | None
    product_category: str | None
    price: float | None
    old_price: float | None
    discount: float | None
    offer_type: str | None
    hook: str | None
    hook_type: str | None
    creative_angle: str | None
    creative_style: str | None
    ugc_detected: bool | None
    testimonial_detected: bool | None
    demonstration_detected: bool | None
    problem_solution_detected: bool | None
    comparison_detected: bool | None
    creative_fingerprint: str | None
    claims_risk_flags: list[str] = Field(default_factory=list)
    niche: str | None
    subniche: str | None
    confidence: float = 0.0
    raw_payload: dict = Field(default_factory=dict)


class DiscoveredPage(BaseModel):
    page_id: str
    page_name: str
    fanpage_url: str | None = None
    niche: str
    discovered_via_keyword: str
    generation: int = 0

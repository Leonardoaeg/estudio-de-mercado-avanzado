"""Pipeline orchestrator — section 43. Runs DISCOVER -> ... -> SAVE_SNAPSHOT, wiring every
module built in src/eci/*. Every stage is wrapped so a single failure (one bad store, one
timeout) is logged to `errors` and does not abort the run (section 31/50).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from eci.classifiers.angle_classifier import classify_angle
from eci.classifiers.brand_exclusion import is_excluded_brand
from eci.classifiers.claims_risk import analyze_claims_risk
from eci.classifiers.format_classifier import classify_format, format_distribution
from eci.classifiers.hook_classifier import classify_hook, extract_hook_text
from eci.classifiers.niche_classifier import classify_subniche_for_niche
from eci.classifiers.offer_classifier import classify_offer, extract_discount_percentage
from eci.classifiers.style_flags import detect_style_flags
from eci.config import get_settings
from eci.creative.family_detector import ad_to_family_map, build_families
from eci.creative.landing_analyzer import analyze_landing
from eci.database.engine import get_session
from eci.database.migrate import apply_migrations
from eci.database.models import Advertiser, ResearchRun, Snapshot
from eci.database.repository import (
    record_error,
    replace_rankings,
    save_snapshot,
    upsert_ad,
    upsert_advertiser,
    upsert_creative_family,
    upsert_keyword,
    upsert_store,
)
from eci.discovery.keyword_engine import expand_keywords
from eci.ecommerce.validator import score_html, validate_store
from eci.metrics.longevity import AdLongevityFact, dominant_value, summarize_longevity
from eci.models.schemas import AdFormat, NormalizedAd, RawAd
from eci.pipeline.checkpoints import set_stage
from eci.ranking.rankers import rank_by_acceleration, rank_by_presence
from eci.reports.generator import ReportBundle, write_reports
from eci.scoring.confidence import ConfidenceInputs, calculate_confidence_score
from eci.scoring.scale_signal import ScaleSignalInputs, calculate_scale_signal_score
from eci.shopify.detector import detect_from_html, detect_store
from eci.sources import get_source
from eci.sources.mock_source import synthetic_store_html
from eci.utils.dates import age_days, parse_date
from eci.utils.textsim import creative_fingerprint
from eci.utils.urls import canonical_store_key, normalize_url


@dataclass
class RunConfig:
    niche: str
    market: str
    source_name: str = "mock"
    minimum_active_ads: int | None = None  # falls back to settings.minimum_active_ads
    shopify_only: bool = False
    max_keywords: int = 12
    max_pages_per_keyword: int = 3
    analyze_landing_pages: bool = True
    top_n: int = 10


@dataclass
class RunResult:
    run_uuid: str
    niche: str
    market: str
    stage: str
    pages_discovered: int = 0
    pages_analyzed: int = 0
    ecommerce_verified: int = 0
    stores_over_threshold: int = 0
    ads_collected: int = 0
    format_counts: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report_path: str | None = None
    database_path: str | None = None


def _normalize_ad(raw: RawAd, niche: str) -> NormalizedAd:
    fmt, _fmt_conf = classify_format(raw.format_hint, raw.primary_text)
    hook_type, _hook_conf = classify_hook(raw.primary_text)
    hook_text = extract_hook_text(raw.primary_text)
    angle, _angle_conf = classify_angle(raw.primary_text)
    offer_type, _offer_conf = classify_offer(raw.primary_text)
    discount_pct = extract_discount_percentage(raw.primary_text)
    style_flags = detect_style_flags(raw.primary_text)
    claims = analyze_claims_risk(raw.primary_text)
    subniche, subniche_conf = classify_subniche_for_niche(raw.primary_text or raw.headline or "", niche)

    start_dt = parse_date(raw.start_date)
    ad_age = age_days(raw.start_date)

    landing_norm = normalize_url(raw.landing_url)
    price = None
    if isinstance(raw.raw_payload, dict) and "price" in raw.raw_payload:
        try:
            price = float(raw.raw_payload["price"])
        except (TypeError, ValueError):
            price = None

    fingerprint = creative_fingerprint(raw.primary_text, hook_text, raw.headline, landing_norm, raw.cta)

    # Overall confidence: blends per-field classifier confidences; conservative floor when
    # there's no ad copy at all to classify from.
    confidence = 0.0 if not raw.primary_text else round((_fmt_conf + _hook_conf + _angle_conf + _offer_conf) / 4, 2)

    return NormalizedAd(
        ad_id=raw.ad_id,
        source_name=raw.source_name,
        page_id=raw.page_id,
        page_name=raw.page_name,
        ad_library_url=raw.ad_library_url,
        active=raw.active,
        start_date=start_dt,
        age_days=ad_age,
        format=fmt,
        primary_text=raw.primary_text,
        headline=raw.headline,
        description=raw.description,
        cta=raw.cta,
        landing_url=raw.landing_url,
        final_landing_url=landing_norm,
        product=raw.headline,
        product_category=None,
        price=price,
        old_price=None,
        discount=discount_pct,
        offer_type=offer_type,
        hook=hook_text,
        hook_type=hook_type,
        creative_angle=angle,
        creative_style=None,
        ugc_detected=style_flags["ugc_detected"],
        testimonial_detected=style_flags["testimonial_detected"],
        demonstration_detected=style_flags["demonstration_detected"],
        problem_solution_detected=style_flags["problem_solution_detected"],
        comparison_detected=style_flags["comparison_detected"],
        creative_fingerprint=fingerprint,
        claims_risk_flags=claims,
        niche=niche,
        subniche=subniche,
        confidence=confidence,
        raw_payload=raw.raw_payload,
    )


def run_research(config: RunConfig) -> RunResult:
    settings = get_settings()
    apply_migrations()
    session = get_session()

    run_uuid = str(uuid.uuid4())
    minimum_active_ads = config.minimum_active_ads or settings.minimum_active_ads

    run = ResearchRun(
        run_uuid=run_uuid,
        market=config.market,
        niche=config.niche,
        source_name=config.source_name,
        minimum_active_ads=minimum_active_ads,
        stage="DISCOVER",
    )
    session.add(run)
    session.flush()

    result = RunResult(run_uuid=run_uuid, niche=config.niche, market=config.market, stage="DISCOVER")

    try:
        source = get_source(config.source_name)
    except ValueError as exc:
        record_error(session, run_uuid=run_uuid, stage="DISCOVER", entity_ref=None, message=str(exc))
        session.commit()
        result.errors.append(str(exc))
        return result

    available, reason = source.is_available()
    if not available:
        record_error(session, run_uuid=run_uuid, stage="DISCOVER", entity_ref=config.source_name, message=reason or "unavailable")
        session.commit()
        result.errors.append(f"source_unavailable: {reason}")
        result.stage = "DONE"
        return result

    # --- DISCOVER: seed keywords from config, capped ---
    seed_keywords = list(settings.keywords.get(config.niche.upper(), []))[: config.max_keywords]
    for kw in seed_keywords:
        upsert_keyword(session, kw, config.niche, config.market, {"generation": 0})
    session.commit()

    # --- COLLECT + NORMALIZE + DEDUPLICATE ---
    set_stage(session, run, "COLLECT")
    all_normalized: list[NormalizedAd] = []
    pages_seen: set[str] = set()

    for keyword in seed_keywords:
        cursor = None
        for _page in range(config.max_pages_per_keyword):
            outcome = source.search_ads(keyword, config.market, page_cursor=cursor)
            if not outcome.ok:
                record_error(session, run_uuid=run_uuid, stage="COLLECT", entity_ref=keyword, message=outcome.error or "unknown_error")
                result.warnings.append(f"{keyword}: {outcome.error}")
                break
            for raw_ad in outcome.ads:
                normalized = _normalize_ad(raw_ad, config.niche)
                all_normalized.append(normalized)
                pages_seen.add(normalized.page_id)
            if outcome.exhausted:
                break
        session.commit()

    set_stage(session, run, "NORMALIZE")
    result.pages_discovered = len(pages_seen)
    result.ads_collected = len(all_normalized)

    # DEDUPLICATE + persist ads
    set_stage(session, run, "DEDUPLICATE")
    for ad in all_normalized:
        upsert_ad(
            session,
            {
                "ad_id": ad.ad_id,
                "source_name": ad.source_name,
                "page_id": ad.page_id,
                "page_name": ad.page_name,
                "ad_library_url": ad.ad_library_url,
                "active": ad.active,
                "start_date": ad.start_date,
                "age_days": ad.age_days,
                "format": ad.format.value,
                "primary_text": ad.primary_text,
                "headline": ad.headline,
                "description": ad.description,
                "cta": ad.cta,
                "landing_url": ad.landing_url,
                "final_landing_url": ad.final_landing_url,
                "product": ad.product,
                "product_category": ad.product_category,
                "price": ad.price,
                "old_price": ad.old_price,
                "discount": ad.discount,
                "offer_type": ad.offer_type,
                "hook": ad.hook,
                "hook_type": ad.hook_type,
                "creative_angle": ad.creative_angle,
                "creative_style": ad.creative_style,
                "ugc_detected": ad.ugc_detected,
                "testimonial_detected": ad.testimonial_detected,
                "demonstration_detected": ad.demonstration_detected,
                "problem_solution_detected": ad.problem_solution_detected,
                "comparison_detected": ad.comparison_detected,
                "creative_fingerprint": ad.creative_fingerprint,
                "claims_risk_flags": ad.claims_risk_flags,
                "niche": ad.niche,
                "subniche": ad.subniche,
                "confidence": ad.confidence,
                "raw_payload": ad.raw_payload,
            },
        )
    session.commit()

    # --- Discovery round 2: mine new keywords from what we just collected (best-effort) ---
    try:
        new_keywords = expand_keywords(all_normalized, existing_keywords=set(seed_keywords))
        for kw in new_keywords:
            upsert_keyword(session, kw, config.niche, config.market, {"generation": 1})
        session.commit()
    except Exception as exc:  # noqa: BLE001
        record_error(session, run_uuid=run_uuid, stage="DISCOVER", entity_ref=None, message=f"keyword_expansion_failed: {exc}")
        session.commit()

    # --- Group ads per advertiser (page_id) ---
    ads_by_page: dict[str, list[NormalizedAd]] = {}
    for ad in all_normalized:
        ads_by_page.setdefault(ad.page_id, []).append(ad)

    # --- CREATE_FAMILIES (per-page creative concept grouping) ---
    set_stage(session, run, "CREATE_FAMILIES")
    family_dicts = [
        {
            "ad_id": ad.ad_id,
            "page_id": ad.page_id,
            "primary_text": ad.primary_text,
            "hook": ad.hook,
            "product": ad.product,
            "landing_url": ad.final_landing_url,
            "cta": ad.cta,
            "format": ad.format.value,
            "hook_type": ad.hook_type,
        }
        for ad in all_normalized
    ]
    families = build_families(family_dicts)
    ad_family_map = ad_to_family_map(families)
    for family_key, cluster in families.items():
        upsert_creative_family(
            session,
            family_key,
            {
                "page_id": cluster.member_ad_ids and next(
                    (a.page_id for a in all_normalized if a.ad_id == cluster.representative_ad_id), "unknown"
                ) or "unknown",
                "representative_ad_id": cluster.representative_ad_id,
                "member_count": len(cluster.member_ad_ids),
                "dominant_hook": cluster.dominant_hook,
                "dominant_format": cluster.dominant_format,
                "structure_summary": None,
            },
        )
    session.commit()

    # --- VERIFY_ECOMMERCE + DETECT_SHOPIFY + landing analysis, per advertiser ---
    set_stage(session, run, "VERIFY_ECOMMERCE")
    advertiser_rows: list[dict] = []
    cohort_active_counts = [
        sum(1 for a in ads if a.active) for ads in ads_by_page.values()
    ]

    for page_id, ads in ads_by_page.items():
        try:
            store_candidate = next((a.final_landing_url for a in ads if a.final_landing_url), None)
            ecommerce_report = {"ecommerce_score": 0.0, "verified": False, "reason": "no_landing_url", "signals": {}}
            shopify_report = {"shopify_detected": None, "shopify_confidence": 0.0, "shopify_signals": {}}
            domain = None
            if store_candidate:
                domain = canonical_store_key(store_candidate)
                if config.source_name == "mock":
                    # MockSource ads point at store URLs that don't exist on the real internet
                    # (see mock_source.py docstring). Running the real HTTP fetch against them
                    # would only measure DNS/TLS failure latency, not exercise anything new — the
                    # exact same score_html/detect_from_html heuristics are exercised instead
                    # against synthetic HTML, keeping `--source mock` genuinely network-free
                    # end-to-end (IMPLEMENTATION_PLAN.md's stated purpose for this source).
                    is_shopify_page = hash(page_id) % 3 != 0  # deterministic ~2/3 Shopify mix
                    synthetic_html = synthetic_store_html(ads[0].page_name, shopify=is_shopify_page)
                    score, ec_signals = score_html(synthetic_html)
                    ecommerce_report = {"ecommerce_score": score, "verified": score >= settings.ecommerce_score_minimum, "reason": None, "signals": ec_signals.__dict__}
                    detected, confidence, shop_signals = detect_from_html(synthetic_html)
                    shopify_report = {"shopify_detected": detected, "shopify_confidence": confidence, "shopify_signals": shop_signals.matched}
                else:
                    ecommerce_report = validate_store(store_candidate)
                    shopify_report = detect_store(store_candidate)
                    if ecommerce_report.get("verified") is False and ecommerce_report.get("reason"):
                        result.warnings.append(f"{page_id}: ecommerce fetch issue ({ecommerce_report['reason']})")

            if domain:
                upsert_store(
                    session,
                    domain,
                    {
                        "store_url": store_candidate,
                        "advertiser_page_id": page_id,
                        "ecommerce_score": ecommerce_report.get("ecommerce_score", 0.0),
                        "shopify_detected": shopify_report.get("shopify_detected"),
                        "landing_analysis": {},
                    },
                )
                session.commit()
                result.ecommerce_verified += 1 if ecommerce_report.get("verified") else 0

            active_ads = [a for a in ads if a.active]
            longevity_facts = [
                AdLongevityFact(
                    ad_id=a.ad_id,
                    age_days=a.age_days,
                    ad_library_url=a.ad_library_url,
                    start_date=a.start_date.isoformat() if a.start_date else None,
                    format=a.format.value,
                    hook_type=a.hook_type,
                    product=a.product,
                )
                for a in active_ads
            ]
            longevity = summarize_longevity(
                longevity_facts,
                reference_min_age_days=settings.longevity_reference_window.min_age_days,
                reference_max_age_days=settings.longevity_reference_window.max_age_days,
            )
            formats = [a.format for a in active_ads]
            dist = format_distribution(formats)
            page_family_ids = {ad_family_map[a.ad_id] for a in ads if a.ad_id in ad_family_map}
            excluded_brand, excluded_reason = is_excluded_brand(ads[0].page_name)

            advertiser_rows.append(
                {
                    "page_id": page_id,
                    "page_name": ads[0].page_name,
                    "excluded_brand": excluded_brand,
                    "excluded_reason": excluded_reason,
                    # Only a real numeric Facebook Page ID (Graph API source) makes a valid
                    # facebook.com/<id> URL. MockSource ("mock_...") and the web scraper
                    # ("scraped_<slug>", since the card doesn't expose the real numeric ID
                    # without an extra click-through — documented limitation) don't have
                    # one, so this stays not_available rather than linking to a 404.
                    "fanpage_url": f"https://www.facebook.com/{page_id}" if page_id.isdigit() else None,
                    "instagram_url": None,
                    "country": config.market,
                    "niche": config.niche,
                    "subniche": dominant_value([a.subniche for a in ads]),
                    "classification_confidence": 0.5 if any(a.subniche for a in ads) else 0.0,
                    "active_ad_count": len(active_ads),
                    "store_url": store_candidate,
                    "final_store_url": store_candidate,
                    "ecommerce_score": ecommerce_report.get("ecommerce_score", 0.0),
                    "ecommerce_signals": ecommerce_report.get("signals", {}),
                    "shopify_detected": shopify_report.get("shopify_detected"),
                    "shopify_confidence": shopify_report.get("shopify_confidence", 0.0),
                    "shopify_signals": shopify_report.get("shopify_signals", {}),
                    "video_count": sum(1 for f in formats if f == AdFormat.VIDEO),
                    "image_count": sum(1 for f in formats if f == AdFormat.IMAGE),
                    "carousel_count": sum(1 for f in formats if f == AdFormat.CAROUSEL),
                    "unknown_format_count": sum(1 for f in formats if f == AdFormat.UNKNOWN),
                    "oldest_active_ad_url": longevity.oldest_active_ad_url,
                    "oldest_active_ad_date": None,
                    "oldest_active_ad_age_days": longevity.oldest_active_ad_age_days,
                    "median_ad_age": longevity.median_ad_age,
                    "average_ad_age": longevity.average_ad_age,
                    "ads_over_14_days": longevity.ads_over_14_days,
                    "ads_over_30_days": longevity.ads_over_30_days,
                    "ads_over_60_days": longevity.ads_over_60_days,
                    "ads_over_90_days": longevity.ads_over_90_days,
                    "ads_in_reference_window": longevity.ads_in_reference_window,
                    "reference_window_ratio": longevity.reference_window_ratio,
                    "dominant_format": dominant_value([f.value for f in formats]),
                    "dominant_hook": dominant_value([a.hook_type for a in active_ads]),
                    "dominant_angle": dominant_value([a.creative_angle for a in active_ads]),
                    "dominant_offer": dominant_value([a.offer_type for a in active_ads]),
                    "_n_creative_families": len(page_family_ids),
                    "_n_total_ads": len(ads),
                    "_format_distribution_pct": dist,
                    "_ads": ads,
                }
            )
        except Exception as exc:  # noqa: BLE001
            record_error(session, run_uuid=run_uuid, stage="VERIFY_ECOMMERCE", entity_ref=page_id, message=str(exc))
            result.warnings.append(f"{page_id}: {exc}")

    set_stage(session, run, "DETECT_SHOPIFY")
    result.pages_analyzed = len(advertiser_rows)

    # --- CALCULATE_METRICS + SCORE ---
    set_stage(session, run, "CALCULATE_METRICS")
    set_stage(session, run, "SCORE")
    for row in advertiser_rows:
        longevity_summary = summarize_longevity(
            [
                AdLongevityFact(ad_id=a.ad_id, age_days=a.age_days)
                for a in row["_ads"]
                if a.active
            ],
            reference_min_age_days=settings.longevity_reference_window.min_age_days,
            reference_max_age_days=settings.longevity_reference_window.max_age_days,
        )
        # Historical presence: how many prior snapshots exist for this page.
        prior_snapshots = session.query(Snapshot).filter_by(page_id=row["page_id"]).count()

        scale_inputs = ScaleSignalInputs(
            active_ad_count=row["active_ad_count"],
            cohort_active_ad_counts=cohort_active_counts,
            longevity=longevity_summary,
            n_creative_families=row["_n_creative_families"],
            n_total_ads=row["_n_total_ads"],
            format_distribution_pct=row["_format_distribution_pct"],
            snapshots_observed=prior_snapshots,
            ecommerce_score=row["ecommerce_score"],
        )
        scale_score, _breakdown = calculate_scale_signal_score(scale_inputs)

        cross_agree = None
        if row["shopify_detected"] is not None:
            cross_agree = row["shopify_detected"] == (row["ecommerce_score"] >= settings.ecommerce_score_minimum)

        confidence_inputs = ConfidenceInputs(
            advertiser_fields={k: row.get(k) for k in row if not k.startswith("_")},
            source_name=config.source_name,
            last_verified_at=datetime.now(timezone.utc),
            cross_signals_agree=cross_agree,
        )
        confidence_score, _c_breakdown = calculate_confidence_score(confidence_inputs)

        # Acceleration: compare against the most recent prior snapshot for this page.
        previous = (
            session.query(Snapshot)
            .filter_by(page_id=row["page_id"])
            .order_by(Snapshot.taken_at.desc())
            .first()
        )
        growth_percentage = None
        acceleration_score = 0.0
        new_ads, removed_ads = 0, 0
        if previous is not None and previous.active_ad_count:
            growth_percentage = round(
                (row["active_ad_count"] - previous.active_ad_count) / previous.active_ad_count * 100, 1
            )
            prev_ids = set(previous.ad_ids or [])
            current_ids = {a.ad_id for a in row["_ads"] if a.active}
            new_ads = len(current_ids - prev_ids)
            removed_ads = len(prev_ids - current_ids)
            acceleration_score = round(max(growth_percentage, 0) * 0.5 + new_ads * 2, 1)

        row["scale_signal_score"] = scale_score
        row["confidence_score"] = confidence_score
        row["growth_percentage"] = growth_percentage
        row["acceleration_score"] = acceleration_score
        row["new_ads_since_last_snapshot"] = new_ads
        row["removed_ads_since_last_snapshot"] = removed_ads
        row["last_verified_at"] = datetime.now(timezone.utc)
        row["created_at"] = datetime.now(timezone.utc)

        # excluded_brand/excluded_reason are report/ranking-time fields only (see RANK stage
        # below) — not part of the Advertiser DB schema, so they're stripped before persisting.
        persisted = {
            k: v for k, v in row.items() if not k.startswith("_") and k not in ("excluded_brand", "excluded_reason")
        }
        upsert_advertiser(session, persisted)
    session.commit()

    result.format_counts = {
        "video": sum(r["video_count"] for r in advertiser_rows),
        "image": sum(r["image_count"] for r in advertiser_rows),
        "carousel": sum(r["carousel_count"] for r in advertiser_rows),
        "unknown": sum(r["unknown_format_count"] for r in advertiser_rows),
    }

    # --- Optional landing-page deep analysis for advertisers over threshold ---
    # Skipped for source_name == "mock": store_url points at a synthetic domain (see
    # synthetic_store_html above), so there is nothing real to fetch — see IMPLEMENTATION_PLAN.md.
    if config.analyze_landing_pages and config.source_name != "mock":
        for row in advertiser_rows:
            if row["active_ad_count"] < minimum_active_ads or not row["store_url"]:
                continue
            try:
                analyze_landing(row["store_url"])
            except Exception as exc:  # noqa: BLE001
                record_error(session, run_uuid=run_uuid, stage="ANALYZE_CREATIVES", entity_ref=row["page_id"], message=str(exc))

    # --- RANK ---
    set_stage(session, run, "RANK")
    # Mega-brands/marketplaces (SHEIN, Mercado Libre, ...) are never presented as a "small
    # store" example (operator instruction) — excluded from qualifying/rankings entirely,
    # but their ads still feed the report's aggregate creative-pattern sections (see
    # `creative_reference` below and reports/generator.py) since their hooks/angles/offers
    # are still real market signal, just not a "store to emulate".
    qualifying = [
        r
        for r in advertiser_rows
        if r["active_ad_count"] >= minimum_active_ads
        and r["ecommerce_score"] >= settings.ecommerce_score_minimum
        and not r["excluded_brand"]
        and (not config.shopify_only or r["shopify_detected"] is True)
    ]
    creative_reference = [r for r in advertiser_rows if r["excluded_brand"] and r["active_ad_count"] > 0]
    result.stores_over_threshold = len(qualifying)

    presence_rank = rank_by_presence(qualifying, top_n=config.top_n)
    acceleration_rank = rank_by_acceleration(qualifying, top_n=config.top_n)

    replace_rankings(
        session,
        config.niche,
        config.market,
        "presence",
        [{"rank": r.rank, "page_id": r.page_id, "page_name": r.page_name, "score": r.score} for r in presence_rank],
    )
    replace_rankings(
        session,
        config.niche,
        config.market,
        "acceleration",
        [{"rank": r.rank, "page_id": r.page_id, "page_name": r.page_name, "score": r.score} for r in acceleration_rank],
    )
    session.commit()

    # --- GENERATE_REPORT ---
    set_stage(session, run, "GENERATE_REPORT")
    bundle = ReportBundle(
        niche=config.niche,
        market=config.market,
        run_uuid=run_uuid,
        source_name=config.source_name,
        pages_discovered=result.pages_discovered,
        pages_analyzed=result.pages_analyzed,
        ecommerce_verified=result.ecommerce_verified,
        stores_over_threshold=result.stores_over_threshold,
        minimum_active_ads=minimum_active_ads,
        advertisers=qualifying,
        all_advertisers=advertiser_rows,
        creative_reference_advertisers=creative_reference,
        presence_ranking=presence_rank,
        acceleration_ranking=acceleration_rank,
        format_counts=result.format_counts,
        warnings=result.warnings,
        errors=result.errors,
    )
    report_path = write_reports(bundle)
    result.report_path = str(report_path)

    run.report_path = str(report_path)
    run.database_path = settings.database_url
    run.pages_discovered = result.pages_discovered
    run.pages_analyzed = result.pages_analyzed
    run.ecommerce_verified = result.ecommerce_verified
    run.stores_over_threshold = result.stores_over_threshold
    run.ads_collected = result.ads_collected
    run.videos = result.format_counts.get("video", 0)
    run.images = result.format_counts.get("image", 0)
    run.carousels = result.format_counts.get("carousel", 0)
    run.unknown_format = result.format_counts.get("unknown", 0)
    run.errors_count = len(result.errors)
    run.warnings_count = len(result.warnings)

    # --- SAVE_SNAPSHOT ---
    set_stage(session, run, "SAVE_SNAPSHOT")
    now = datetime.now(timezone.utc)
    for row in advertiser_rows:
        current_ids = [a.ad_id for a in row["_ads"] if a.active]
        page_family_ids = sorted({ad_family_map[aid] for aid in current_ids if aid in ad_family_map})
        products = sorted({a.product for a in row["_ads"] if a.product})[:20]
        save_snapshot(
            session,
            {
                "page_id": row["page_id"],
                "niche": config.niche,
                "market": config.market,
                "taken_at": now,
                "active_ad_count": row["active_ad_count"],
                "ad_ids": current_ids,
                "creative_family_ids": page_family_ids,
                "products": products,
                "scale_signal_score": row["scale_signal_score"],
            },
        )
    session.commit()

    set_stage(session, run, "DONE")
    run.finished_at = now
    session.commit()

    result.database_path = settings.database_url
    result.stage = "DONE"
    session.close()
    return result

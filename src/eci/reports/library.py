"""Biblioteca de Referentes — a curated, visual swipe file of small independent LATAM
ecommerce brands actively advertising at scale on Meta, deliberately separate from the
technical audit report (reports/generator.py): this one is meant to be browsed for
creative inspiration, not audited.

Selection rule (operator instruction, 2026-08-14): a brand only earns a card if it has
at least one ACTIVE ad that has been running 30+ days — that's the "proof of a working
creative strategy" bar, distinct from just having many ads. Known mega-brands/marketplaces
are excluded (classifiers/brand_exclusion.py) regardless of ad volume. One file per niche;
multiple markets can feed the same file (a brand found via more than one market search is
deduplicated by store domain).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from eci.classifiers.brand_exclusion import is_excluded_brand, is_excluded_domain
from eci.classifiers.claims_risk import is_claims_sensitive_niche
from eci.config import CONFIG_DIR, REPORTS_DIR, get_settings
from eci.reports.generator import _fmt_pairs  # reuse the same "label (count)" formatting
from eci.utils.urls import (
    extract_ad_id,
    extract_domain,
    meta_ad_library_ad_url_with_context,
    meta_ad_library_page_url,
    meta_ad_library_store_search_url,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
LIBRARY_DIR = REPORTS_DIR / "biblioteca"
CREATIVE_NOTES_DIR = CONFIG_DIR / "creative_notes"


def _load_creative_notes(niche: str) -> dict[str, dict[str, str]]:
    """Loads config/creative_notes/<NICHE>.yaml — manually-curated "estructura del
    creativo" descriptions written after actually watching/viewing the ad (see that file's
    header comment). Missing file or missing entry just means "not reviewed yet", never an
    error — visual review is an incremental, ongoing process, not a hard requirement."""
    path = CREATIVE_NOTES_DIR / f"{niche.upper()}.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}

_MARKET_FLAGS = {
    "CO": "🇨🇴", "MX": "🇲🇽", "PE": "🇵🇪", "EC": "🇪🇨", "CL": "🇨🇱",
    "AR": "🇦🇷", "US": "🇺🇸", "ES": "🇪🇸",
}

# Extra precision filter specific to this curated library (operator: "necesito precisión").
# Keyword-based discovery occasionally pulls in a real, ecommerce-scoring store that's
# still the wrong kind of business for a niche swipe file — e.g. a dog-agility training
# academy surfaced by a "chaqueta impermeable" search matching dog raincoats. The full
# audit report (reports/generator.py) keeps these with their real scores for completeness;
# this library actively screens them out since it's meant to be browsed as-is.
_OFF_TOPIC_RE = re.compile(
    r"\bacademy\b|\bacademia\b|\bcurso\b|\bcoaching\b|\bconsultor(a|ía)\b|\bagencia\b",
    re.IGNORECASE,
)

# Generic link shorteners found live pointing at 3 completely unrelated advertisers under
# the exact same "domain" (bit.ly). Deduping by domain would silently collapse them into
# one card — the fix isn't to exclude these brands (they're real, distinct businesses),
# it's to never treat a shortener as a meaningful "domain" for dedup purposes.
_LINK_SHORTENER_DOMAINS = {"bit.ly", "tinyurl.com", "t.ly", "cutt.ly", "rebrand.ly", "is.gd", "s.id"}

# A real find (2026-08-14, SUPLEMENTOS pass): a genuinely single-vendor store
# (dulcehogar55.myshopify.com, 4 active ads all pointing at its own store) was wrongly
# thrown out by _is_multi_vendor_affiliate because one of its ads' "landing_url" was a
# WhatsApp CTA link (api.whatsapp.com) instead of the product page — a completely normal
# thing for a small store to do, not a second unrelated business. Messaging/social CTA
# domains never count as a distinct "store domain" for the multi-vendor check below.
_NON_STORE_CTA_DOMAINS = {
    "api.whatsapp.com",
    "whatsapp.com",
    "wa.link",
    "wa.me",
    "m.me",
    "instagram.com",
    "facebook.com",
    "t.me",
    "play.google.com",
    "apps.apple.com",
    "itunes.apple.com",
}

# A real find (2026-08-14, "más de 20 anuncios" pass): ICON Amsterdam's real 42-ad page
# was being thrown out by the multi-vendor check over just 4 of its 38 ads — a hotel
# booking site, a leather-accessories store, and an AI ad tool, each attached to ad copy
# that was obviously about ICON's own jeans/overshirts. That's the scraper's landing-URL
# extraction (positional pairing of ad cards to `l.facebook.com/l.php` hrefs on the page,
# see meta_web_scraper.py) occasionally grabbing a NEIGHBORING ad's link, not a second
# business. A genuine affiliate/media-buyer (confirmed live: Beautyboost, Sowi Colombia)
# has NO dominant domain — its ads are spread roughly evenly across 3-6 stores. So instead
# of "any 2+ distinct domains", require the single most common domain to fall under this
# share of all (non-CTA) landing domains before calling it multi-vendor.
_MULTI_VENDOR_DOMINANT_SHARE_THRESHOLD = 0.7


def _is_off_topic(page_name: str, store_url: str | None) -> bool:
    haystack = f"{page_name} {store_url or ''}"
    return bool(_OFF_TOPIC_RE.search(haystack))


def _is_multi_vendor_affiliate(session, ad_model, page_id: str) -> bool:
    """A real find: one advertiser page ran the identical ad copy landing on THREE
    unrelated domains (a bedsheet, a vitamin-B store, and a multivitamin store) — that's
    an affiliate/media-buyer running traffic for other people's stores, not a store of
    their own: confirmed live, these pages have NO dominant domain, ads spread roughly
    evenly across every one. A real single-vendor store can still show a couple of stray
    non-store landing domains (scraper landing-URL extraction noise — see
    _MULTI_VENDOR_DOMINANT_SHARE_THRESHOLD's comment for the confirmed live example), so
    the signal isn't "2+ distinct domains", it's "no single domain clearly dominates"."""
    rows = session.query(ad_model.landing_url).filter_by(page_id=page_id).all()
    domains = [extract_domain(url) for (url,) in rows if url]
    domains = [d for d in domains if d and d not in _NON_STORE_CTA_DOMAINS]
    if len(domains) < 2:
        return False
    _dominant_domain, dominant_count = Counter(domains).most_common(1)[0]
    dominant_share = dominant_count / len(domains)
    return dominant_share < _MULTI_VENDOR_DOMINANT_SHARE_THRESHOLD


def _serialize_ad(a, *, market: str, page_name: str) -> dict:
    """One ad's worth of fields for the biblioteca — shared by the "reference" cards
    (30+ day ads, quote + structure note) and the full "todos los anuncios activos" list
    (operator, 2026-08-14: "debes de colocar todos los anuncios activos que tenga la
    tienda... el limite solo es al evaluar los creativos en cuanto videos" — the 3-4
    ad *visual review* cap from the original spec was never meant to cap how many real
    ads get listed, only how many get manually watched/described in creative_notes)."""
    return {
        "ad_id": a.ad_id,
        "age_days": a.age_days,
        "hook_type": a.hook_type,
        "creative_angle": a.creative_angle,
        "offer_type": a.offer_type,
        "format": a.format,
        "primary_text": (a.primary_text or "")[:220],
        "headline": a.headline,
        "claims_flags": a.claims_risk_flags or [],
        "ad_library_url": (
            meta_ad_library_ad_url_with_context(extract_ad_id(a.ad_library_url), market=market, keyword=page_name)
            if extract_ad_id(a.ad_library_url)
            else a.ad_library_url
        ),
    }


def _scale_tier(active_ad_count: int) -> str:
    """Operator's explicit bar: 50+ active ads = genuinely scaling/experienced advertiser
    ("por lo general tienen un patrón"). Smaller-but-real stores stay visible (the operator
    also explicitly wants small independent stores as references) but clearly labeled, so
    the read never confuses "found it" with "it's proven at scale"."""
    if active_ad_count >= 50:
        return "alta"
    if active_ad_count >= 15:
        return "media"
    return "emergente"


_SCALE_TIER_LABELS = {
    "alta": "Escala alta (50+ anuncios activos)",
    "media": "Escala media (15-49 anuncios activos)",
    "emergente": "Emergente (menos de 15 anuncios activos)",
}


def _ads_link(
    page_id: str | None, oldest_active_ad_url: str | None, *, page_name: str | None = None, market: str | None = None
) -> tuple[str | None, bool]:
    """Returns (url, is_page_level). Prefers the real "see all ads from this Page" link
    (only possible with a real numeric Facebook page ID). Otherwise, rather than opening a
    specific ad, links straight to the Ad Library's results LIST filtered by the store's
    own name (operator: "que lleve a la biblioteca de anuncios filtrada por el nombre de
    la tienda") — no `?id=` modal in the way, just the filtered list of that store's ads."""
    page_url = meta_ad_library_page_url(page_id)
    if page_url:
        return page_url, True
    if page_name and market:
        return meta_ad_library_store_search_url(page_name, market), False
    if oldest_active_ad_url:
        return oldest_active_ad_url, False
    return None, False


def _build_library_context(
    niche: str,
    markets: list[str],
    session,
    *,
    min_ad_age_days: int = 30,
    min_ecommerce_score: float = 70.0,
    top_n: int = 10,
    must_include_domains: list[str] | None = None,
    niche_href_fn=lambda code: f"{code}.html",
) -> dict:
    """All the selection/filtering/aggregation work for one niche's biblioteca, shared by
    every output format (HTML, JSON, DOCX) — a single source of truth so they can never
    show different brands/numbers for the same build."""
    from eci.database.models import Ad, Advertiser

    creative_notes = _load_creative_notes(niche)

    niche = niche.upper()
    brands: list[dict] = []
    seen_keys: set[str] = set()

    for market in markets:
        market = market.upper()
        advertisers = (
            session.query(Advertiser)
            .filter_by(niche=niche, country=market)
            .filter(Advertiser.ecommerce_score >= min_ecommerce_score)
            .order_by(Advertiser.active_ad_count.desc())
            # Same store can show up as several distinct "advertisers" (creator/influencer
            # collab ads each post as their own Page but land on the same domain — seen live
            # with ICON Amsterdam: ~10 single-ad creator variants beside the real 42-ad brand
            # page). Processing highest ad-count first means the dedup-by-domain step below
            # always keeps the real brand account, not a 1-ad creator variant.
            .all()
        )
        for adv in advertisers:
            excluded, _reason = is_excluded_brand(adv.page_name)
            if excluded:
                continue
            domain_excluded, _domain_reason = is_excluded_domain(adv.store_url)
            if domain_excluded:
                continue
            if _is_off_topic(adv.page_name, adv.store_url):
                continue
            if _is_multi_vendor_affiliate(session, Ad, adv.page_id):
                continue

            # Dedup by domain, not full URL — the same store found via two market searches
            # (or two products) will have different paths/products but the same domain.
            # Falls back to a per-advertiser key for missing/shortener domains so unrelated
            # businesses sharing a link shortener never get collapsed into one card.
            store_domain = extract_domain(adv.store_url)
            if not store_domain or store_domain in _LINK_SHORTENER_DOMAINS:
                dedup_key = f"{market}:{adv.page_id}"
            else:
                dedup_key = store_domain
            if dedup_key in seen_keys:
                continue

            long_running_ads = (
                session.query(Ad)
                .filter_by(page_id=adv.page_id, active=True)
                .filter(Ad.age_days >= min_ad_age_days)
                .order_by(Ad.age_days.desc())
                .limit(3)
                .all()
            )
            if not long_running_ads:
                continue  # doesn't clear the "30+ days running" reference bar

            # ALL of this store's active ads, no age filter and no cap — operator: "debes
            # de colocar todos los anuncios activos que tenga la tienda... el limite solo
            # es al evaluar los creativos en cuanto videos". The 30+-day `long_running_ads`
            # above stays as the small "reference" set (quote + structure note cards); this
            # is the complete real inventory, always saved and always shown (collapsed, for
            # scale-alta brands with 50-170+ ads, but never truncated).
            all_active_ads_rows = (
                session.query(Ad)
                .filter_by(page_id=adv.page_id, active=True)
                .order_by(Ad.age_days.desc())
                .all()
            )

            seen_keys.add(dedup_key)
            ads_url, is_page_level = _ads_link(
                adv.page_id, adv.oldest_active_ad_url, page_name=adv.page_name, market=market
            )

            brands.append(
                {
                    "page_name": adv.page_name,
                    "domain": dedup_key,
                    "_page_id": adv.page_id,
                    "market": market,
                    "market_flag": _MARKET_FLAGS.get(market, ""),
                    "subniche": adv.subniche,
                    "store_url": adv.store_url,
                    "creative_notes": creative_notes.get(dedup_key, {}),
                    "shopify_detected": adv.shopify_detected,
                    "oldest_active_ad_age_days": adv.oldest_active_ad_age_days,
                    "active_ad_count": adv.active_ad_count,
                    "scale_tier": _scale_tier(adv.active_ad_count),
                    "scale_signal_score": adv.scale_signal_score,
                    "confidence_score": adv.confidence_score,
                    "dominant_format": adv.dominant_format,
                    # "Más detalle" panel fields (operator: the Level-Up-Suite-style detail
                    # drawer) — all sourced from fields the pipeline already computes per
                    # advertiser (metrics/scoring.py), never invented for the panel.
                    "dominant_hook": adv.dominant_hook,
                    "dominant_angle": adv.dominant_angle,
                    "dominant_offer": adv.dominant_offer,
                    "video_count": adv.video_count,
                    "image_count": adv.image_count,
                    "carousel_count": adv.carousel_count,
                    "unknown_format_count": adv.unknown_format_count,
                    "median_ad_age": adv.median_ad_age,
                    "ads_library_page_url": ads_url,
                    "ads_library_is_page_level": is_page_level,
                    "long_running_ads": [_serialize_ad(a, market=market, page_name=adv.page_name) for a in long_running_ads],
                    "all_active_ads": [_serialize_ad(a, market=market, page_name=adv.page_name) for a in all_active_ads_rows],
                    "all_active_ads_count": len(all_active_ads_rows),
                }
            )

    brands.sort(key=lambda b: (-b["active_ad_count"], -b["scale_signal_score"]))

    # Cap to a curated top N (operator: "necesito 10 marcas de cada uno") — this is a
    # swipe file meant to be actually read, not an exhaustive dump. Explicitly-requested
    # brands (e.g. One4Vice, ICON Amsterdam) are guaranteed a spot even on the rare chance
    # they didn't already rank inside the natural top N by ad count.
    selected = brands[:top_n]
    if must_include_domains:
        selected_domains = {b["domain"] for b in selected}
        for wanted in must_include_domains:
            if wanted in selected_domains:
                continue
            forced = next((b for b in brands if b["domain"] == wanted), None)
            if forced:
                selected.append(forced)
    brands = selected

    # A stable, global "#1, #2, ..." rank — independent of the tier/subniche grouping
    # below, which is a browsing aid, not a re-ranking. Assigned once, right after the
    # final top-N + must-include list is locked in, so it never drifts from what's shown.
    for i, b in enumerate(brands, start=1):
        b["rank"] = i

    # Format statistics across the curated set's full active-ad history (not just the 30+
    # day reference ads) — "extraerás por estadística si funciona más video, imagen o la
    # combinación". Queried directly rather than reusing long_running_ads, which is capped
    # at 3 ads/brand and therefore not representative of each brand's real format mix.
    format_stats = {"video": 0, "image": 0, "carousel": 0, "unknown": 0}
    single_format_brands = 0
    mixed_format_brands = 0
    if brands:
        page_ids = list({b["_page_id"] for b in brands})
        format_rows = session.query(Ad.page_id, Ad.format).filter(Ad.page_id.in_(page_ids), Ad.active.is_(True)).all()
        per_brand_formats: dict[str, dict[str, int]] = {}
        for page_id, fmt in format_rows:
            fmt = fmt or "unknown"
            format_stats[fmt] = format_stats.get(fmt, 0) + 1
            per_brand_formats.setdefault(page_id, {}).setdefault(fmt, 0)
            per_brand_formats[page_id][fmt] += 1
        for page_id, counts in per_brand_formats.items():
            known = {k: v for k, v in counts.items() if k != "unknown"}
            if len(known) <= 1:
                single_format_brands += 1
            else:
                mixed_format_brands += 1
    total_formatted_ads = sum(format_stats.values()) or 1
    format_percentages = {k: round(v / total_formatted_ads * 100, 1) for k, v in format_stats.items()}

    by_subniche: dict[str, list] = {}
    for b in brands:
        key = b["subniche"] or "General"
        by_subniche.setdefault(key, []).append(b)

    _tier_order = ["alta", "media", "emergente"]
    by_tier_and_subniche: dict[str, dict[str, list]] = {t: {} for t in _tier_order}
    for b in brands:
        tier_group = by_tier_and_subniche[b["scale_tier"]]
        key = b["subniche"] or "General"
        tier_group.setdefault(key, []).append(b)
    tier_counts = {t: sum(len(v) for v in by_tier_and_subniche[t].values()) for t in _tier_order}

    # Aggregate patterns across every 30+ day reference ad — "what do the brands that
    # already have a proven, long-running creative have in common", not a per-brand stat.
    def _count(values: list[str | None]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in values:
            if v:
                counts[v] = counts.get(v, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    all_reference_ads = [ad for b in brands for ad in b["long_running_ads"]]
    top_hooks = list(_count([a["hook_type"] for a in all_reference_ads]).items())[:6]
    top_angles = list(_count([a["creative_angle"] for a in all_reference_ads]).items())[:6]
    top_offers = list(_count([a["offer_type"] for a in all_reference_ads]).items())[:6]

    # Nav tabs across every niche's biblioteca file (operator: "todo organizado como está en
    # la página" — a real Level-Up-Suite-style niche switcher, not just one isolated file).
    # Sourced from config/niches.yaml — the same taxonomy the whole pipeline uses — rather
    # than hand-maintained here, so a niche never goes stale/missing from the nav.
    all_niches = [
        {"code": code, "label": info.get("label", code.title()), "active": code == niche, "href": niche_href_fn(code)}
        for code, info in get_settings().niches.items()
    ]

    context = {
        "niche": niche,
        "all_niches": all_niches,
        "markets": markets,
        "market_flags": " ".join(_MARKET_FLAGS.get(m.upper(), m) for m in markets),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brands": brands,
        "by_tier_and_subniche": by_tier_and_subniche,
        "tier_order": _tier_order,
        "tier_labels": _SCALE_TIER_LABELS,
        "tier_counts": tier_counts,
        "by_subniche": dict(sorted(by_subniche.items(), key=lambda kv: -len(kv[1]))),
        "total": len(brands),
        "min_ad_age_days": min_ad_age_days,
        "top_hooks": top_hooks,
        "top_angles": top_angles,
        "top_offers": top_offers,
        "format_stats": format_stats,
        "format_percentages": format_percentages,
        "single_format_brands": single_format_brands,
        "mixed_format_brands": mixed_format_brands,
        "is_claims_sensitive_niche": is_claims_sensitive_niche(niche),
    }
    return context


def build_library(
    niche: str,
    markets: list[str],
    session,
    *,
    min_ad_age_days: int = 30,
    min_ecommerce_score: float = 70.0,
    top_n: int = 10,
    must_include_domains: list[str] | None = None,
) -> Path:
    context = _build_library_context(
        niche,
        markets,
        session,
        min_ad_age_days=min_ad_age_days,
        min_ecommerce_score=min_ecommerce_score,
        top_n=top_n,
        must_include_domains=must_include_domains,
    )
    niche = context["niche"]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt_pairs"] = _fmt_pairs
    template = env.get_template("library.html.j2")
    html = template.render(**context)

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    path = LIBRARY_DIR / f"{niche}.html"
    path.write_text(html, encoding="utf-8")

    _write_library_json(niche, context, LIBRARY_DIR / f"{niche}.json")
    return path


def _write_library_json(niche: str, context: dict, path: Path) -> None:
    """Machine-readable twin of the HTML biblioteca — same underlying data (brands,
    format stats, hook/angle/offer patterns, tier groupings), shaped for a consuming
    app rather than for browsing. Written alongside the HTML on every build, from the
    same `context` dict the template renders, so the two can never drift apart.
    "_page_id" (leading underscore = template-internal, used only to re-query per-brand
    ad formats above) is renamed to "page_id" here since it's genuinely useful to an app
    and there's no reason to hide it — it's the same id already visible in every
    ad_library_url link on the page."""
    brands_out = []
    for b in context["brands"]:
        clean = {k: v for k, v in b.items() if not k.startswith("_")}
        clean["page_id"] = b["_page_id"]
        brands_out.append(clean)

    payload = {
        "niche": niche,
        "markets": context["markets"],
        "generated_at": context["generated_at"],
        "min_ad_age_days": context["min_ad_age_days"],
        "is_claims_sensitive_niche": context["is_claims_sensitive_niche"],
        "total_brands": context["total"],
        "scale_tiers": {
            tier: {
                "label": context["tier_labels"][tier],
                "count": context["tier_counts"][tier],
            }
            for tier in context["tier_order"]
        },
        "format_stats": context["format_stats"],
        "format_percentages": context["format_percentages"],
        "single_format_brands": context["single_format_brands"],
        "mixed_format_brands": context["mixed_format_brands"],
        "top_hooks": context["top_hooks"],
        "top_angles": context["top_angles"],
        "top_offers": context["top_offers"],
        "brands": brands_out,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

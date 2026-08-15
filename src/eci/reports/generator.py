"""Report generator — sections 34-37. Builds the full context dict once, then renders it
through Jinja2 templates into Markdown + HTML, and exports the same underlying rows to
CSV + JSON. Every number shown is traceable back to `advertiser_rows`/`_ads` computed by
the orchestrator — this module does not compute new "facts", only aggregates/formats them.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from eci.classifiers.claims_risk import CLAIMS_SENSITIVE_NICHES
from eci.config import REPORTS_DIR, get_settings
from eci.insights.insight_engine import build_niche_insights
from eci.models.schemas import NormalizedAd
from eci.ranking.rankers import RankedAdvertiser
from eci.trends.saturation_engine import creative_saturation, product_saturation
from eci.utils.urls import meta_ad_library_page_url, meta_ad_library_store_search_url

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class ReportBundle:
    niche: str
    market: str
    run_uuid: str
    source_name: str
    pages_discovered: int
    pages_analyzed: int
    ecommerce_verified: int
    stores_over_threshold: int
    minimum_active_ads: int
    advertisers: list[dict]  # qualifying SMALL STORES (ecommerce_score + minimum_active_ads passed,
    # excludes known mega-brands/marketplaces) — this is the only pool used for rankings,
    # Deep Dive, Longest Running Ads, and the CSV/JSON advertiser export.
    all_advertisers: list[dict]  # every advertiser discovered, for "universo analizado"
    presence_ranking: list[RankedAdvertiser]
    acceleration_ranking: list[RankedAdvertiser]
    format_counts: dict
    creative_reference_advertisers: list[dict] = field(default_factory=list)
    # Known mega-brands/marketplaces (SHEIN, Mercado Libre, ...) — per operator instruction,
    # never treated as a store example, but their ads still feed the aggregate creative-
    # pattern sections (Top Hooks/Ángulos/Ofertas/Productos, format strategy, saturation)
    # since those patterns are real market signal. See classifiers/brand_exclusion.py.
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _count_by(values: list[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        if not v:
            continue
        counts[v] = counts.get(v, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _top_n(counts: dict[str, int], n: int = 10) -> list[tuple[str, int]]:
    return list(counts.items())[:n]


def _fmt_pairs(pairs: list[tuple[str, int]]) -> str:
    """Renders [('demonstration', 173), ('question', 131)] as a readable
    'demonstration (173) · question (131)' instead of a raw Python list-of-tuples."""
    if not pairs:
        return "not_available"
    return " · ".join(f"{label} ({count})" for label, count in pairs)


def _ads_link(
    page_id: str | None, oldest_active_ad_url: str | None, *, page_name: str | None = None, market: str | None = None
) -> tuple[str | None, bool]:
    """Returns (url, is_page_level). Prefers the real "see all ads from this Page" link;
    when the page_id isn't a real Facebook ID (mock/scraped sources — see
    meta_ad_library_page_url), links straight to the Ad Library's results LIST filtered by
    the store's own name, rather than opening a specific ad's detail modal."""
    page_url = meta_ad_library_page_url(page_id)
    if page_url:
        return page_url, True
    if page_name and market:
        return meta_ad_library_store_search_url(page_name, market), False
    if oldest_active_ad_url:
        return oldest_active_ad_url, False
    return None, False


def _enrich_ranking(ranking: list[RankedAdvertiser], advertisers_by_page_id: dict, *, market: str | None = None) -> list[dict]:
    """Attaches store/ad-library links to each ranking row for the report tables, so
    'Marca' rows are directly clickable instead of requiring a lookup elsewhere."""
    enriched = []
    for row in ranking:
        adv = advertisers_by_page_id.get(row.page_id, {})
        ads_url, is_page_level = _ads_link(
            row.page_id, adv.get("oldest_active_ad_url"), page_name=row.page_name, market=market
        )
        enriched.append(
            {
                "rank": row.rank,
                "page_name": row.page_name,
                "score": row.score,
                "store_url": adv.get("store_url"),
                "ads_library_page_url": ads_url,
                "ads_library_is_page_level": is_page_level,
                "shopify_detected": adv.get("shopify_detected"),
            }
        )
    return enriched


def _all_active_ads(advertisers: list[dict]) -> list[NormalizedAd]:
    ads: list[NormalizedAd] = []
    for row in advertisers:
        ads.extend(a for a in row.get("_ads", []) if a.active)
    return ads


def _build_context(bundle: ReportBundle) -> dict:
    # Two pools, per operator instruction on mega-brands/marketplaces (SHEIN, Mercado Libre, ...):
    #   store_ads     -> qualifying small stores ONLY. Used anywhere a specific brand/store is
    #                    named or ranked (Longest Running Ads, Deep Dive, rankings, insights).
    #   creative_ads  -> store_ads + excluded mega-brands. Used ONLY for aggregate, brand-blind
    #                    creative-pattern stats (Top Hooks/Ángulos/Ofertas/Productos, format
    #                    strategy, saturation) — those are legitimate market signal either way.
    store_ads = _all_active_ads(bundle.advertisers)
    creative_ads = store_ads + _all_active_ads(bundle.creative_reference_advertisers)
    total_ads = len(store_ads)
    reference_brand_names = sorted({r["page_name"] for r in bundle.creative_reference_advertisers})

    hooks = _count_by([a.hook_type for a in creative_ads])
    angles = _count_by([a.creative_angle for a in creative_ads])
    offers = _count_by([a.offer_type for a in creative_ads])
    products = _count_by([a.product for a in creative_ads])

    longest_running = sorted((a for a in store_ads if a.age_days is not None), key=lambda a: -a.age_days)[:10]

    # Saturation: group active ads by product / (hook, angle) combo, each item carrying page_id.
    ads_by_product: dict[str, list[dict]] = {}
    ads_by_combo: dict[str, list[dict]] = {}
    for a in creative_ads:
        if a.product:
            ads_by_product.setdefault(a.product, []).append({"page_id": a.page_id})
        combo = f"{a.hook_type or 'unknown'} + {a.creative_angle or 'unknown'}"
        ads_by_combo.setdefault(combo, []).append({"page_id": a.page_id})

    saturation_products = product_saturation(ads_by_product)[:10]
    saturation_creative = creative_saturation(ads_by_combo)[:10]

    def _format_strategy(fmt: str) -> dict:
        subset = [a for a in creative_ads if a.format.value == fmt]
        return {
            "count": len(subset),
            "top_hooks": _top_n(_count_by([a.hook_type for a in subset]), 5),
            "top_angles": _top_n(_count_by([a.creative_angle for a in subset]), 5),
            "top_offers": _top_n(_count_by([a.offer_type for a in subset]), 5),
        }

    video_strategy = _format_strategy("video")
    image_strategy = _format_strategy("image")
    carousel_strategy = _format_strategy("carousel")

    # Opportunities (section 17): a simple, transparent heuristic — products with low
    # saturation (BAJA) that still have at least 2 distinct advertisers, i.e. there IS
    # demand signal but few competitors serving it within the analyzed sample. Framed as
    # HIPOTESIS, never a guarantee.
    opportunities = [
        s for s in product_saturation(ads_by_product) if s.level == "BAJA" and s.distinct_brands >= 2
    ][:8]

    insight_stats = {
        "ugc_flags": [a.ugc_detected for a in store_ads],
        "demonstration_flags": [a.demonstration_detected for a in store_ads],
        "testimonial_flags": [a.testimonial_detected for a in store_ads],
        "total_ads": total_ads,
        "dominant_hook_label": next(iter(hooks), None),
        "dominant_hook_count": next(iter(hooks.values()), 0),
        "hook_pattern_matches": sum(1 for a in store_ads if a.hook_type is not None),
    }
    insights = build_niche_insights(insight_stats)

    claims_flagged = [
        {"ad_id": a.ad_id, "page_name": a.page_name, "flags": a.claims_risk_flags}
        for a in store_ads
        if a.claims_risk_flags
    ]
    is_claims_sensitive = bundle.niche.upper() in CLAIMS_SENSITIVE_NICHES

    # Note on creative families in this report: family membership (ad_id -> family_key) is
    # computed and persisted to the DB's `creative_families` table by the orchestrator, but
    # isn't threaded back onto NormalizedAd objects here. The report's "familias creativas"
    # section therefore reads a hook+product combo as a readable proxy for concept grouping;
    # the authoritative family assignments are queryable from the database directly.
    advertisers_by_page_id = {a["page_id"]: a for a in bundle.advertisers}

    deep_dives = []
    for rank_row in bundle.presence_ranking:
        adv = advertisers_by_page_id.get(rank_row.page_id)
        if not adv:
            continue
        adv_ads = [a for a in adv.get("_ads", []) if a.active]
        adv_hooks = _top_n(_count_by([a.hook_type for a in adv_ads]), 5)
        adv_angles = _top_n(_count_by([a.creative_angle for a in adv_ads]), 5)
        adv_offers = _top_n(_count_by([a.offer_type for a in adv_ads]), 5)
        adv_products = _top_n(_count_by([a.product for a in adv_ads]), 5)

        summary_bits = []
        if adv["dominant_format"]:
            summary_bits.append(f"El formato predominante observado es {adv['dominant_format']}.")
        if adv_hooks:
            summary_bits.append(f"El hook más repetido en la muestra es '{adv_hooks[0][0]}' ({adv_hooks[0][1]} anuncios).")
        if adv["reference_window_ratio"]:
            summary_bits.append(
                f"El {round(adv['reference_window_ratio']*100)}% de sus anuncios activos con fecha conocida "
                f"llevan entre 30 y 90 días corriendo, la ventana de referencia usada para esta auditoría."
            )
        deep_dive_ads_url, deep_dive_is_page_level = _ads_link(
            adv["page_id"], adv.get("oldest_active_ad_url"), page_name=adv.get("page_name"), market=bundle.market
        )
        deep_dives.append(
            {
                "rank": rank_row.rank,
                "page_id": adv["page_id"],
                "page_name": adv["page_name"],
                "fanpage_url": adv.get("fanpage_url"),
                "store_url": adv.get("store_url"),
                "ads_library_page_url": deep_dive_ads_url,
                "ads_library_is_page_level": deep_dive_is_page_level,
                "niche": adv["niche"],
                "subniche": adv.get("subniche") or "unknown",
                "shopify_detected": adv["shopify_detected"],
                "active_ad_count": adv["active_ad_count"],
                "video_count": adv["video_count"],
                "image_count": adv["image_count"],
                "carousel_count": adv["carousel_count"],
                "oldest_active_ad_url": adv["oldest_active_ad_url"] or "not_available",
                "oldest_active_ad_age_days": adv["oldest_active_ad_age_days"],
                "median_ad_age": adv["median_ad_age"],
                "ads_over_14_days": adv["ads_over_14_days"],
                "ads_over_30_days": adv["ads_over_30_days"],
                "ads_over_60_days": adv["ads_over_60_days"],
                "top_hooks": adv_hooks,
                "top_angles": adv_angles,
                "top_offers": adv_offers,
                "top_products": adv_products,
                "scale_signal_score": adv["scale_signal_score"],
                "confidence_score": adv["confidence_score"],
                "growth_percentage": adv.get("growth_percentage"),
                "summary": " ".join(summary_bits) if summary_bits else "Datos insuficientes para un resumen.",
            }
        )

    return {
        "niche": bundle.niche,
        "market": bundle.market,
        "run_uuid": bundle.run_uuid,
        "source_name": bundle.source_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages_discovered": bundle.pages_discovered,
        "pages_analyzed": bundle.pages_analyzed,
        "ecommerce_verified": bundle.ecommerce_verified,
        "stores_over_threshold": bundle.stores_over_threshold,
        "minimum_active_ads": bundle.minimum_active_ads,
        "total_ads_analyzed": total_ads,
        "format_counts": bundle.format_counts,
        "presence_ranking": _enrich_ranking(bundle.presence_ranking, advertisers_by_page_id, market=bundle.market),
        "acceleration_ranking": _enrich_ranking(bundle.acceleration_ranking, advertisers_by_page_id, market=bundle.market),
        "advertisers": bundle.advertisers,
        "reference_brand_names": reference_brand_names,
        "top_hooks": _top_n(hooks),
        "top_angles": _top_n(angles),
        "top_offers": _top_n(offers),
        "top_products": _top_n(products),
        "longest_running": longest_running,
        "saturation_products": saturation_products,
        "saturation_creative": saturation_creative,
        "video_strategy": video_strategy,
        "image_strategy": image_strategy,
        "carousel_strategy": carousel_strategy,
        "opportunities": opportunities,
        "insights": insights,
        "claims_flagged": claims_flagged,
        "is_claims_sensitive_niche": is_claims_sensitive,
        "deep_dives": deep_dives,
        "warnings": bundle.warnings,
        "errors": bundle.errors,
        "source_notes": _source_notes(bundle.source_name),
    }


def _source_notes(source_name: str) -> str:
    notes = {
        "mock": (
            "Fuente MOCK: datos sintéticos deterministas usados solo para demostrar que el pipeline "
            "completo funciona end-to-end sin red. NO representan competidores reales — no usar para "
            "decisiones de negocio."
        ),
        "meta_graph_api": "Fuente: Meta Ad Library API oficial (graph.facebook.com/ads_archive).",
        "meta_web_scraper": (
            "Fuente: scraping best-effort de la interfaz pública de Meta Ad Library. Sujeto a cambios "
            "de HTML por parte de Meta; campos no confirmados se marcan not_verified."
        ),
        "database": (
            "Reporte regenerado desde datos ya recolectados en una ejecución anterior de `eci research` "
            "(no se volvió a consultar ninguna fuente externa)."
        ),
    }
    return notes.get(source_name, "Fuente no documentada.")


def _slugify(value: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in value).strip("_")


def _run_dir(bundle: ReportBundle) -> Path:
    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dir_name = f"{date_slug}_{bundle.market}_{_slugify(bundle.niche)}"
    path = REPORTS_DIR / dir_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _render(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt_pairs"] = _fmt_pairs
    env.globals["ad_library_page_url"] = meta_ad_library_page_url
    template = env.get_template(template_name)
    return template.render(**context)


def _write_csv(path: Path, advertisers: list[dict]) -> None:
    fields = [
        "page_id", "page_name", "fanpage_url", "store_url", "ads_library_page_url",
        "oldest_active_ad_url", "niche", "subniche", "active_ad_count",
        "video_count", "image_count", "carousel_count", "oldest_active_ad_age_days",
        "median_ad_age", "ads_over_30_days", "ads_over_60_days", "ads_over_90_days",
        "shopify_detected", "ecommerce_score", "scale_signal_score", "confidence_score",
        "dominant_format", "dominant_hook", "dominant_angle", "dominant_offer",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in advertisers:
            values = {k: row.get(k) for k in fields}
            ads_url, _is_page_level = _ads_link(
                row["page_id"], row.get("oldest_active_ad_url"), page_name=row.get("page_name"), market=row.get("country")
            )
            values["ads_library_page_url"] = ads_url
            writer.writerow(values)


def _write_json(path: Path, context: dict) -> None:
    def default(obj):
        if hasattr(obj, "model_dump"):  # pydantic BaseModel (NormalizedAd, etc.)
            return obj.model_dump(mode="json")
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return str(obj)

    serializable = dict(context)
    serializable["advertisers"] = [
        {k: v for k, v in row.items() if not k.startswith("_")} for row in context.get("advertisers", [])
    ]
    path.write_text(json.dumps(serializable, default=default, ensure_ascii=False, indent=2), encoding="utf-8")


def build_master_report(market: str, session) -> Path:
    """Section 39. Reads already-persisted `advertisers`/`ads` rows (grouped by niche) from
    the DB — no new network calls, no recalculation, purely an aggregation of prior runs."""
    from eci.database.models import Ad, Advertiser

    rows = session.query(Advertiser).filter_by(country=market).all()
    settings = get_settings()

    by_niche: dict[str, list] = {}
    for r in rows:
        if r.active_ad_count < settings.minimum_active_ads or r.ecommerce_score < settings.ecommerce_score_minimum:
            continue
        by_niche.setdefault(r.niche, []).append(r)

    niches = []
    for niche, advertisers in sorted(by_niche.items()):
        total_ads = sum(a.active_ad_count for a in advertisers)
        video = sum(a.video_count for a in advertisers)
        image = sum(a.image_count for a in advertisers)
        carousel = sum(a.carousel_count for a in advertisers)
        fmt_total = max(video + image + carousel, 1)
        oldest = max((a.oldest_active_ad_age_days for a in advertisers if a.oldest_active_ad_age_days), default=None)
        hooks = _count_by([a.dominant_hook for a in advertisers])
        offers = _count_by([a.dominant_offer for a in advertisers])

        page_ids = [a.page_id for a in advertisers]
        ad_products = [
            product
            for (product,) in session.query(Ad.product).filter(Ad.page_id.in_(page_ids), Ad.active.is_(True)).all()
        ]
        products = _count_by(ad_products)

        date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        niches.append(
            {
                "niche": niche,
                "advertisers_count": len(advertisers),
                "total_ads": total_ads,
                "shopify_count": sum(1 for a in advertisers if a.shopify_detected),
                "video_pct": round(video / fmt_total * 100, 1),
                "image_pct": round(image / fmt_total * 100, 1),
                "carousel_pct": round(carousel / fmt_total * 100, 1),
                "oldest_ad_days": oldest,
                "avg_scale_signal": round(sum(a.scale_signal_score for a in advertisers) / len(advertisers), 1)
                if advertisers
                else 0.0,
                "top_hooks": list(_top_n(hooks, 5)),
                "top_offers": list(_top_n(offers, 5)),
                "top_products": list(_top_n(products, 5)),
                "report_relative_path": f"../{date_slug}_{market}_{_slugify(niche)}/report.html",
            }
        )

    context = {"market": market, "generated_at": datetime.now(timezone.utc).isoformat(), "niches": niches}
    content = _render("master_report.md.j2", context)

    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"{date_slug}_{market}_MASTER"
    path.mkdir(parents=True, exist_ok=True)
    (path / "master_report.md").write_text(content, encoding="utf-8")
    body_html = md.markdown(content, extensions=["tables", "fenced_code"])
    html = _render("report_shell.html.j2", {"niche": "MASTER", "market": market, "body": body_html})
    (path / "master_report.html").write_text(html, encoding="utf-8")
    return path / "master_report.md"


def write_reports(bundle: ReportBundle) -> Path:
    context = _build_context(bundle)
    run_dir = _run_dir(bundle)

    md_content = _render("niche_report.md.j2", context)
    (run_dir / "report.md").write_text(md_content, encoding="utf-8")

    body_html = md.markdown(md_content, extensions=["tables", "fenced_code"])
    html_content = _render("report_shell.html.j2", {**context, "body": body_html})
    (run_dir / "report.html").write_text(html_content, encoding="utf-8")

    _write_csv(run_dir / "advertisers.csv", bundle.advertisers)

    json_context = dict(context)
    json_context["advertisers"] = bundle.advertisers
    _write_json(run_dir / "report.json", json_context)

    return run_dir / "report.md"

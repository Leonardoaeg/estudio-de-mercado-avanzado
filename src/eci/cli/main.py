"""CLI — section 40. `eci research`, `eci research-all`, `eci rank`, `eci trends`,
`eci report`, `eci report-all`, all with `--market`, `--minimum-ads`, `--shopify-only`.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from eci.config import get_settings
from eci.database.engine import get_session
from eci.database.migrate import apply_migrations
from eci.database.models import Advertiser, RankingRecord
from eci.pipeline.orchestrator import RunConfig, run_research
from eci.reports.docx_export import build_docx
from eci.reports.generator import ReportBundle, build_master_report, write_reports
from eci.reports.library import build_library
from eci.sources import available_sources
from eci.trends.trend_engine import SnapshotWindow, build_trend_report

app = typer.Typer(add_completion=False, help="Ecommerce Creative Intelligence (ECI) CLI")
console = Console()


def _niches() -> list[str]:
    return list(get_settings().niches.keys())


@app.command()
def research(
    niche: str = typer.Option(..., help="TEXTIL | SALUD | TECNOLOGIA | BELLEZA | SUPLEMENTOS"),
    market: str = typer.Option(None, help="Country code, e.g. CO"),
    minimum_ads: int = typer.Option(None, "--minimum-ads", help="Overrides config/settings.yaml minimum_active_ads"),
    source: str = typer.Option("mock", help=f"One of: {', '.join(available_sources())}"),
    shopify_only: bool = typer.Option(False, "--shopify-only"),
):
    """`eci research --niche textil --market CO --minimum-ads 50`"""
    settings = get_settings()
    market = market or settings.market
    config = RunConfig(
        niche=niche.upper(),
        market=market.upper(),
        source_name=source,
        minimum_active_ads=minimum_ads,
        shopify_only=shopify_only,
    )
    console.print(f"[bold]Iniciando research[/bold] niche={config.niche} market={config.market} source={source}")
    result = run_research(config)

    console.print(f"Run: {result.run_uuid} — stage final: {result.stage}")
    console.print(
        f"Páginas descubiertas: {result.pages_discovered} · analizadas: {result.pages_analyzed} · "
        f"ecommerce verificadas: {result.ecommerce_verified} · sobre umbral: {result.stores_over_threshold}"
    )
    console.print(f"Anuncios recolectados: {result.ads_collected} — {result.format_counts}")
    if result.errors:
        console.print(f"[red]Errores ({len(result.errors)}):[/red] {result.errors}")
    if result.warnings:
        console.print(f"[yellow]Advertencias ({len(result.warnings)}):[/yellow] {len(result.warnings)}")
    if result.report_path:
        console.print(f"[green]Reporte:[/green] {result.report_path}")


@app.command("research-all")
def research_all(
    market: str = typer.Option(None),
    minimum_ads: int = typer.Option(None, "--minimum-ads"),
    source: str = typer.Option("mock"),
    shopify_only: bool = typer.Option(False, "--shopify-only"),
):
    """`eci research-all --market CO [--shopify-only]`"""
    for niche in _niches():
        research(niche=niche, market=market, minimum_ads=minimum_ads, source=source, shopify_only=shopify_only)


@app.command()
def rank(
    niche: str = typer.Option(...),
    market: str = typer.Option(None),
):
    """`eci rank --niche textil` — prints the two most recently computed rankings."""
    settings = get_settings()
    market = (market or settings.market).upper()
    apply_migrations()
    session = get_session()
    try:
        for ranking_type, title in (("presence", "Highest Advertising Presence"), ("acceleration", "Fastest Advertising Acceleration")):
            rows = (
                session.query(RankingRecord)
                .filter_by(niche=niche.upper(), market=market, ranking_type=ranking_type)
                .order_by(RankingRecord.rank)
                .all()
            )
            table = Table(title=f"{title} — {niche.upper()} ({market})")
            table.add_column("Rank")
            table.add_column("Marca")
            table.add_column("Score")
            for r in rows:
                table.add_row(str(r.rank), r.page_name, str(r.score))
            console.print(table)
            if not rows:
                console.print("[dim]Sin datos — ejecuta `eci research` primero.[/dim]")
    finally:
        session.close()


@app.command()
def trends(
    niche: str = typer.Option(...),
    market: str = typer.Option(None),
):
    """`eci trends --niche suplementos` — compares the two most recent snapshots per advertiser."""
    from eci.database.models import Snapshot

    settings = get_settings()
    market = (market or settings.market).upper()
    apply_migrations()
    session = get_session()
    try:
        pages = [
            pid
            for (pid,) in session.query(Snapshot.page_id).filter_by(niche=niche.upper(), market=market).distinct()
        ]
        if not pages:
            console.print("[dim]Sin snapshots todavía — ejecuta `eci research` al menos una vez.[/dim]")
            return

        baseline_counts: dict[str, int] = {}
        current_counts: dict[str, int] = {}
        for page_id in pages:
            snaps = (
                session.query(Snapshot)
                .filter_by(page_id=page_id)
                .order_by(Snapshot.taken_at.desc())
                .limit(2)
                .all()
            )
            if len(snaps) < 2:
                continue
            current, baseline = snaps[0], snaps[1]
            for product in current.products or []:
                current_counts[product] = current_counts.get(product, 0) + 1
            for product in baseline.products or []:
                baseline_counts[product] = baseline_counts.get(product, 0) + 1

        window_current = SnapshotWindow(period_start=None, period_end=None, counts_by_dimension={"product": current_counts})
        window_baseline = SnapshotWindow(period_start=None, period_end=None, counts_by_dimension={"product": baseline_counts})
        report = build_trend_report(window_baseline, window_current)

        table = Table(title=f"Advertising Trends (producto) — {niche.upper()} ({market})")
        table.add_column("Producto")
        table.add_column("Antes")
        table.add_column("Ahora")
        table.add_column("Variación %")
        for trend in report.get("product", [])[:20]:
            table.add_row(
                trend.label,
                str(trend.baseline_count),
                str(trend.current_count),
                "NUEVO" if trend.is_new else f"{trend.variation_percentage}%",
            )
        console.print(table)
        if not report.get("product"):
            console.print("[dim]Se necesitan al menos 2 snapshots por marca (dos ejecuciones de `eci research` en fechas distintas).[/dim]")
    finally:
        session.close()


@app.command()
def report(
    niche: str = typer.Option(...),
    market: str = typer.Option(None),
    minimum_ads: int = typer.Option(None, "--minimum-ads", help="Overrides config/settings.yaml minimum_active_ads"),
):
    """`eci report --niche textil --market CO` — regenerates the report from data already
    in the database (does not re-collect ads; run `eci research` first)."""
    settings = get_settings()
    market = (market or settings.market).upper()
    threshold = minimum_ads if minimum_ads is not None else settings.minimum_active_ads
    apply_migrations()
    session = get_session()
    try:
        from eci.classifiers.brand_exclusion import is_excluded_brand
        from eci.database.models import Ad
        from eci.models.schemas import AdFormat, NormalizedAd
        from eci.ranking.rankers import rank_by_acceleration, rank_by_presence

        all_advertisers = (
            session.query(Advertiser)
            .filter_by(niche=niche.upper(), country=market)
            .filter(Advertiser.ecommerce_score >= settings.ecommerce_score_minimum)
            .all()
        )
        # Mega-brands/marketplaces (SHEIN, Mercado Libre, ...) never count as a qualifying
        # "small store" example, regardless of ad volume — see classifiers/brand_exclusion.py.
        advertisers = [
            a
            for a in all_advertisers
            if a.active_ad_count >= threshold and not is_excluded_brand(a.page_name)[0]
        ]
        reference_advertisers = [a for a in all_advertisers if is_excluded_brand(a.page_name)[0] and a.active_ad_count > 0]
        if not advertisers:
            console.print("[dim]Sin marcas calificadas en la base para este nicho/mercado — ejecuta `eci research` primero.[/dim]")
            raise typer.Exit(code=1)

        def _to_row(adv: Advertiser) -> dict:
            ad_rows = session.query(Ad).filter_by(page_id=adv.page_id).all()
            normalized_ads = [
                NormalizedAd(
                    ad_id=a.ad_id, source_name=a.source_name, page_id=a.page_id, page_name=a.page_name,
                    ad_library_url=a.ad_library_url, active=a.active, start_date=a.start_date, age_days=a.age_days,
                    format=AdFormat(a.format), primary_text=a.primary_text, headline=a.headline,
                    description=a.description, cta=a.cta, landing_url=a.landing_url,
                    final_landing_url=a.final_landing_url, product=a.product, product_category=a.product_category,
                    price=a.price, old_price=a.old_price, discount=a.discount, offer_type=a.offer_type,
                    hook=a.hook, hook_type=a.hook_type, creative_angle=a.creative_angle,
                    creative_style=a.creative_style, ugc_detected=a.ugc_detected,
                    testimonial_detected=a.testimonial_detected, demonstration_detected=a.demonstration_detected,
                    problem_solution_detected=a.problem_solution_detected, comparison_detected=a.comparison_detected,
                    creative_fingerprint=a.creative_fingerprint, claims_risk_flags=a.claims_risk_flags or [],
                    niche=a.niche, subniche=a.subniche, confidence=a.confidence, raw_payload=a.raw_payload or {},
                )
                for a in ad_rows
            ]
            row = {c.name: getattr(adv, c.name) for c in Advertiser.__table__.columns}
            row["_ads"] = normalized_ads
            return row

        rows = [_to_row(adv) for adv in advertisers]
        reference_rows = [_to_row(adv) for adv in reference_advertisers]
        all_rows = rows + reference_rows

        presence_rank = rank_by_presence(rows, top_n=10)
        acceleration_rank = rank_by_acceleration(rows, top_n=10)

        bundle = ReportBundle(
            niche=niche.upper(), market=market, run_uuid="regenerated", source_name="database",
            pages_discovered=len(all_rows), pages_analyzed=len(all_rows), ecommerce_verified=len(all_rows),
            stores_over_threshold=len(rows), minimum_active_ads=threshold,
            advertisers=rows, all_advertisers=all_rows, creative_reference_advertisers=reference_rows,
            presence_ranking=presence_rank, acceleration_ranking=acceleration_rank,
            format_counts={
                "video": sum(r["video_count"] for r in all_rows),
                "image": sum(r["image_count"] for r in all_rows),
                "carousel": sum(r["carousel_count"] for r in all_rows),
                "unknown": sum(r["unknown_format_count"] for r in all_rows),
            },
        )
        path = write_reports(bundle)
        console.print(f"[green]Reporte regenerado:[/green] {path}")
    finally:
        session.close()


@app.command("report-all")
def report_all(market: str = typer.Option(None), minimum_ads: int = typer.Option(None, "--minimum-ads")):
    """`eci report-all` — regenerates per-niche reports plus the MASTER comparison report."""
    settings = get_settings()
    market = (market or settings.market).upper()
    for niche in _niches():
        try:
            report(niche=niche, market=market, minimum_ads=minimum_ads)
        except typer.Exit:
            console.print(f"[dim]Saltando {niche}: sin datos.[/dim]")

    apply_migrations()
    session = get_session()
    try:
        path = build_master_report(market, session)
        console.print(f"[green]Informe maestro:[/green] {path}")
    finally:
        session.close()


@app.command()
def library(
    niche: str = typer.Option(...),
    market: str = typer.Option(None, help="Comma-separated markets, e.g. CO,MX,PE"),
    minimum_ad_age_days: int = typer.Option(30, "--minimum-ad-age-days", help="Only brands with an active ad running at least this many days"),
    top_n: int = typer.Option(10, "--top-n", help="Curated brand cap per niche"),
    must_include: str = typer.Option(None, "--must-include", help="Comma-separated store domains guaranteed a spot even if outside the natural top-N"),
    docx: bool = typer.Option(False, "--docx", help="Also export a professional Word (.docx) version alongside the HTML/JSON"),
):
    """`eci library --niche textil --market CO,MX --must-include icon-amsterdam.com,one4viceco.com`
    builds the curated "Biblioteca de Referentes": small independent stores with a proven
    (30+ day) running creative, excluding known mega-brands/marketplaces/shared platforms.
    Reads from data already in the database — run `eci research` for each market first.
    One HTML file (+ matching JSON) per niche in reports/biblioteca/; pass --docx for a
    Word version too.
    """
    settings = get_settings()
    markets = [m.strip().upper() for m in (market or settings.market).split(",") if m.strip()]
    must_include_domains = [d.strip() for d in must_include.split(",") if d.strip()] if must_include else None
    apply_migrations()
    session = get_session()
    try:
        path = build_library(
            niche, markets, session, min_ad_age_days=minimum_ad_age_days,
            top_n=top_n, must_include_domains=must_include_domains,
        )
        console.print(f"[green]Biblioteca generada:[/green] {path}")
        if docx:
            docx_path = build_docx(
                niche, markets, session, min_ad_age_days=minimum_ad_age_days,
                top_n=top_n, must_include_domains=must_include_domains,
            )
            console.print(f"[green]Word generado:[/green] {docx_path}")
    finally:
        session.close()


if __name__ == "__main__":
    app()

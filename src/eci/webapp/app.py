"""Radar de Ecommerce — the live web dashboard (operator, 2026-08-14: "necesito que sea funcional...
en localhost o en un dash... una aplicación... 100% funcional sin errores").

Everything here is a thin HTTP layer over code that already exists and is already tested
(reports/library.py's _build_library_context, analysis/product_viability.py's
analyze_product) — the webapp never re-implements business logic, it only serves it live
instead of writing it to a static file. Run with:

    uvicorn eci.webapp.app:app --reload --port 8000

or `eci serve` (see cli/main.py).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from eci.analysis.product_viability import analyze_product
from eci.classifiers.claims_risk import is_claims_sensitive_niche
from eci.config import get_settings
from eci.database.engine import get_session
from eci.database.migrate import apply_migrations
from eci.reports.library import _build_library_context, _scale_tier
from eci.reports.product_report import render_product_html
from datetime import datetime, timezone

TEMPLATES_DIR = Path(__file__).parent.parent / "reports" / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",)),
    trim_blocks=True,
    lstrip_blocks=True,
)

app = FastAPI(title="Radar de Ecommerce")


def _render(template_name: str, **context) -> HTMLResponse:
    template = _env.get_template(template_name)
    return HTMLResponse(template.render(**context))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    from eci.database.models import Advertiser

    apply_migrations()
    session = get_session()
    try:
        settings = get_settings()
        niches = []
        for code, info in settings.niches.items():
            rows = session.query(Advertiser).filter_by(niche=code).all()
            markets = sorted({a.country for a in rows if a.country})
            scale_alta = sum(1 for a in rows if _scale_tier(a.active_ad_count) == "alta")
            niches.append(
                {
                    "code": code,
                    "label": info.get("label", code.title()),
                    "has_data": len(rows) > 0,
                    "total_advertisers": len(rows),
                    "scale_alta_count": scale_alta,
                    "markets": markets,
                    "href": f"/nicho/{code}",
                }
            )
        return _render("dashboard.html.j2", niches=niches)
    finally:
        session.close()


@app.get("/nicho/{niche}", response_class=HTMLResponse)
def niche_view(niche: str):
    from eci.database.models import Advertiser

    apply_migrations()
    session = get_session()
    try:
        niche = niche.upper()
        settings = get_settings()
        if niche not in settings.niches:
            return HTMLResponse(f"<h1>Nicho '{niche}' no existe</h1><p><a href='/'>Volver</a></p>", status_code=404)

        markets = sorted({a.country for a in session.query(Advertiser).filter_by(niche=niche).all() if a.country})
        if not markets:
            markets = [settings.market]

        context = _build_library_context(
            niche,
            markets,
            session,
            niche_href_fn=lambda code: f"/nicho/{code}",
        )
        context["generated_at"] = datetime.now(timezone.utc).isoformat()
        return _render("library.html.j2", **context)
    finally:
        session.close()


@app.get("/producto", response_class=HTMLResponse)
def product_form(niche: str | None = None):
    from eci.database.models import Advertiser

    apply_migrations()
    session = get_session()
    try:
        settings = get_settings()
        niches = [{"code": code, "label": info.get("label", code.title())} for code, info in settings.niches.items()]
        selected_niche = niche or (niches[0]["code"] if niches else None)
        markets = sorted({a.country for a in session.query(Advertiser).all() if a.country}) or [settings.market]
        return _render(
            "analyze_form.html.j2",
            niches=niches,
            selected_niche=selected_niche,
            available_markets=markets,
            selected_markets=None,
            form_values=None,
            error=None,
        )
    finally:
        session.close()


@app.post("/producto", response_class=HTMLResponse)
def product_analyze(
    niche: str = Form(...),
    product: str = Form(...),
    market: list[str] = Form(default_factory=list),
    cost_price: str = Form(""),
    target_price: str = Form(""),
    currency: str = Form(""),
):
    from eci.database.models import Advertiser

    apply_migrations()
    session = get_session()
    try:
        settings = get_settings()
        niches = [{"code": code, "label": info.get("label", code.title())} for code, info in settings.niches.items()]
        available_markets = sorted({a.country for a in session.query(Advertiser).all() if a.country}) or [settings.market]
        form_values = {"product": product, "cost_price": cost_price, "target_price": target_price, "currency": currency}

        markets = market or available_markets[:1]

        def _parse_float(raw: str) -> float | None:
            raw = (raw or "").strip()
            if not raw:
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        cost = _parse_float(cost_price)
        target = _parse_float(target_price)
        if cost_price.strip() and cost is None:
            return _render(
                "analyze_form.html.j2", niches=niches, selected_niche=niche, available_markets=available_markets,
                selected_markets=markets, form_values=form_values,
                error="El costo debe ser un número (usá punto para decimales, ej. 35000 o 35000.50).",
            )
        if target_price.strip() and target is None:
            return _render(
                "analyze_form.html.j2", niches=niches, selected_niche=niche, available_markets=available_markets,
                selected_markets=markets, form_values=form_values,
                error="El precio de venta debe ser un número (usá punto para decimales).",
            )
        if not product.strip():
            return _render(
                "analyze_form.html.j2", niches=niches, selected_niche=niche, available_markets=available_markets,
                selected_markets=markets, form_values=form_values,
                error="Describí el producto para poder analizarlo.",
            )

        currency_note = f"Precios en {currency.strip()}" if currency.strip() else (
            "moneda no especificada — asumida consistente entre costo y precio de venta"
        )

        result = analyze_product(
            niche, markets, session,
            product_description=product.strip(),
            cost_price=cost, target_price=target,
            currency_note=currency_note,
        )
        generated_at = datetime.now(timezone.utc).isoformat()
        html = render_product_html(
            result, generated_at,
            niche_href_fn=lambda code: f"/nicho/{code}",
            include_nav=True,
            new_analysis_href="/producto",
        )
        return HTMLResponse(html)
    finally:
        session.close()

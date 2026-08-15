"""Renders the "Análisis de Viabilidad de Producto" (src/eci/analysis/product_viability.py)
as an HTML page + JSON, matching the same dark-dashboard visual language as the Biblioteca
de Referentes so the two feel like one suite, not two different tools."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from eci.analysis.product_viability import ProductViabilityResult, analyze_product
from eci.config import REPORTS_DIR, get_settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
PRODUCT_REPORTS_DIR = REPORTS_DIR / "analisis_producto"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",)),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _slugify(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "producto"


def render_product_html(
    result: ProductViabilityResult,
    generated_at: str,
    *,
    niche_href_fn=lambda code: f"{code}.html",
    include_nav: bool = False,
    new_analysis_href: str | None = None,
) -> str:
    """The actual HTML render, factored out so both the static build (writes a file) and
    the live webapp (renders straight into an HTTP response, no file I/O) use the exact
    same template and never drift apart. `include_nav=False` by default: a standalone
    static export doesn't need cross-niche nav links wired to app routes that won't exist
    on disk — only the live webapp passes include_nav=True."""
    all_niches = None
    if include_nav:
        all_niches = [
            {"code": code, "label": info.get("label", code.title()), "active": code == result.niche, "href": niche_href_fn(code)}
            for code, info in get_settings().niches.items()
        ]
    template = _env.get_template("product_viability.html.j2")
    return template.render(
        result=result, generated_at=generated_at, all_niches=all_niches, new_analysis_href=new_analysis_href
    )


def build_product_report(
    niche: str,
    markets: list[str],
    session,
    *,
    product_description: str,
    cost_price: float | None = None,
    target_price: float | None = None,
    currency_note: str = "moneda no especificada — asumida consistente entre costo y precio de venta",
) -> Path:
    result = analyze_product(
        niche,
        markets,
        session,
        product_description=product_description,
        cost_price=cost_price,
        target_price=target_price,
        currency_note=currency_note,
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    html = render_product_html(result, generated_at)

    PRODUCT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(product_description)
    date_tag = generated_at[:10]
    path = PRODUCT_REPORTS_DIR / f"{niche.upper()}_{slug}_{date_tag}.html"
    path.write_text(html, encoding="utf-8")

    payload = asdict(result)
    payload["generated_at"] = generated_at
    payload["competitors"] = [asdict(c) for c in result.top_competitors]
    del payload["top_competitors"]
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return path

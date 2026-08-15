"""MockSource — deterministic, offline, fixture-driven source.

Used by (a) the test suite, so classifiers/scoring/ranking/reports can be tested without
network access, and (b) `eci research --source mock`, which proves the whole pipeline is
wired correctly end-to-end without needing a Meta token or Playwright browsers installed.

Nothing here claims to be real market data — every advertiser/ad it returns has
`source_name="mock"`, and reports generated from it must be treated as a wiring
demonstration, not competitive intelligence.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from eci.models.schemas import RawAd
from eci.sources.base import AdLibrarySource, SourceFetchOutcome

_HOOK_TEMPLATES = [
    "¿Sigues sufriendo de {pain}? Esto te puede ayudar.",
    "Mira lo que pasó cuando probé {product} por 7 días.",
    "3 razones por las que {product} se agotó la semana pasada.",
    "No vas a creer el antes y después con {product}.",
    "Oferta por tiempo limitado: {product} con 30% off.",
]

_BODY_TEMPLATES = [
    "Miles de clientas ya lo probaron. Testimonio real de nuestra comunidad con {product}.",
    "Comparado con productos similares, {product} tiene mejor relación calidad-precio.",
    "Envío gratis y pago contra entrega disponible para {product}. Garantía de devolución 30 días.",
    "Edición limitada de {product}, quedan pocas unidades. Compra ahora con 2x1.",
    "Demostración en video de cómo usar {product} en menos de 1 minuto.",
]

_CTAS = ["Comprar ahora", "Ver más", "Enviar mensaje", "Comprar", "Más información"]
_PAINS = ["el dolor de espalda", "la piel opaca", "la falta de energía", "la ropa que no cierra"]

_FORMAT_WEIGHTS = [("video", 0.5), ("image", 0.35), ("carousel", 0.15)]


def synthetic_store_html(page_name: str, *, shopify: bool, n_products: int = 3) -> str:
    """Generates HTML equivalent in structure to a real store, for MockSource-driven runs.

    Lets `eci research --source mock` genuinely stay offline (no HTTP calls) end-to-end,
    matching IMPLEMENTATION_PLAN.md's claim, while still exercising the exact same
    ecommerce_validator/shopify_detector heuristics (score_html/detect_from_html) that run
    against real HTML for the real sources.
    """
    products_html = "".join(
        f'<div class="product-card">Producto {i+1} de {page_name} - $ {29900 + i*10000} COP '
        f'<button class="add-to-cart">Añadir al carrito</button></div>'
        for i in range(n_products)
    )
    shopify_markup = (
        """
        <link rel="stylesheet" href="https://cdn.shopify.com/s/files/1/0000/0000/t/1/assets/theme.css">
        <script>window.Shopify = window.Shopify || {}; Shopify.theme = {"name": "Dawn"};</script>
        <div class="shopify-section">header</div>
        """
        if shopify
        else ""
    )
    return f"""<!DOCTYPE html>
<html><head><title>{page_name}</title>{shopify_markup}</head>
<body>
  <div class="product-grid">{products_html}</div>
  <a href="/cart">Ver carrito</a>
  <p>Envío gratis a todo el país. Pago contra entrega disponible. Garantía de devolución 30 días.</p>
  <script type="application/ld+json">{{"@type": "Product", "name": "{page_name}"}}</script>
</body></html>"""


def _weighted_format(rng: random.Random) -> str:
    r = rng.random()
    acc = 0.0
    for fmt, weight in _FORMAT_WEIGHTS:
        acc += weight
        if r <= acc:
            return fmt
    return "image"


class MockSource(AdLibrarySource):
    name = "mock"

    def __init__(self, *, min_advertisers_per_keyword: int = 2, max_advertisers_per_keyword: int = 4):
        self.min_advertisers = min_advertisers_per_keyword
        self.max_advertisers = max_advertisers_per_keyword

    def is_available(self) -> tuple[bool, str | None]:
        return True, None

    def _seed_for(self, keyword: str, market: str) -> int:
        digest = hashlib.sha256(f"{keyword}|{market}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def search_ads(self, keyword: str, market: str, *, page_cursor: str | None = None) -> SourceFetchOutcome:
        if page_cursor is not None:
            # MockSource returns everything in a single page — pagination is a no-op here,
            # but the cursor contract is honored so the collector's loop logic is exercised too.
            return SourceFetchOutcome(ads=[], ok=True, exhausted=True)

        rng = random.Random(self._seed_for(keyword, market))
        n_advertisers = rng.randint(self.min_advertisers, self.max_advertisers)
        now = datetime.now(timezone.utc)
        ads: list[RawAd] = []

        slug_base = keyword.lower().replace(" ", "_")
        for advertiser_idx in range(n_advertisers):
            page_id = f"mock_{slug_base}_{advertiser_idx}"
            page_name = f"{keyword.title()} Store {advertiser_idx + 1}"
            # Skew: most advertisers small, a couple with high presence (>=50 ads) so the
            # "minimum_active_ads" filter and scoring actually have something to differentiate.
            n_ads = rng.choice([rng.randint(3, 25), rng.randint(30, 48), rng.randint(50, 140)])

            for ad_idx in range(n_ads):
                age = rng.choice(
                    [rng.randint(0, 13), rng.randint(14, 29), rng.randint(30, 90), rng.randint(91, 240)]
                )
                start_date = now - timedelta(days=age)
                product = f"{keyword} modelo {rng.randint(1, 5)}"
                fmt = _weighted_format(rng)
                hook = rng.choice(_HOOK_TEMPLATES).format(product=product, pain=rng.choice(_PAINS))
                body = rng.choice(_BODY_TEMPLATES).format(product=product)
                price = round(rng.uniform(29900, 189900), -2)

                ads.append(
                    RawAd(
                        ad_id=f"{page_id}_ad_{ad_idx}",
                        source_name=self.name,
                        page_id=page_id,
                        page_name=page_name,
                        ad_library_url=f"https://www.facebook.com/ads/library/?id={page_id}_ad_{ad_idx}",
                        active=True,
                        start_date=start_date.strftime("%Y-%m-%d"),
                        format_hint=fmt,
                        primary_text=f"{hook} {body}",
                        headline=product.title(),
                        description=body,
                        cta=rng.choice(_CTAS),
                        landing_url=f"https://{slug_base}-store{advertiser_idx}.myshopify.com/products/{product.replace(' ', '-')}",
                        raw_payload={"price": price, "mock": True},
                    )
                )
        return SourceFetchOutcome(ads=ads, ok=True, exhausted=True)

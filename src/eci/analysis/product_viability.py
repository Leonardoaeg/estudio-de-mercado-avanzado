"""Análisis de Viabilidad de Producto — operator request (2026-08-14): "un apartado donde
pueda hacer un análisis del producto que se quiera vender... identificar qué tipo de
producto es, características, nicho, subnicho... en qué precio le sale, qué precio lo va
a vender... si es viable y a qué nivel lo puede vender."

Given a free-text product description (+ niche, optional cost/target price), this module:
  1. classifies the product into a subniche using the SAME classifier the research
     pipeline uses (niche_classifier.classify_subniche_for_niche) — never a separate,
     inconsistent taxonomy;
  2. counts REAL competitors already advertising in that niche/subniche from data already
     in the database (run `eci research` first if the niche/market combo is empty) —
     unlike the curated "Biblioteca de Referentes", mega-brands/marketplaces are NOT
     excluded here: a competing SHEIN or Mercado Libre listing is exactly the kind of
     competition a seller needs to know about, just flagged so it reads differently from
     a small independent competitor;
  3. estimates a market price range by regex-extracting currency amounts out of those
     competitors' real ad copy (best-effort text parsing, not a guarantee — documented
     openly in the report, same honesty stance as claims_risk.py);
  4. gives a transparent, explainable verdict (saturation level + price positioning +
     margin health -> viability label), never a black-box single score.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from eci.classifiers.brand_exclusion import is_excluded_brand
from eci.classifiers.niche_classifier import classify_subniche_for_niche, get_subniche_seeds

# ---------------------------------------------------------------------------
# Price extraction — best-effort regex parsing of LATAM-style ad copy prices.
# Documented limitation: this is text heuristics, not a guaranteed-accurate figure.
# ---------------------------------------------------------------------------
_PRICE_TOKEN_RE = re.compile(
    r"(?:\$|USD|COP|MXN|PEN|CLP|ARS)\s?(\d(?:[\d.,]*\d)?)(?!\s?%)",
    re.IGNORECASE,
)
_MIN_PLAUSIBLE_PRICE = 1.0
_MAX_PLAUSIBLE_PRICE = 10_000_000.0


def _parse_price_token(raw: str) -> float | None:
    s = raw.strip()
    # A trailing 2-digit group after a separator, on an otherwise short number, reads as
    # cents (e.g. "45.50") — everything else is treated as thousands grouping (e.g. the
    # very common LATAM ad-copy style "$1,490 MXN" = mil cuatrocientos noventa, not 1.49).
    m = re.match(r"^(.*?)([.,])(\d{2})$", s)
    if m and len(re.sub(r"[.,]", "", m.group(1))) <= 3:
        integer_part = re.sub(r"[.,]", "", m.group(1)) or "0"
        try:
            return float(f"{integer_part}.{m.group(3)}")
        except ValueError:
            return None
    digits = re.sub(r"[.,]", "", s)
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def extract_prices(text: str | None) -> list[float]:
    """Returns every plausible price amount found in the text, in original order."""
    if not text:
        return []
    prices = []
    for match in _PRICE_TOKEN_RE.finditer(text):
        value = _parse_price_token(match.group(1))
        if value is not None and _MIN_PLAUSIBLE_PRICE <= value <= _MAX_PLAUSIBLE_PRICE:
            prices.append(value)
    return prices


# ---------------------------------------------------------------------------
# Saturation — same "simple, documented thresholds" philosophy as
# trends/saturation_engine.py, but at niche/subniche-competitor-count granularity
# rather than product-label granularity (we don't have a clean "product" field for
# arbitrary user-described products, but we DO have a reliable competitor count).
# ---------------------------------------------------------------------------
SATURATION_THRESHOLDS = {
    "ALTA": {"min_competitors": 15, "min_scale_alta": 3},
    "MEDIA": {"min_competitors": 6, "min_scale_alta": 1},
}


def _saturation_level(distinct_competitors: int, scale_alta_count: int) -> str:
    t = SATURATION_THRESHOLDS
    if distinct_competitors >= t["ALTA"]["min_competitors"] or scale_alta_count >= t["ALTA"]["min_scale_alta"]:
        return "ALTA"
    if distinct_competitors >= t["MEDIA"]["min_competitors"] or scale_alta_count >= t["MEDIA"]["min_scale_alta"]:
        return "MEDIA"
    return "BAJA"


def _price_position(target_price: float, market_prices: list[float]) -> str | None:
    if not market_prices:
        return None
    sorted_prices = sorted(market_prices)
    p25 = sorted_prices[len(sorted_prices) // 4]
    p75 = sorted_prices[min(len(sorted_prices) - 1, (len(sorted_prices) * 3) // 4)]
    if target_price < p25:
        return "más barato que la mayoría del mercado"
    if target_price > p75:
        return "más caro que la mayoría del mercado"
    return "dentro del rango de precios del mercado"


def _margin_health(cost_price: float, target_price: float) -> tuple[float, str]:
    if target_price <= 0:
        return 0.0, "precio de venta inválido (debe ser mayor a 0)"
    margin_pct = round((target_price - cost_price) / target_price * 100, 1)
    if margin_pct < 0:
        label = "margen negativo — vendería por debajo del costo"
    elif margin_pct < 20:
        label = "margen bajo — arriesgado si necesitás pautar en Meta Ads (el costo publicitario suele comerse un margen así de estrecho)"
    elif margin_pct < 40:
        label = "margen aceptable"
    else:
        label = "margen saludable"
    return margin_pct, label


def _verdict(saturation: str, margin_label: str | None, price_position: str | None) -> tuple[str, str]:
    """Returns (label, explanation). A small, transparent decision table — not a
    black-box score — so the report can always say exactly *why* it landed here."""
    margin_ok = margin_label is not None and "bajo" not in margin_label and "negativo" not in margin_label
    margin_bad = margin_label is not None and ("bajo" in margin_label or "negativo" in margin_label)

    if saturation == "BAJA" and not margin_bad:
        return (
            "Alta viabilidad",
            "Pocos competidores reales encontrados y el margen no es un problema — es un buen momento para probar el producto.",
        )
    if saturation == "ALTA" and margin_bad:
        return (
            "Baja viabilidad",
            "Mercado saturado (muchos competidores, algunos a gran escala) combinado con un margen ajustado — va a ser difícil competir en precio y en presupuesto publicitario a la vez.",
        )
    if saturation == "ALTA" and not margin_bad:
        return (
            "Viable con diferenciación",
            "Hay bastante competencia, pero el margen da espacio para pautar — necesitás un ángulo creativo o una propuesta de valor distinta a la de la mayoría, no competir solo por precio.",
        )
    if saturation == "MEDIA" and margin_bad:
        return (
            "Viable con ajustes",
            "La competencia todavía no es extrema, pero el margen actual deja poco margen de error — conviene revisar el precio de venta o el costo antes de escalar en ads.",
        )
    return (
        "Viable",
        "Nivel de competencia manejable y el margen no es una alarma — vale la pena una prueba controlada antes de escalar el presupuesto.",
    )


@dataclass
class CompetitorSummary:
    page_name: str
    active_ad_count: int
    scale_tier: str
    store_url: str | None
    is_mega_brand: bool
    market: str


@dataclass
class ProductViabilityResult:
    product_description: str
    niche: str
    markets: list[str]
    subniche: str | None
    subniche_confidence: float
    cost_price: float | None
    target_price: float | None
    currency_note: str
    total_competitors: int
    scale_alta_count: int
    scale_media_count: int
    scale_emergente_count: int
    mega_brand_competitors: int
    top_competitors: list[CompetitorSummary]
    market_price_samples: list[float]
    market_price_min: float | None
    market_price_median: float | None
    market_price_max: float | None
    price_position: str | None
    margin_pct: float | None
    margin_label: str | None
    saturation_level: str
    viability_label: str
    viability_explanation: str
    data_available: bool
    warnings: list[str] = field(default_factory=list)


def analyze_product(
    niche: str,
    markets: list[str],
    session,
    *,
    product_description: str,
    cost_price: float | None = None,
    target_price: float | None = None,
    currency_note: str = "moneda no especificada — asumida consistente entre costo y precio de venta",
    top_n_competitors: int = 8,
) -> ProductViabilityResult:
    from eci.database.models import Ad, Advertiser

    niche = niche.upper()
    warnings: list[str] = []

    subniche, subniche_confidence = classify_subniche_for_niche(product_description, niche)
    known_subniches = set(get_subniche_seeds(niche).keys())
    if subniche and subniche not in known_subniches:
        subniche = None  # only trust seed subniches for competitor filtering, not free-text guesses

    query = session.query(Advertiser).filter(
        Advertiser.niche == niche,
        Advertiser.country.in_([m.upper() for m in markets]),
    )
    if subniche:
        query = query.filter(Advertiser.subniche == subniche)
    advertisers = query.order_by(Advertiser.active_ad_count.desc()).all()

    if not advertisers and subniche:
        # Subniche filter might be too narrow if that specific pocket hasn't been
        # researched yet — fall back to the whole niche rather than reporting "0
        # competitors" when the real answer is "we haven't looked closely enough".
        warnings.append(
            f"No se encontraron competidores ya investigados en el subnicho '{subniche}' — "
            "se amplió la búsqueda a todo el nicho para no reportar 0 competidores por error."
        )
        advertisers = (
            session.query(Advertiser)
            .filter(Advertiser.niche == niche, Advertiser.country.in_([m.upper() for m in markets]))
            .order_by(Advertiser.active_ad_count.desc())
            .all()
        )

    data_available = len(advertisers) > 0
    if not data_available:
        warnings.append(
            f"No hay datos investigados todavía para {niche} en {', '.join(markets)} — corré "
            "`eci research` para ese nicho/mercado antes de repetir este análisis."
        )

    from eci.reports.library import _scale_tier  # reuse the exact same tier thresholds

    scale_counts = {"alta": 0, "media": 0, "emergente": 0}
    mega_brand_count = 0
    top_competitors: list[CompetitorSummary] = []
    page_ids: list[str] = []

    for adv in advertisers:
        tier = _scale_tier(adv.active_ad_count)
        scale_counts[tier] += 1
        excluded, reason = is_excluded_brand(adv.page_name)
        if excluded:
            mega_brand_count += 1
        page_ids.append(adv.page_id)
        if len(top_competitors) < top_n_competitors:
            top_competitors.append(
                CompetitorSummary(
                    page_name=adv.page_name,
                    active_ad_count=adv.active_ad_count,
                    scale_tier=tier,
                    store_url=adv.store_url,
                    is_mega_brand=excluded,
                    market=adv.country,
                )
            )

    # --- Market price range from competitors' real ad copy (best-effort) ---
    market_prices: list[float] = []
    if page_ids:
        texts = (
            session.query(Ad.primary_text)
            .filter(Ad.page_id.in_(page_ids), Ad.active.is_(True), Ad.primary_text.isnot(None))
            .all()
        )
        for (text,) in texts:
            market_prices.extend(extract_prices(text))

    # Text-regex price extraction occasionally grabs a stray small number that isn't
    # really a price (a rating, a quantity, "$10 de descuento adicional") — a single
    # $10 sitting next to a $74,900 median would visibly break trust in the whole
    # section. Filter out anything wildly far from the rest of the observed sample
    # (more than 50x below/above the median) before reporting min/median/max.
    if market_prices:
        rough_median = statistics.median(market_prices)
        lower_bound = rough_median / 50
        upper_bound = rough_median * 50
        filtered = [p for p in market_prices if lower_bound <= p <= upper_bound]
        dropped = len(market_prices) - len(filtered)
        if dropped:
            warnings.append(
                f"Se descartaron {dropped} precio(s) extraído(s) del texto de anuncios por ser "
                "atípicos frente al resto de la muestra (probablemente no eran precios reales, "
                "sino otro número en el copy)."
            )
        market_prices = filtered or market_prices

    price_min = min(market_prices) if market_prices else None
    price_median = round(statistics.median(market_prices), 2) if market_prices else None
    price_max = max(market_prices) if market_prices else None
    if not market_prices:
        warnings.append(
            "No se pudieron extraer precios del texto de los anuncios de la competencia "
            "(no siempre aparece el precio en el copy) — el rango de mercado queda sin datos."
        )

    price_position = None
    if target_price is not None and market_prices:
        price_position = _price_position(target_price, market_prices)

    margin_pct = None
    margin_label = None
    if cost_price is not None and target_price is not None:
        margin_pct, margin_label = _margin_health(cost_price, target_price)

    saturation = _saturation_level(len(advertisers), scale_counts["alta"])
    viability_label, viability_explanation = _verdict(saturation, margin_label, price_position)

    return ProductViabilityResult(
        product_description=product_description,
        niche=niche,
        markets=[m.upper() for m in markets],
        subniche=subniche,
        subniche_confidence=subniche_confidence,
        cost_price=cost_price,
        target_price=target_price,
        currency_note=currency_note,
        total_competitors=len(advertisers),
        scale_alta_count=scale_counts["alta"],
        scale_media_count=scale_counts["media"],
        scale_emergente_count=scale_counts["emergente"],
        mega_brand_competitors=mega_brand_count,
        top_competitors=top_competitors,
        market_price_samples=market_prices,
        market_price_min=price_min,
        market_price_median=price_median,
        market_price_max=price_max,
        price_position=price_position,
        margin_pct=margin_pct,
        margin_label=margin_label,
        saturation_level=saturation,
        viability_label=viability_label,
        viability_explanation=viability_explanation,
        data_available=data_available,
        warnings=warnings,
    )

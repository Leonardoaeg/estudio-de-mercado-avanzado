"""SaturationEngine — section 25. Flags when many advertisers converge on the same
product/hook/creative, using simple, documented thresholds (config-driven) rather than a
black-box score, so the report can always explain *why* something is labeled ALTA.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_THRESHOLDS = {
    "ALTA": {"min_brands": 10, "min_ads": 200},
    "MEDIA": {"min_brands": 5, "min_ads": 80},
}


@dataclass
class SaturationResult:
    label: str
    distinct_brands: int
    total_ads: int
    level: str  # ALTA | MEDIA | BAJA


def _classify_level(distinct_brands: int, total_ads: int, thresholds: dict) -> str:
    alta = thresholds.get("ALTA", DEFAULT_THRESHOLDS["ALTA"])
    media = thresholds.get("MEDIA", DEFAULT_THRESHOLDS["MEDIA"])
    if distinct_brands >= alta["min_brands"] or total_ads >= alta["min_ads"]:
        return "ALTA"
    if distinct_brands >= media["min_brands"] or total_ads >= media["min_ads"]:
        return "MEDIA"
    return "BAJA"


def product_saturation(
    ads_by_product: dict[str, list[dict]],
    *,
    thresholds: dict | None = None,
) -> list[SaturationResult]:
    """`ads_by_product`: {product_label: [ {page_id, ...}, ... ]}. distinct_brands is the
    count of unique page_ids advertising that product."""
    thresholds = thresholds or DEFAULT_THRESHOLDS
    results = []
    for product, ads in ads_by_product.items():
        brands = {ad["page_id"] for ad in ads}
        level = _classify_level(len(brands), len(ads), thresholds)
        results.append(SaturationResult(product, len(brands), len(ads), level))
    results.sort(key=lambda r: (-r.total_ads, -r.distinct_brands))
    return results


def creative_saturation(
    ads_by_hook_angle: dict[str, list[dict]],
    *,
    thresholds: dict | None = None,
) -> list[SaturationResult]:
    """Same mechanics as product_saturation but keyed by a (hook, angle, offer) combo
    label, to answer "is everyone using the same creative structure"."""
    thresholds = thresholds or DEFAULT_THRESHOLDS
    results = []
    for combo, ads in ads_by_hook_angle.items():
        brands = {ad["page_id"] for ad in ads}
        level = _classify_level(len(brands), len(ads), thresholds)
        results.append(SaturationResult(combo, len(brands), len(ads), level))
    results.sort(key=lambda r: (-r.total_ads, -r.distinct_brands))
    return results

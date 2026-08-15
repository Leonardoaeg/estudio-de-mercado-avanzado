"""InsightEngine — section 38. Turns statistics into plain-language conclusions using a
strict template: "N de las M marcas analizadas usan X" / "Y% de los anuncios muestran Z".
Never phrases a pattern as causal advice ("UGC is the best strategy") — only as an
observed pattern within the analyzed sample (section 3/38's objectivity rule).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Insight:
    statement: str
    evidence_level: str  # HECHO | INFERENCIA | HIPOTESIS
    sample_size: int


def insight_boolean_flag_share(flag_name_es: str, flag_values: list[bool | None], *, sample_label: str = "marcas") -> Insight | None:
    """flag_values: one bool|None per advertiser (or per ad) indicating whether the
    pattern was detected. Returns None if there's no usable sample."""
    known = [v for v in flag_values if v is not None]
    if not known:
        return None
    positive = sum(1 for v in known if v)
    total = len(known)
    pct = round(positive / total * 100)
    statement = f"{positive} de {total} {sample_label} analizados muestran señales de {flag_name_es} ({pct}%)."
    return Insight(statement=statement, evidence_level="INFERENCIA", sample_size=total)


def insight_dominant_label_share(dimension_label_es: str, label: str, count: int, total: int) -> Insight | None:
    if total == 0:
        return None
    pct = round(count / total * 100)
    statement = (
        f"{count} de {total} anuncios analizados ({pct}%) usan '{label}' como {dimension_label_es} "
        f"predominante dentro de la muestra."
    )
    return Insight(statement=statement, evidence_level="INFERENCIA", sample_size=total)


def insight_early_seconds_pattern(matching: int, total: int) -> Insight | None:
    """Section 12: what happens in the first 1-3 seconds. v1 only has text-based hook
    detection (see IMPLEMENTATION_PLAN.md), so this is always phrased as INFERENCIA about
    the ad's *opening copy*, not a HECHO about the literal video frame."""
    if total == 0:
        return None
    pct = round(matching / total * 100)
    statement = (
        f"{matching} de {total} anuncios ({pct}%) abren su texto con un patrón de gancho "
        f"identificable (pregunta, problema, oferta o curiosidad) en las primeras palabras del copy."
    )
    return Insight(statement=statement, evidence_level="INFERENCIA", sample_size=total)


def build_niche_insights(stats: dict) -> list[Insight]:
    """`stats` is a pre-aggregated dict the report generator builds; this function stays
    a thin, testable wrapper so insight *wording* is centralized and consistent."""
    insights: list[Insight] = []

    ugc = insight_boolean_flag_share("UGC", stats.get("ugc_flags", []), sample_label="anuncios")
    if ugc:
        insights.append(ugc)

    demo = insight_boolean_flag_share(
        "demostración de producto", stats.get("demonstration_flags", []), sample_label="anuncios"
    )
    if demo:
        insights.append(demo)

    testimonial = insight_boolean_flag_share("testimonios", stats.get("testimonial_flags", []), sample_label="anuncios")
    if testimonial:
        insights.append(testimonial)

    if stats.get("dominant_hook_count") and stats.get("total_ads"):
        hook_insight = insight_dominant_label_share(
            "hook", stats["dominant_hook_label"], stats["dominant_hook_count"], stats["total_ads"]
        )
        if hook_insight:
            insights.append(hook_insight)

    if stats.get("hook_pattern_matches") is not None and stats.get("total_ads"):
        early = insight_early_seconds_pattern(stats["hook_pattern_matches"], stats["total_ads"])
        if early:
            insights.append(early)

    return insights

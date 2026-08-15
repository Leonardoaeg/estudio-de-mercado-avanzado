"""Two rankings per niche — section 21. Pure functions over a list of advertiser dicts,
so they're testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankedAdvertiser:
    rank: int
    page_id: str
    page_name: str
    score: float


def rank_by_presence(advertisers: list[dict], *, top_n: int = 10) -> list[RankedAdvertiser]:
    """Ranking 1: Highest Advertising Presence — sorted by scale_signal_score desc.
    Ties broken by active_ad_count desc, then page_name asc for determinism."""
    ordered = sorted(
        advertisers,
        key=lambda a: (-a.get("scale_signal_score", 0.0), -a.get("active_ad_count", 0), a.get("page_name", "")),
    )
    return [
        RankedAdvertiser(rank=i + 1, page_id=a["page_id"], page_name=a["page_name"], score=a.get("scale_signal_score", 0.0))
        for i, a in enumerate(ordered[:top_n])
    ]


def rank_by_acceleration(advertisers: list[dict], *, top_n: int = 10) -> list[RankedAdvertiser]:
    """Ranking 2: Fastest Advertising Acceleration — sorted by acceleration_score desc.
    Advertisers with no prior snapshot (growth_percentage is None) are excluded, since
    "fastest growing" is meaningless without a baseline — not silently treated as 0%."""
    eligible = [a for a in advertisers if a.get("growth_percentage") is not None]
    ordered = sorted(
        eligible,
        key=lambda a: (-a.get("acceleration_score", 0.0), a.get("page_name", "")),
    )
    return [
        RankedAdvertiser(rank=i + 1, page_id=a["page_id"], page_name=a["page_name"], score=a.get("acceleration_score", 0.0))
        for i, a in enumerate(ordered[:top_n])
    ]

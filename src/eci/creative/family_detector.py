"""CreativeFamilyDetector — section 17.

Groups near-duplicate ads (same underlying creative concept) so a report can say
"100 ads but really 6 concepts" instead of treating every text variation as a distinct
strategy. v1 groups by SimHash similarity over copy + hook + product + landing + CTA
(utils/textsim.py) — a text-level proxy; it does not compare thumbnails/video frames
(see IMPLEMENTATION_PLAN.md limitations), so two ads with identical copy but a different
video edit will currently land in the same family.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from eci.utils.textsim import hamming_distance, simhash

DEFAULT_SIMILARITY_THRESHOLD = 0.82  # fraction of matching bits (see utils.textsim.similarity)
BITS = 64


@dataclass
class CreativeFamilyCluster:
    family_key: str
    member_ad_ids: list[str] = field(default_factory=list)
    representative_ad_id: str | None = None
    dominant_hook: str | None = None
    dominant_format: str | None = None


def _family_key(page_id: str, representative_fingerprint: int) -> str:
    page_hash = hashlib.md5(page_id.encode("utf-8")).hexdigest()[:8]
    return f"{page_hash}{representative_fingerprint:016x}"[:32]


def build_families(
    ads: list[dict],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict[str, CreativeFamilyCluster]:
    """`ads` items must have: ad_id, page_id, primary_text, hook, product, landing_url, cta,
    format, hook_type. Clusters per page_id (cross-advertiser grouping isn't meaningful for
    "how many concepts does THIS brand run"). Returns {family_key: cluster}.
    """
    clusters_by_page: dict[str, list[tuple[int, CreativeFamilyCluster]]] = {}
    families: dict[str, CreativeFamilyCluster] = {}

    for ad in ads:
        page_id = ad["page_id"]
        combined_text = " || ".join(
            str(ad.get(f) or "") for f in ("primary_text", "hook", "product", "landing_url", "cta")
        )
        fingerprint = simhash(combined_text)

        page_clusters = clusters_by_page.setdefault(page_id, [])
        matched_cluster = None
        for rep_fingerprint, cluster in page_clusters:
            dist = hamming_distance(fingerprint, rep_fingerprint)
            similarity = 1.0 - (dist / BITS)
            if similarity >= similarity_threshold:
                matched_cluster = cluster
                break

        if matched_cluster is None:
            key = _family_key(page_id, fingerprint)
            cluster = CreativeFamilyCluster(
                family_key=key,
                member_ad_ids=[ad["ad_id"]],
                representative_ad_id=ad["ad_id"],
                dominant_hook=ad.get("hook_type"),
                dominant_format=ad.get("format"),
            )
            page_clusters.append((fingerprint, cluster))
            families[key] = cluster
        else:
            matched_cluster.member_ad_ids.append(ad["ad_id"])

    return families


def ad_to_family_map(families: dict[str, CreativeFamilyCluster]) -> dict[str, str]:
    """Flattens {family_key: cluster} into {ad_id: family_key} for persistence."""
    mapping: dict[str, str] = {}
    for family_key, cluster in families.items():
        for ad_id in cluster.member_ad_ids:
            mapping[ad_id] = family_key
    return mapping

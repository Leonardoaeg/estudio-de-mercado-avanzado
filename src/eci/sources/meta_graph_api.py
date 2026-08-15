"""Official Meta Ad Library API client (`graph.facebook.com/.../ads_archive`).

This is the source Meta explicitly sanctions for programmatic access (section 32:
"Priorizar APIs o fuentes oficiales cuando existan"). It requires a developer access
token with the Ad Library API permission (`ads_read` for the advertiser's own ads is NOT
what this uses — `ads_archive` is public-read for any active ad, gated only by an app
access token). Get one at https://developers.facebook.com/.

Without META_ACCESS_TOKEN set, `is_available()` returns False with a clear reason and
`search_ads` returns a controlled error — it never fabricates ads.
"""

from __future__ import annotations

import json

from eci.config import get_settings
from eci.models.schemas import RawAd
from eci.sources.base import AdLibrarySource, SourceFetchOutcome
from eci.utils.http import fetch

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}/ads_archive"

FIELDS = ",".join(
    [
        "id",
        "page_id",
        "page_name",
        "ad_snapshot_url",
        "ad_delivery_start_time",
        "ad_delivery_stop_time",
        "ad_creative_bodies",
        "ad_creative_link_titles",
        "ad_creative_link_descriptions",
        "ad_creative_link_captions",
        "publisher_platforms",
        "languages",
    ]
)


class MetaGraphAPISource(AdLibrarySource):
    name = "meta_graph_api"

    def is_available(self) -> tuple[bool, str | None]:
        settings = get_settings()
        if not settings.meta_access_token:
            return False, "missing_token: set META_ACCESS_TOKEN in .env (see .env.example)"
        return True, None

    def search_ads(self, keyword: str, market: str, *, page_cursor: str | None = None) -> SourceFetchOutcome:
        available, reason = self.is_available()
        if not available:
            return SourceFetchOutcome(ads=[], ok=False, error=reason, exhausted=True)

        settings = get_settings()
        params = {
            "search_terms": keyword,
            "ad_reached_countries": json.dumps([market]),
            "ad_active_status": "ACTIVE",
            "ad_type": "ALL",
            "fields": FIELDS,
            "limit": str(settings.pagination.page_size),
            "access_token": settings.meta_access_token,
        }
        if page_cursor:
            params["after"] = page_cursor

        query = "&".join(f"{k}={v}" for k, v in params.items())
        result = fetch(f"{BASE_URL}?{query}", use_cache=True)
        if not result.ok or not result.text:
            return SourceFetchOutcome(ads=[], ok=False, error=result.error or "empty_response", exhausted=True)

        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError as exc:
            return SourceFetchOutcome(ads=[], ok=False, error=f"invalid_json: {exc}", exhausted=True)

        if "error" in payload:
            err = payload["error"]
            return SourceFetchOutcome(
                ads=[], ok=False, error=f"graph_api_error: {err.get('message', err)}", exhausted=True
            )

        ads: list[RawAd] = []
        for item in payload.get("data", []):
            bodies = item.get("ad_creative_bodies") or []
            titles = item.get("ad_creative_link_titles") or []
            descriptions = item.get("ad_creative_link_descriptions") or []
            ads.append(
                RawAd(
                    ad_id=str(item.get("id")),
                    source_name=self.name,
                    page_id=str(item.get("page_id", "")),
                    page_name=item.get("page_name", "unknown"),
                    ad_library_url=item.get("ad_snapshot_url"),
                    active=item.get("ad_delivery_stop_time") is None,
                    start_date=item.get("ad_delivery_start_time"),
                    format_hint=None,  # Graph API doesn't expose creative format directly; resolved
                    # downstream by fetching ad_snapshot_url when the analyzer needs it (not done in v1;
                    # format_classifier falls back to text-only heuristics, marking format "unknown"
                    # unless publisher_platforms/creative text imply otherwise).
                    primary_text=bodies[0] if bodies else None,
                    headline=titles[0] if titles else None,
                    description=descriptions[0] if descriptions else None,
                    cta=None,
                    landing_url=None,
                    raw_payload=item,
                )
            )

        cursor = payload.get("paging", {}).get("cursors", {}).get("after")
        has_next = bool(payload.get("paging", {}).get("next"))
        return SourceFetchOutcome(ads=ads, ok=True, exhausted=not has_next)

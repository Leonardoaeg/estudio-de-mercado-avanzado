"""URL normalization and canonicalization utilities.

These are pure functions (no network I/O) so they are fully unit-testable. Redirect
resolution (which needs network I/O) lives in `utils/http.py::resolve_final_url`.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

_AD_ID_RE = re.compile(r"[?&]id=(\d+)")

# Query params that are pure tracking noise and should never affect deduplication or
# be persisted for privacy/URL-hygiene reasons (section: privacy — never leak tracking IDs).
TRACKING_PARAM_PREFIXES = ("utm_", "fbclid", "gclid", "ttclid", "igshid", "mc_")


def normalize_url(raw: str | None) -> str | None:
    """Lowercases scheme/host, strips default ports, trailing slash, and tracking params.

    Returns None for falsy/unparseable input rather than raising, since this is used
    on messy scraped data where a malformed URL should degrade to "unknown", not crash
    the pipeline.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw.lstrip("/")

    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    if not parsed.netloc:
        return None

    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    netloc = netloc.split(":")[0] if netloc.endswith(":80") or netloc.endswith(":443") else netloc

    path = parsed.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not any(k.lower().startswith(p) for p in TRACKING_PARAM_PREFIXES)
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)

    return urlunparse((scheme, netloc, path, "", query, ""))


def extract_domain(raw: str | None) -> str | None:
    """Returns the bare registrable-ish host (no scheme, no www, no port), or None."""
    normalized = normalize_url(raw)
    if not normalized:
        return None
    return urlparse(normalized).netloc or None


def canonical_store_key(raw: str | None) -> str | None:
    """A stable dedup key for a store: the domain only (path/query dropped).

    Two ads landing on https://mystore.com/product-a and https://mystore.com/product-b
    are the same store for dedup purposes; product-level detail is kept separately on
    the `ads` row, not lost — this key only drives `stores` table dedup.
    """
    return extract_domain(raw)


def meta_ad_library_page_url(page_id: str | None) -> str | None:
    """Builds the "see every active ad from this Page" Meta Ad Library link — more useful
    than linking a single sampled ad, since it stays valid as the advertiser's ad set
    changes. Only real Facebook numeric page IDs work with `view_all_page_id` — this
    happens automatically with the Graph API source. Neither MockSource's synthetic IDs
    nor the web scraper's slugified `scraped_<page_name>` IDs (the card's numeric Page ID
    isn't exposed without an extra click-through per ad — documented limitation) are real
    Facebook IDs, so this returns None for them rather than emitting a link that 404s.
    Callers should fall back to a specific ad's own (real, working) `ad_library_url`.
    """
    if not page_id or not page_id.isdigit():
        return None
    return (
        "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
        f"&search_type=page&view_all_page_id={page_id}"
    )


def extract_ad_id(ad_library_url: str | None) -> str | None:
    """Pulls the numeric ad id out of a `.../ads/library/?id=123` style URL."""
    if not ad_library_url:
        return None
    match = _AD_ID_RE.search(ad_library_url)
    return match.group(1) if match else None


def meta_ad_library_ad_url_with_context(
    ad_id: str, *, market: str | None = None, keyword: str | None = None
) -> str:
    """Links to one specific ad (opens as a detail modal on Meta's site) while ALSO
    seeding the page behind that modal with a keyword search for the advertiser's own
    name — confirmed live (2026-08-14): closing the modal then reveals that store's other
    active ads instead of a blank/unrelated results page, which is what a bare `?id=`
    link leaves behind. Falls back to the bare link when there's no market/keyword to
    seed the background search with (e.g. regenerating a report without that context)."""
    if not market or not keyword:
        return f"https://www.facebook.com/ads/library/?id={ad_id}"
    return (
        "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
        f"&country={market}&q={quote(keyword)}&search_type=keyword_unordered&id={ad_id}"
    )


def meta_ad_library_store_search_url(keyword: str, market: str) -> str:
    """Links straight to the Ad Library's search RESULTS LIST for the store's own name —
    no `?id=` modal on top, just the filtered list of that store's ads (operator: "que
    lleve a la biblioteca de anuncios filtrada por el nombre de la tienda"). Used for the
    card-level "Ver anuncios" button when we don't have a real numeric page ID (see
    meta_ad_library_page_url) to build the more precise `view_all_page_id` link."""
    return (
        "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
        f"&country={market}&q={quote(keyword)}&search_type=keyword_unordered"
    )

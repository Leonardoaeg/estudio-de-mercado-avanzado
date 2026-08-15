"""Playwright-based scraper for the public Meta Ad Library search UI
(facebook.com/ads/library). This is the fallback source when no official API token is
configured, using only publicly viewable pages and no authentication.

Explicitly out of bounds (section 32): no CAPTCHA bypass, no cookie theft, no login,
no access-control evasion. If Meta blocks/serves a CAPTCHA/changes the DOM, this source
must fail closed (log the error, return not_verified, keep going) — never guess.

Parsing strategy (rewritten 2026-08-14 against the real, live UI — the original version
guessed at English wording that turned out wrong for the actual product):
Meta's ad library ships obfuscated, auto-generated CSS class names that change on every
deploy, so this scraper avoids CSS-class selectors entirely and instead parses the page's
plain rendered text (`document.body.innerText`), split into one chunk per ad using the
stable, user-facing "Activo"/"Inactivo" status line that starts every card. Confirmed
live wording (Spanish UI, observed 2026-08-14 browsing Colombia):
    Activo
    Identificador de la biblioteca: 2160719207835594
    En circulación desde el 6 jul 2026
    Plataformas
    [Este anuncio tiene varias versiones]
    Abrir menú desplegable
    Ver detalles del anuncio
    SHEIN
    Publicidad
    <primary text...>
    M.SHEIN.COM.CO
    <headline>
    [<description>]
    Shop Now
English installs use "Active"/"Inactive", "Library ID: N", "Started running on <date>" —
both are matched. `parse_ad_library_text` is a pure function (no Playwright dependency),
so it's fully unit-testable against captured fixtures without a live browser.

The CTA button ("Shop Now"/"Comprar ahora"/...) links through Meta's `l.facebook.com/l.php
?u=<real landing url>` redirect shim; the real destination is recovered by decoding that
`u` query param directly from the anchor's `href`, without ever following the redirect.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from eci.config import get_settings
from eci.models.schemas import RawAd
from eci.sources.base import AdLibrarySource, SourceFetchOutcome

SEARCH_URL = (
    "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
    "&country={country}&q={query}&search_type=keyword_unordered"
)

_STATUS_WORDS = ("Activo", "Inactivo", "Active", "Inactive")
_STATUS_BLOCK_SPLIT_RE = re.compile(
    r"(?=^(?:" + "|".join(_STATUS_WORDS) + r")\s*$)", re.MULTILINE
)
_ID_RE = re.compile(
    r"(?:Identificador de la biblioteca|Library ID)\s*[:\s]\s*(\d+)", re.IGNORECASE
)
_ID_LINE_RE = re.compile(r"^(Identificador de la biblioteca|Library ID)\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"(?:En circulación desde el|Started running on)\s+([^\n]+)", re.IGNORECASE
)
_DATE_LINE_RE = re.compile(r"^(En circulación desde el|Started running on)\b", re.IGNORECASE)
_DOMAIN_LINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}$")
# Meta renders a video scrubber as plain text like "0:00 / 0:18" right next to the video —
# a reliable, real signal that a card is a VIDEO ad, extractable without any visual/vision
# analysis. No equivalent reliable text marker was found for CAROUSEL vs single IMAGE in
# the captured samples, so that distinction still requires visual inspection (documented
# limitation) — this only ever resolves to "video" or leaves format_hint unset.
_VIDEO_DURATION_RE = re.compile(r"\b\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}\b")

_BOILERPLATE_LINES = {
    "plataformas", "platforms",
    "este anuncio tiene varias versiones", "this ad has multiple versions",
    "abrir menú desplegable", "open drop-down", "open dropdown",
    "ver detalles del anuncio", "see ad details", "see summary details",
    "publicidad", "sponsored",
}

_KNOWN_CTAS = {
    "shop now", "comprar ahora", "ver más", "learn more", "más información",
    "enviar mensaje", "send message", "sign up", "regístrate", "download",
    "descargar", "contact us", "contáctanos", "get offer", "obtener oferta",
    "apply now", "book now", "reservar",
}


def _clean_lines(segment: str) -> list[str]:
    """Splits into lines, strips whitespace and the zero-width-space characters Meta
    renders for icon-only buttons, and drops anything left empty."""
    lines = []
    for raw_line in segment.splitlines():
        line = raw_line.strip().strip("​").strip()
        if line:
            lines.append(line)
    return lines


def parse_ad_library_text(full_text: str) -> list[dict]:
    """Pure function: Ad Library page's plain text -> list of loosely-typed ad dicts
    with keys: status, ad_id, start_date_raw, page_name, primary_text, domain, headline,
    description, cta. Any field it can't confidently identify is None (never guessed).
    Ads without a recognizable ID are dropped (there's nothing reliable to key them on).
    """
    results: list[dict] = []
    for segment in _STATUS_BLOCK_SPLIT_RE.split(full_text):
        id_match = _ID_RE.search(segment)
        if not id_match:
            continue  # not an ad card (header/footer/filter-chip text)
        ad_id = id_match.group(1)

        date_match = _DATE_RE.search(segment)
        start_date_raw = date_match.group(1).strip() if date_match else None

        lines = _clean_lines(segment)
        status = next((w for w in _STATUS_WORDS if lines and lines[0] == w), None)

        # Anchor on "Publicidad"/"Sponsored" rather than trying to enumerate every possible
        # boilerplate line: cards can carry extra disclaimers we haven't seen before ("N
        # anuncios usan este contenido...", "Número de impresiones bajo", "Transparencia de
        # la UE" on EU-targeted ads, etc.) — an exhaustive strip-list is a losing game and
        # was misidentifying those disclaimer lines as the page_name. The "Publicidad"/
        # "Sponsored" label is the one line Meta renders on every single ad card, always
        # immediately after the advertiser name, regardless of which other disclaimers show.
        sponsor_idx = next(
            (i for i, line in enumerate(lines) if line.lower() in ("publicidad", "sponsored")), None
        )
        has_video = bool(_VIDEO_DURATION_RE.search(segment))

        if sponsor_idx is not None and sponsor_idx > 0:
            page_name = lines[sponsor_idx - 1]
            remaining = [line for line in lines[sponsor_idx + 1 :] if not _VIDEO_DURATION_RE.match(line)]
        else:
            # Fallback for a malformed/unusual card: strip every known boilerplate line and
            # hope the first survivor is the page name (best-effort, may be wrong).
            content_lines = [
                line
                for line in lines
                if line.lower() not in _BOILERPLATE_LINES
                and line not in _STATUS_WORDS
                and not _ID_LINE_RE.match(line)
                and not _DATE_LINE_RE.match(line)
                and not _VIDEO_DURATION_RE.match(line)
            ]
            if not content_lines:
                continue
            page_name = content_lines[0]
            remaining = content_lines[1:]
        domain_idx = next((i for i, line in enumerate(remaining) if _DOMAIN_LINE_RE.match(line)), None)

        if domain_idx is not None:
            primary_text = " ".join(remaining[:domain_idx]) or None
            domain = remaining[domain_idx]
            after_domain = remaining[domain_idx + 1 :]
            headline = after_domain[0] if after_domain else None
            description = after_domain[1] if len(after_domain) >= 3 else None
            cta = after_domain[-1] if len(after_domain) >= 2 else None
        else:
            # No recognizable domain line — keep everything as primary_text rather than
            # mis-assigning fields, and mark format-relevant fields not_available upstream.
            primary_text = " ".join(remaining) or None
            domain, headline, description, cta = None, None, None, None

        results.append(
            {
                "ad_id": ad_id,
                "status": status,
                "active": status in ("Activo", "Active") if status else True,
                "start_date_raw": start_date_raw,
                "page_name": page_name,
                "primary_text": primary_text,
                "domain": domain,
                "headline": headline,
                "description": description,
                "cta": cta if (cta and cta.lower() in _KNOWN_CTAS) or cta else cta,
                "format_hint": "video" if has_video else None,
            }
        )
    return results


def decode_landing_url(l_php_href: str) -> str | None:
    """Decodes Meta's outbound-link shim (l.facebook.com/l.php?u=<encoded target>) back
    into the real destination URL, without following the redirect."""
    try:
        parsed = urlparse(l_php_href)
        params = parse_qs(parsed.query)
        target = params.get("u", [None])[0]
        return unquote(target) if target else None
    except Exception:  # noqa: BLE001 - malformed href just means "unknown", not a crash
        return None


class PlaywrightUnavailable(RuntimeError):
    pass


class MetaWebScraperSource(AdLibrarySource):
    name = "meta_web_scraper"

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False, "playwright_not_installed: pip install playwright"
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                except Exception as exc:  # noqa: BLE001 - any launch failure means "unavailable"
                    return False, f"chromium_not_installed: run `playwright install chromium` ({exc})"
        except Exception as exc:  # noqa: BLE001
            return False, f"playwright_launch_error: {exc}"
        return True, None

    def search_ads(self, keyword: str, market: str, *, page_cursor: str | None = None) -> SourceFetchOutcome:
        available, reason = self.is_available()
        if not available:
            return SourceFetchOutcome(ads=[], ok=False, error=reason, exhausted=True)

        settings = get_settings()
        url = SEARCH_URL.format(country=market, query=quote(keyword))

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=settings.playwright.headless)
                page = browser.new_page(user_agent=settings.http.user_agent)
                page.set_default_navigation_timeout(settings.playwright.navigation_timeout_ms)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)  # let client-side rendering settle (low-result
                    # queries seem to need closer to 4s than 2.5s to hydrate — observed
                    # empirically: a 2.5s wait intermittently returned 0 ads for a real,
                    # verified-present advertiser that a 4s wait captured reliably)
                    # Scroll repeatedly to trigger lazy-loaded ad cards — Meta's feed is
                    # virtualized and only renders what's been scrolled into view.
                    for _ in range(6):
                        page.mouse.wheel(0, 2400)
                        page.wait_for_timeout(700)
                    full_text = page.evaluate("() => document.body.innerText")
                    landing_hrefs = page.eval_on_selector_all(
                        'a[href*="l.facebook.com/l.php"]', "els => els.map(e => e.href)"
                    )
                except PlaywrightTimeoutError as exc:
                    browser.close()
                    return SourceFetchOutcome(ads=[], ok=False, error=f"navigation_timeout: {exc}", exhausted=True)
                browser.close()
        except Exception as exc:  # noqa: BLE001 - never let a scraper crash the pipeline
            return SourceFetchOutcome(ads=[], ok=False, error=f"scrape_error: {exc}", exhausted=True)

        parsed_ads = parse_ad_library_text(full_text)
        landing_urls = [decode_landing_url(href) for href in landing_hrefs]

        ads: list[RawAd] = []
        seen_ids: set[str] = set()
        for i, item in enumerate(parsed_ads):
            if item["ad_id"] in seen_ids:
                continue
            seen_ids.add(item["ad_id"])
            landing_url = landing_urls[i] if i < len(landing_urls) else None

            ads.append(
                RawAd(
                    ad_id=item["ad_id"],
                    source_name=self.name,
                    page_id=f"scraped_{item['page_name'].lower().replace(' ', '_')}",
                    # Meta's public UI doesn't expose the advertiser's numeric Page ID on the
                    # card itself (would need an extra click-through per ad, not done in v1 —
                    # documented limitation, see IMPLEMENTATION_PLAN.md). Slugified page_name
                    # is used as a stable-enough dedup key within a single scraping session.
                    page_name=item["page_name"],
                    ad_library_url=f"https://www.facebook.com/ads/library/?id={item['ad_id']}",
                    active=item["active"],
                    start_date=item["start_date_raw"],
                    format_hint=item["format_hint"],  # "video" when a duration scrubber was
                    # detected in the card's text (see _VIDEO_DURATION_RE); otherwise None,
                    # and format_classifier falls back to a low-confidence text heuristic or
                    # UNKNOWN — image vs. carousel still isn't distinguishable from text alone.
                    primary_text=item["primary_text"],
                    headline=item["headline"],
                    description=item["description"],
                    cta=item["cta"],
                    landing_url=landing_url,
                    raw_payload={"domain": item["domain"], "status_raw": item["status"]},
                )
            )

        # The public UI has no stable cursor token exposed to us without deeper interaction;
        # v1 scrapes a single "page" (post-scroll) per keyword and marks itself exhausted.
        return SourceFetchOutcome(ads=ads, ok=True, exhausted=True)

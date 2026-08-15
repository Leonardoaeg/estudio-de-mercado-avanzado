"""Resilient HTTP client: retry + exponential backoff + jitter + timeouts + on-disk cache.

Section 31 of the spec: the program must tolerate timeouts, network errors, redirects,
rate limits and never let a single failing request break a whole research run. Every
public function here returns a structured result (never raises for expected failure
modes) so callers can record `not_verified` and continue.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from eci.config import get_settings, resolve_path


@dataclass
class FetchResult:
    url: str
    final_url: str | None
    status_code: int | None
    text: str | None
    ok: bool
    error: str | None
    from_cache: bool = False


def _cache_path(url: str) -> Path:
    settings = get_settings()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return resolve_path(f"{settings.http.cache_dir}/{digest}.json")


def _read_cache(url: str) -> FetchResult | None:
    settings = get_settings()
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - payload.get("cached_at", 0) > settings.http.cache_ttl_seconds:
        return None
    return FetchResult(
        url=url,
        final_url=payload.get("final_url"),
        status_code=payload.get("status_code"),
        text=payload.get("text"),
        ok=payload.get("ok", False),
        error=payload.get("error"),
        from_cache=True,
    )


def _write_cache(url: str, result: FetchResult) -> None:
    path = _cache_path(url)
    payload = {
        "url": result.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "text": result.text,
        "ok": result.ok,
        "error": result.error,
        "cached_at": time.time(),
    }
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; never fail the pipeline over a disk write error


def fetch(url: str, *, use_cache: bool = True, headers: dict[str, str] | None = None) -> FetchResult:
    """GET a URL with retry/backoff/jitter and an on-disk cache. Never raises."""
    if use_cache:
        cached = _read_cache(url)
        if cached is not None:
            return cached

    settings = get_settings()
    req_headers = {"User-Agent": settings.http.user_agent}
    if headers:
        req_headers.update(headers)

    @retry(
        stop=stop_after_attempt(settings.http.max_retries + 1),
        wait=wait_exponential_jitter(
            initial=settings.http.backoff_base_seconds,
            max=settings.http.backoff_max_seconds,
            jitter=settings.http.jitter_seconds,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        reraise=True,
    )
    def _do_request() -> httpx.Response:
        with httpx.Client(
            timeout=settings.http.timeout_seconds,
            follow_redirects=True,
            headers=req_headers,
            verify=settings.http.verify_ssl,
        ) as client:
            return client.get(url)

    try:
        response = _do_request()
    except httpx.TimeoutException as exc:
        return FetchResult(url, None, None, None, False, f"timeout: {exc}")
    except httpx.TransportError as exc:
        return FetchResult(url, None, None, None, False, f"transport_error: {exc}")
    except httpx.HTTPError as exc:
        return FetchResult(url, None, None, None, False, f"http_error: {exc}")

    result = FetchResult(
        url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        text=response.text if response.status_code < 400 else None,
        ok=response.status_code < 400,
        error=None if response.status_code < 400 else f"http_status_{response.status_code}",
    )
    if use_cache and result.ok:
        _write_cache(url, result)
    return result


def resolve_final_url(url: str) -> str | None:
    """Follows redirects and returns the final landing URL, or None on failure."""
    result = fetch(url)
    return result.final_url if result.ok else None


def polite_sleep(base_seconds: float = 0.5) -> None:
    """A small randomized delay between requests to the same host, to be a respectful crawler."""
    time.sleep(base_seconds + random.random() * base_seconds)


def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None) -> FetchResult:
    """POST with the same retry/backoff policy as `fetch`, used by API sources (e.g. Meta Graph API)."""
    settings = get_settings()
    req_headers = {"User-Agent": settings.http.user_agent, "Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    @retry(
        stop=stop_after_attempt(settings.http.max_retries + 1),
        wait=wait_exponential_jitter(
            initial=settings.http.backoff_base_seconds,
            max=settings.http.backoff_max_seconds,
            jitter=settings.http.jitter_seconds,
        ),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        reraise=True,
    )
    def _do_request() -> httpx.Response:
        with httpx.Client(
            timeout=settings.http.timeout_seconds, headers=req_headers, verify=settings.http.verify_ssl
        ) as client:
            return client.post(url, json=payload)

    try:
        response = _do_request()
    except httpx.HTTPError as exc:
        return FetchResult(url, None, None, None, False, f"http_error: {exc}")

    return FetchResult(
        url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        text=response.text,
        ok=response.status_code < 400,
        error=None if response.status_code < 400 else f"http_status_{response.status_code}",
    )

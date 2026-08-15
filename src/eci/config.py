"""Central configuration loader.

Loads config/settings.yaml, config/niches.yaml, config/keywords.yaml and config/scoring.yaml,
merges in environment variables (via a .env file if present) and exposes a single `get_settings()`
singleton. Keeping this in one module means every other module gets configuration the same way,
instead of re-reading YAML files ad hoc.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing required config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_dotenv() -> None:
    """Minimal .env loader (avoids adding python-dotenv as a hard dependency)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class HttpSettings(BaseModel):
    timeout_seconds: float = 15
    max_retries: int = 3
    backoff_base_seconds: float = 1.5
    backoff_max_seconds: float = 30
    jitter_seconds: float = 0.75
    user_agent: str = "ECI-Research-Agent/0.1"
    cache_dir: str = "data/cache"
    cache_ttl_seconds: int = 21600
    # SECURITY: must stay True on any real deployment. Some sandboxed/dev environments sit
    # behind a TLS-intercepting proxy whose re-signed certificate isn't in the default trust
    # store, which makes every third-party HTTPS request fail with CERTIFICATE_VERIFY_FAILED
    # even though the site itself is fine — that's the ONLY legitimate reason to flip this,
    # via ECI_HTTP_VERIFY_SSL=false in .env, never as a hardcoded default.
    verify_ssl: bool = True


class PlaywrightSettings(BaseModel):
    headless: bool = True
    navigation_timeout_ms: int = 30000
    slow_mo_ms: int = 0


class PaginationSettings(BaseModel):
    max_pages_per_source: int = 200
    page_size: int = 100


class LongevityWindow(BaseModel):
    min_age_days: int = 30
    max_age_days: int = 90


class Settings(BaseModel):
    market: str = "CO"
    supported_markets: list[str] = Field(default_factory=list)
    minimum_active_ads: int = 50
    ecommerce_score_minimum: int = 70
    http: HttpSettings = Field(default_factory=HttpSettings)
    playwright: PlaywrightSettings = Field(default_factory=PlaywrightSettings)
    database_url: str = "sqlite:///data/eci.db"
    pagination: PaginationSettings = Field(default_factory=PaginationSettings)
    longevity_reference_window: LongevityWindow = Field(default_factory=LongevityWindow)
    log_level: str = "INFO"

    # Raw taxonomies / weights, kept as plain dicts since their shape is domain-specific
    # and validated by the modules that consume them rather than by this generic loader.
    niches: dict[str, Any] = Field(default_factory=dict)
    keywords: dict[str, Any] = Field(default_factory=dict)
    scoring: dict[str, Any] = Field(default_factory=dict)
    excluded_brands: dict[str, Any] = Field(default_factory=dict)

    meta_access_token: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()

    raw = _load_yaml("settings.yaml")
    niches = _load_yaml("niches.yaml")
    keywords = _load_yaml("keywords.yaml")
    scoring = _load_yaml("scoring.yaml")
    excluded_brands = _load_yaml("excluded_brands.yaml")

    db_url = os.environ.get("ECI_DATABASE_URL") or raw.get("database", {}).get(
        "url", "sqlite:///data/eci.db"
    )
    http_raw = dict(raw.get("http", {}))
    if os.environ.get("ECI_HTTP_TIMEOUT_SECONDS"):
        http_raw["timeout_seconds"] = float(os.environ["ECI_HTTP_TIMEOUT_SECONDS"])
    if os.environ.get("ECI_HTTP_MAX_RETRIES"):
        http_raw["max_retries"] = int(os.environ["ECI_HTTP_MAX_RETRIES"])
    if os.environ.get("ECI_HTTP_VERIFY_SSL") is not None:
        http_raw["verify_ssl"] = os.environ["ECI_HTTP_VERIFY_SSL"].strip().lower() not in ("false", "0", "no")

    return Settings(
        market=raw.get("market", "CO"),
        supported_markets=raw.get("supported_markets", []),
        minimum_active_ads=raw.get("minimum_active_ads", 50),
        ecommerce_score_minimum=raw.get("ecommerce_score_minimum", 70),
        http=HttpSettings(**http_raw),
        playwright=PlaywrightSettings(**raw.get("playwright", {})),
        database_url=db_url,
        pagination=PaginationSettings(**raw.get("pagination", {})),
        longevity_reference_window=LongevityWindow(**raw.get("longevity_reference_window", {})),
        log_level=raw.get("logging", {}).get("level", "INFO"),
        niches=niches,
        keywords=keywords,
        scoring=scoring,
        excluded_brands=excluded_brands,
        meta_access_token=os.environ.get("META_ACCESS_TOKEN") or None,
    )


def resolve_path(relative: str) -> Path:
    """Resolve a path relative to the project root, creating parent dirs if needed."""
    p = PROJECT_ROOT / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

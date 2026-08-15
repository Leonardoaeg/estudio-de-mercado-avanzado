"""AdLibrarySource abstraction — section 32/41. Every concrete source (official API,
web scraper, offline mock, and any future source) implements this interface so the
discovery/collector pipeline never depends on how ads were actually obtained.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from eci.models.schemas import RawAd


@dataclass
class SourceFetchOutcome:
    """Wraps a batch of ads plus what went wrong, so the collector can log errors
    (section 45) without ever raising and aborting the whole run (section 31)."""

    ads: list[RawAd] = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    exhausted: bool = False  # True when the source has no more pages for this query


class AdLibrarySource(ABC):
    """Common interface for anything that can answer: "give me ads matching this
    keyword, in this market". Concrete sources decide how (API call, scraping, fixture)."""

    name: str = "base"

    @abstractmethod
    def search_ads(self, keyword: str, market: str, *, page_cursor: str | None = None) -> SourceFetchOutcome:
        """Returns one page of ads for `keyword`/`market`. `page_cursor` is opaque and
        source-specific (used for pagination/resume)."""
        raise NotImplementedError

    def is_available(self) -> tuple[bool, str | None]:
        """Cheap pre-flight check (e.g. "do we have a token?", "is playwright installed?").
        Returns (available, reason_if_not). Never raises."""
        return True, None

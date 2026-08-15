"""Source factory: string name -> AdLibrarySource instance."""

from __future__ import annotations

from eci.sources.base import AdLibrarySource

_REGISTRY: dict[str, type[AdLibrarySource]] = {}


def _lazy_registry() -> dict[str, type[AdLibrarySource]]:
    if not _REGISTRY:
        from eci.sources.meta_graph_api import MetaGraphAPISource
        from eci.sources.meta_web_scraper import MetaWebScraperSource
        from eci.sources.mock_source import MockSource

        _REGISTRY.update(
            {
                MockSource.name: MockSource,
                MetaGraphAPISource.name: MetaGraphAPISource,
                MetaWebScraperSource.name: MetaWebScraperSource,
            }
        )
    return _REGISTRY


def get_source(name: str) -> AdLibrarySource:
    registry = _lazy_registry()
    if name not in registry:
        raise ValueError(f"Unknown source '{name}'. Available: {sorted(registry)}")
    return registry[name]()


def available_sources() -> list[str]:
    return sorted(_lazy_registry())

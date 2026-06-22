"""External retrieval providers.

The agents pipeline reads from a list of `ExternalRetrievalProvider` instances,
defined as a Protocol in `seldon.agents.retrieval`. This package holds the
concrete provider implementations (DuckDuckGo for now; Tavily/Brave/Reddit
later) and a small registry/factory so swapping or stacking providers does not
require touching agent code.
"""
from __future__ import annotations

from collections.abc import Callable

from seldon.agents.retrieval import ExternalRetrievalProvider
from seldon.config import RetrievalConfig

from .duckduckgo import DuckDuckGoProvider
from .news import GoogleNewsRSSProvider

ProviderFactory = Callable[[RetrievalConfig], ExternalRetrievalProvider]


class SearchProviderRegistry:
    """Registry mapping provider name → factory function.

    To add a new provider (Tavily, Brave, Serper, Reddit), implement a class
    satisfying `ExternalRetrievalProvider` and register it here. No agent code
    changes.
    """

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, name: str, factory: ProviderFactory) -> None:
        self._factories[name] = factory

    def build(self, name: str, config: RetrievalConfig) -> ExternalRetrievalProvider:
        if name not in self._factories:
            raise KeyError(f"unknown retrieval provider: {name!r} (registered: {sorted(self._factories)})")
        return self._factories[name](config)

    def names(self) -> list[str]:
        return sorted(self._factories)


_default_registry = SearchProviderRegistry()
_default_registry.register("duckduckgo", lambda cfg: DuckDuckGoProvider(cfg))
_default_registry.register("google_news", lambda cfg: GoogleNewsRSSProvider(cfg))


def default_registry() -> SearchProviderRegistry:
    return _default_registry


def build_providers_from_config(retrieval: RetrievalConfig) -> list[ExternalRetrievalProvider]:
    """Build the list of providers requested in config, skipping ones that fail to instantiate.

    Failure to instantiate one provider (missing dep, missing API key) should not
    prevent the others from running.
    """
    providers: list[ExternalRetrievalProvider] = []
    for name in retrieval.providers:
        try:
            providers.append(_default_registry.build(name, retrieval))
        except Exception:
            # Surface to logs via the caller; we don't import logging here to keep
            # this module side-effect free.
            continue
    return providers


__all__ = [
    "SearchProviderRegistry",
    "DuckDuckGoProvider",
    "GoogleNewsRSSProvider",
    "build_providers_from_config",
    "default_registry",
]

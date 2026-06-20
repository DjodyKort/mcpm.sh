"""Provider registry."""
from __future__ import annotations

from typing import Dict, List, Type

from ..provider import CompressionProvider
from .headroom import HeadroomProvider
from .none import NoneProvider
from .rtk import RtkOnlyProvider

_REGISTRY: Dict[str, Type[CompressionProvider]] = {
    HeadroomProvider.name: HeadroomProvider,
    RtkOnlyProvider.name: RtkOnlyProvider,
    NoneProvider.name: NoneProvider,
}


def get_provider(name: str) -> CompressionProvider:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown compression provider: {name!r}. Known: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]()


def provider_names() -> List[str]:
    return list(_REGISTRY)

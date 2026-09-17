"""The StoreAdapter contract and its registry.

CLAUDE.md section 1: adding a chain must mean adding one file and registering it,
nothing else. So the protocol lives here, the registry lives here, and no caller
outside `adapters/` is allowed to branch on chain name.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import RawOffer, RawProduct


@runtime_checkable
class StoreAdapter(Protocol):
    """What every chain module must provide."""

    chain: str

    def fetch_promotions(self) -> list[RawOffer]:
        """Every currently-valid promotion for this chain."""
        ...

    def fetch_product(self, sku: str) -> RawProduct:
        """One SKU, including whatever nutrition the chain exposes."""
        ...


_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    """Class decorator. The chain name is taken from the class attribute."""
    chain = getattr(cls, "chain", None)
    if not chain:
        raise ValueError(f"{cls.__name__} must define a `chain` attribute")
    if chain in _REGISTRY:
        raise ValueError(f"chain {chain!r} already registered by {_REGISTRY[chain].__name__}")
    _REGISTRY[chain] = cls
    return cls


def get_adapter(chain: str, **kwargs: object) -> StoreAdapter:
    if chain not in _REGISTRY:
        raise KeyError(f"unknown chain {chain!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[chain](**kwargs)  # type: ignore[operator]


def available_chains() -> list[str]:
    return sorted(_REGISTRY)

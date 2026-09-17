"""Chain adapters.

Register a new chain by adding one module here and importing it below. Nothing
else in the codebase should need to change.
"""

from . import ah  # noqa: F401  - import registers the adapter
from . import aldi  # noqa: F401
from . import jumbo  # noqa: F401
from .base import StoreAdapter, available_chains, get_adapter, register

__all__ = ["StoreAdapter", "available_chains", "get_adapter", "register"]

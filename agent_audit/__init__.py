"""agent-audit: Tamper-evident audit trail for AI agents."""

__version__ = "1.0.0"

from .observe import (
    get_engine,
    observe,
    set_engine,
)

__all__ = [
    "get_engine",
    "observe",
    "set_engine",
]

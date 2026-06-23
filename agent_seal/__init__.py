"""agent-seal: Tamper-evident audit trail for AI agents."""

__version__ = "1.1.0"

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

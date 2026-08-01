"""The read-only browser window onto the ledger."""
from __future__ import annotations

from .server import serve, snapshot

__all__ = ["serve", "snapshot"]

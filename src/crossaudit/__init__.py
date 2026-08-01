"""CrossAudit: a git-native, cross-vendor audit protocol for agentic science.

Importing this package must never touch the network, authenticate, or write
outside the package (constraint 7). Everything that reaches outward lives
behind an explicit CLI verb.
"""
from __future__ import annotations

__version__ = "2.5.0"
RECEIPT_SCHEMA = 2

__all__ = ["__version__", "RECEIPT_SCHEMA"]

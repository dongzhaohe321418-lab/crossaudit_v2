"""The command line.

Nothing is re-exported here, deliberately. A `from .main import main` puts a
function named `main` on this package, shadowing the submodule of the same name,
so `crossaudit.cli.main` resolves to the function for some importers and to the
module for others — a confusion that costs more than the shortcut saves.

The entry point names both explicitly: `crossaudit.cli.main:main`.
"""
from __future__ import annotations

__all__: list[str] = []

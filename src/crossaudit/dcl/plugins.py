"""Third-party check packs, loaded only when the deployment names them.

An entry point is arbitrary code execution inside a process that will shortly
hold API keys and write a ledger. Discovery is therefore not automatic: a pack
runs because `plugins:` in crossaudit.yml names it, and the name that was
allowed is what gets loaded — nothing else on the machine.

What a pack may contribute is also bounded. Checks are deterministic by
definition; a "check" that calls a model is a second auditor wearing the
mechanical layer's authority, and I4 says the mechanical layer is the one whose
failure modes are least entangled with any model. Packs declare the API version
they were written against, and a mismatch is refused rather than guessed at.
"""
from __future__ import annotations

from ..errors import ConfigDenial

DCL_API_VERSION = 1
_LOADED: set[str] = set()


def load_allowed(allowed: list[str] | None) -> list[str]:
    """Load exactly the named packs. Returns what was newly loaded."""
    if not allowed:
        return []
    from importlib.metadata import entry_points

    available = {ep.name: ep for ep in entry_points(group="crossaudit.checks")}
    loaded = []
    for name in allowed:
        if name in _LOADED:
            continue
        ep = available.get(name)
        if ep is None:
            raise ConfigDenial(
                f"check pack {name!r} is named in plugins: but is not installed; "
                f"available: {sorted(available) or 'none'}")
        pack = ep.load()
        declared = getattr(pack, "DCL_API_VERSION", None)
        if declared != DCL_API_VERSION:
            raise ConfigDenial(
                f"check pack {name!r} declares dcl api {declared!r}, this build "
                f"speaks {DCL_API_VERSION}; refusing rather than guessing")
        register = getattr(pack, "register_checks", None)
        if not callable(register):
            raise ConfigDenial(f"check pack {name!r} exposes no register_checks()")
        register()
        _LOADED.add(name)
        loaded.append(name)
    return loaded

"""Verifier self-identification (constraint 2, completing I7).

The machine that admits must itself be pinned in the ledger. A running package
cannot honestly prove the SHA-256 of the wheel it came from — that digest is a
property of an artefact this process no longer has. What it *can* prove is the
canonical digest of the code actually loaded, plus how it was installed. Only a
lock file, which is external evidence, contributes an artefact hash.

So receipts carry: version, canonical installed-code digest, install mode, and
(when present) the lock digest. `verify --admit` refuses install modes whose
code could have changed under it since the digest was taken.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

__all__ = ["identity", "code_digest", "install_mode", "ADMISSIBLE_MODES"]

PKG_ROOT = Path(__file__).resolve().parent

#: Install modes that may consume a receipt. An editable or bare-source install
#: can be edited between digesting and admitting, so it may verify but never admit.
ADMISSIBLE_MODES = frozenset({"wheel"})


def code_digest() -> str:
    """SHA-256 over every .py file in the package, path-sorted, path-tagged.

    Path-tagged so that moving code between modules changes the digest; sorted
    so that filesystem order cannot.
    """
    h = hashlib.sha256()
    for p in sorted(PKG_ROOT.rglob("*.py")):
        rel = p.relative_to(PKG_ROOT).as_posix()
        h.update(rel.encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def install_mode() -> str:
    """How this package reached the interpreter: wheel, editable, or source."""
    root = str(PKG_ROOT)
    if "site-packages" in root or "dist-packages" in root:
        # An editable install lands a .pth/__editable__ finder rather than files.
        for parent in Path(root).parents:
            if parent.name in ("site-packages", "dist-packages"):
                if any(parent.glob("__editable__*crossaudit*")):
                    return "editable"
                break
        return "wheel"
    if (PKG_ROOT.parent.parent / "pyproject.toml").exists():
        return "source"
    return "unknown"


def lock_digest(start: Path | None = None) -> str | None:
    """SHA-256 of the deployment's hash-pinned lock file, when one is in force.

    External evidence: the lock is what ties this process to artefact hashes,
    which is why an artefact hash is only ever reported alongside it.
    """
    env = os.environ.get("CROSSAUDIT_LOCKFILE")
    candidates = [Path(env)] if env else []
    base = start or Path.cwd()
    candidates += [base / "requirements-crossaudit.lock", base / "constraints.txt"]
    for c in candidates:
        if c.is_file():
            return hashlib.sha256(c.read_bytes()).hexdigest()
    return None


def identity(start: Path | None = None) -> dict:
    """The verifier identity block embedded in every receipt."""
    from . import __version__

    ident = {
        "project": "crossaudit",
        "version": __version__,
        "code_digest_sha256": code_digest(),
        "install_mode": install_mode(),
        "lock_digest_sha256": lock_digest(start),
    }
    return ident

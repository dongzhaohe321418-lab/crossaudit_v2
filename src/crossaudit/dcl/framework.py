"""Check registry and runner.

A check is a callable taking the materialised increment (path -> bytes) and
returning findings. Builtins are registered by name; third-party packs arrive
through the `crossaudit.checks` entry-point group in 0.4 and are, by design,
not discovered automatically — an entry point is arbitrary code execution, so
loading is allowlist-only (installer-design 05a).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Mapping

from ..errors import ConfigDenial

BLOCKER, ADVISORY = "BLOCKER", "ADVISORY"


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    artifact: str
    observation: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def hard_failures(self) -> int:
        return sum(1 for f in self.findings if f.severity == BLOCKER)

    def as_dict(self) -> dict:
        return {
            "crossaudit_dcl_version": 2,
            "verdict": "BLOCKED" if self.hard_failures else "PASS",
            "total_hard_failures": self.hard_failures,
            "findings": [f.as_dict() for f in self.findings],
            "notes": self.notes,
        }


CheckFn = Callable[[Mapping[str, bytes]], list[Finding]]
_REGISTRY: dict[str, CheckFn] = {}


def register(name: str, fn: CheckFn) -> None:
    _REGISTRY[name] = fn


def available() -> list[str]:
    return sorted(_REGISTRY)


def run_checks(files: Mapping[str, bytes], names: list[str],
               notes: list[str] | None = None,
               plugins: list[str] | None = None) -> CheckResult:
    """Run the named checks. An unknown name denies rather than being skipped."""
    from . import builtin, neutral  # noqa: F401  (registration on import)
    from .plugins import load_allowed

    load_allowed(plugins)
    missing = [n for n in names if n not in _REGISTRY]
    if missing:
        raise ConfigDenial(f"unknown checks {missing}; available: {available()}")
    result = CheckResult(notes=list(notes or []))
    for name in names:
        result.findings.extend(_REGISTRY[name](files))
    # I8: an input we could not fully read can never end in PASS.
    if any(n.startswith("truncated:") for n in result.notes):
        result.findings.append(Finding(
            BLOCKER, "CA-META-004", "increment",
            "input truncated before the checks ran; a partial read cannot yield PASS"))
    return result

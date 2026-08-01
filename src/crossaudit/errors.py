"""Denials and exit codes.

Exit codes are part of the CLI contract (installer-design 05a): a caller
scripting the loop must be able to tell *why* it was refused without parsing
prose. Anything unexpected still denies — fail-closed is the default, not a
mode (constraint 3).
"""
from __future__ import annotations

# 0 is reserved for the good outcome of whichever verb ran.
EXIT_OK = 0
EXIT_BLOCKED = 10          # DCL hard failure or auditor BLOCKER findings
EXIT_ESCALATED = 11        # ESCALATE / DCL_ONLY: human or a further round owns it
EXIT_CONFIG = 20           # configuration or environment refused the run
EXIT_INTEGRITY = 21        # receipt, manifest, ledger or verifier identity refused
EXIT_PROVIDER = 22         # network or model provider failed


class Denial(Exception):
    """A refusal with a machine-readable reason and a stable exit code."""

    exit_code = EXIT_CONFIG
    kind = "denied"

    def __init__(self, reason: str, **detail: object) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail

    def as_dict(self) -> dict:
        return {"denied": True, "kind": self.kind, "reason": self.reason,
                "exit_code": self.exit_code, **self.detail}


class ConfigDenial(Denial):
    exit_code = EXIT_CONFIG
    kind = "config"


class IntegrityDenial(Denial):
    """Receipt, manifest, ledger, verifier identity, or isolation refused."""

    exit_code = EXIT_INTEGRITY
    kind = "integrity"


class ProviderDenial(Denial):
    exit_code = EXIT_PROVIDER
    kind = "provider"

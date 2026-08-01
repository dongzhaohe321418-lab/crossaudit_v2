"""Receipt construction, in the only order that can be honest.

The report is an immutable blob committed first; the receipt then binds that
commit. Isolation is recorded as evidence gathered from how this process
actually ran — never as a label chosen by the caller.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .. import RECEIPT_SCHEMA, _selfid
from ..config import Config, heterogeneity


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def isolation_evidence(cfg: Config, *, mode: str, provisioner: str,
                       admission: str) -> dict:
    """Observed isolation, per dimension, plus the operational evidence.

    parametric: the two roles name different vendors, asserted from config (I1).
    contextual: the auditor sees committed artefacts only — true by construction
        here, since the increment is materialised from the git tree.
    permissive: the two roles' credentials are not both reachable by this
        process. On one machine with both keys exported, they are, and this is
        false — recorded, not narrated.
    """
    ok, _why = heterogeneity(cfg)
    gen_key_env = "CROSSAUDIT_GENERATOR_KEY"
    both_keys_here = bool(os.environ.get(cfg.auditor.key_env)) and bool(
        os.environ.get(gen_key_env))
    return {
        "parametric": ok,
        "contextual": True,
        "permissive": mode != "local" and not both_keys_here,
        "execution": mode,
        "credential": "shared-process" if both_keys_here else "auditor-only",
        "provider": f"{cfg.auditor.provider}:{cfg.auditor.model}",
        "provisioner": provisioner,
        "admission": admission,
    }


def build(*, cfg: Config, subject: dict, cycle: dict, manifest: dict,
          constitution_path: str, constitution_bytes: bytes, constitution_commit: str,
          dcl_source_sha256: str, prompt_sha256: str, checks: list[str],
          skills: dict | None = None,
          verdict: str, exchange: dict, retention: str, report_bytes: bytes,
          report_commit: str, cycle_path: str, audit_repo: str,
          mode: str, provisioner: str = "cli", admission: str = "local-controller",
          integrity: str = "OK") -> dict:
    """Assemble a v2 receipt. Every field is derived, none is caller prose."""
    return {
        "receipt_schema": RECEIPT_SCHEMA,
        "subject": {
            "science_repo": cfg.science_repo,
            "sha": subject["sha"],
            "tree": subject["tree"],
            "scope": subject.get("scope", ""),
        },
        "cycle": {
            "cycle_id": cycle["cycle_id"],
            "root_sha": cycle["root_sha"],
            "active_sha": cycle["active_sha"],
            "parent_receipt": cycle.get("parent_receipt", ""),
            "round": cycle["round"],
        },
        "inputs": {
            "manifest": manifest,
            "constitution_path": constitution_path,
            "constitution_sha256": _sha256(constitution_bytes),
            "constitution_commit": constitution_commit,
            "dcl_source_sha256": dcl_source_sha256,
            "prompt_sha256": prompt_sha256,
            "checks": checks,
            # Which house skills shaped this round, and their hashes. A round run
            # under different guidance is a different round, and the ledger says so.
            "skills": skills or {},
        },
        "audit": {
            "verdict": verdict,
            "provider": cfg.auditor.provider,
            "model": cfg.auditor.model,
            "vendor": cfg.auditor.vendor,
            "audit_integrity": integrity,
            "exchange": exchange,
            "retention": retention,
        },
        "ledger": {
            "audit_repo": audit_repo,
            "report_commit": report_commit,
            "cycle_path": cycle_path,
            "report_sha256": _sha256(report_bytes),
        },
        "verifier": _selfid.identity(cfg.root),
        "isolation": isolation_evidence(cfg, mode=mode, provisioner=provisioner,
                                        admission=admission),
    }

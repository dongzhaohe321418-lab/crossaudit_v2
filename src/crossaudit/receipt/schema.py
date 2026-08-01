"""Receipt v2: strict, versioned, canonically serialised.

A receipt binds one audit to one commit. v2 differs from v1 in three ways that
matter: it carries its own schema version (so a verifier never guesses), it
carries the verifier's identity (constraint 2), and it carries isolation
*evidence* rather than a one-word tier (constraint 6).

Ordering rule, enforced by construction elsewhere: the report is committed
first, and the receipt binds that commit. A receipt can therefore never contain
the hash of the commit that carries it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .. import RECEIPT_SCHEMA
from ..config import ISOLATION_DIMS
from ..errors import IntegrityDenial

REQUIRED_TOP = ("receipt_schema", "subject", "cycle", "inputs", "audit", "ledger",
                "verifier", "isolation")
REQUIRED_SUBJECT = ("science_repo", "sha", "tree", "scope")
REQUIRED_CYCLE = ("cycle_id", "root_sha", "active_sha", "parent_receipt", "round")
REQUIRED_INPUTS = ("manifest", "constitution_sha256", "constitution_commit",
                   "dcl_source_sha256", "prompt_sha256", "checks", "skills")
REQUIRED_AUDIT = ("verdict", "provider", "model", "vendor", "audit_integrity",
                  "exchange", "retention")
REQUIRED_LEDGER = ("audit_repo", "report_commit", "cycle_path", "report_sha256")
REQUIRED_VERIFIER = ("project", "version", "code_digest_sha256", "install_mode")

VERDICTS = ("PASS", "BLOCKED", "ESCALATE", "DCL_ONLY")
RETENTION_MODES = ("sealed", "redacted", "no-raw")


def canonical(receipt: dict) -> bytes:
    """Byte form a hash is taken over: sorted keys, compact, UTF-8, newline-free."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(receipt: dict) -> str:
    return hashlib.sha256(canonical(receipt)).hexdigest()


def _require(block: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in block]
    if missing:
        raise IntegrityDenial(f"receipt {where} is missing {missing}", where=where)


def validate(raw: Any) -> dict:
    """Structural validation. Unknown schema versions deny; they are never guessed."""
    if not isinstance(raw, dict):
        raise IntegrityDenial("receipt is not a JSON object")
    version = raw.get("receipt_schema")
    if version is None:
        raise IntegrityDenial(
            "receipt has no receipt_schema; pre-v2 receipts are inspectable with "
            "--legacy-inspect but are never admissible")
    if version != RECEIPT_SCHEMA:
        raise IntegrityDenial(f"receipt schema {version!r} is not supported by this "
                              f"verifier (expects {RECEIPT_SCHEMA})", schema=version)
    _require(raw, REQUIRED_TOP, "top level")
    _require(raw["subject"], REQUIRED_SUBJECT, "subject")
    _require(raw["cycle"], REQUIRED_CYCLE, "cycle")
    _require(raw["inputs"], REQUIRED_INPUTS, "inputs")
    _require(raw["audit"], REQUIRED_AUDIT, "audit")
    _require(raw["ledger"], REQUIRED_LEDGER, "ledger")
    _require(raw["verifier"], REQUIRED_VERIFIER, "verifier")

    if raw["audit"]["verdict"] not in VERDICTS:
        raise IntegrityDenial(f"verdict {raw['audit']['verdict']!r} is not one of {VERDICTS}")
    if raw["audit"]["retention"] not in RETENTION_MODES:
        raise IntegrityDenial(f"retention mode must be one of {RETENTION_MODES}")
    if len(str(raw["subject"]["sha"])) != 40:
        raise IntegrityDenial("subject.sha must be a full 40-character commit sha")
    if not isinstance(raw["inputs"]["manifest"], dict):
        raise IntegrityDenial("inputs.manifest must be a mapping of path to digest")

    iso = raw["isolation"]
    if not isinstance(iso, dict):
        raise IntegrityDenial("isolation must be a mapping")
    for dim in ISOLATION_DIMS:
        if dim not in iso or not isinstance(iso[dim], bool):
            raise IntegrityDenial(f"isolation.{dim} must be present and boolean")
    for key in ("execution", "credential", "provisioner", "admission"):
        if key not in iso:
            raise IntegrityDenial(f"isolation.{key} evidence is missing")
    return raw


def isolation_shortfall(receipt: dict, minimum: dict) -> list[str]:
    """Dimensions the deployment requires that this receipt does not evidence.

    This is the cross-tier replay guard: a receipt minted on a single machine,
    where both keys shared one process, must not admit in a deployment that
    requires permissive isolation.
    """
    iso = receipt.get("isolation", {})
    return [dim for dim in ISOLATION_DIMS if minimum.get(dim) and not iso.get(dim)]

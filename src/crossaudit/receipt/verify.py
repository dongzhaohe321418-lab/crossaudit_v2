"""Full receipt verification, and the admission transaction.

Verification is read-only and offline: it re-derives every binding from the two
git trees and refuses on the first mismatch. Admission is a separate, explicit
step that consumes the receipt inside the controller's lock.

What `--admit` refuses beyond verification (installer-design 05a):
  * an install mode whose code could have changed since it identified itself;
  * a receipt whose isolation evidence is weaker than the deployment's minimum;
  * a state store inside a throwaway checkout, where "consumed" survives nothing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import _selfid
from ..config import Config
from ..controller import StateStore
from ..errors import IntegrityDenial
from ..gitio import commit_exists, entries, is_ancestor, read_blob, resolve
from . import schema


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityDenial(f"receipt unreadable: {exc}", path=str(path)) from exc
    return schema.validate(raw)


def verify(receipt: dict, *, science_root: Path, audit_root: Path,
           expect_repo: str, expect_sha: str, cfg: Config | None = None) -> dict:
    """Re-derive every binding. Returns an evidence dict; raises on any mismatch."""
    subject, inputs, ledger = receipt["subject"], receipt["inputs"], receipt["ledger"]

    if subject["science_repo"] != expect_repo:
        raise IntegrityDenial(f"science_repo {subject['science_repo']!r} != expected "
                              f"{expect_repo!r}")
    if subject["sha"] != expect_sha:
        raise IntegrityDenial(f"receipt sha {subject['sha'][:12]} != expected "
                              f"{expect_sha[:12]}")
    if not commit_exists(science_root, subject["sha"]):
        raise IntegrityDenial("audited commit is not in the science repository",
                              sha=subject["sha"][:12])

    sha, tree = resolve(science_root, subject["sha"])
    if tree != subject["tree"]:
        raise IntegrityDenial(f"science tree {tree[:12]} != receipt tree "
                              f"{subject['tree'][:12]}")

    # Manifest against the tree, not the working directory.
    blobs = {path: blob for _mode, path, blob in entries(science_root, sha)}
    for rel, declared in inputs["manifest"].items():
        if declared == "ABSENT":
            if rel in blobs:
                raise IntegrityDenial(f"manifest says ABSENT but {rel} is in the tree")
            continue
        if rel not in blobs:
            raise IntegrityDenial(f"manifest lists {rel}, absent from the tree")
        data, truncated = read_blob(science_root, blobs[rel])
        if truncated or _sha256(data) != declared:
            raise IntegrityDenial(f"manifest mismatch for {rel}")

    # Constitution: content hash and the commit that versions it (I3).
    const_rel = inputs.get("constitution_path", "AUDIT_RULES.md")
    const_path = audit_root / const_rel
    if not const_path.is_file():
        raise IntegrityDenial(f"constitution {const_rel} missing from the audit tree")
    if _sha256(const_path.read_bytes()) != inputs["constitution_sha256"]:
        raise IntegrityDenial("constitution content differs from the receipt's hash")
    if inputs["constitution_commit"] in ("", None, "unversioned"):
        raise IntegrityDenial("receipt declares the constitution unversioned")

    # Report blob, in the cycle directory the receipt names.
    cycle_dir = audit_root / ledger["cycle_path"]
    report = cycle_dir / "report.md"
    if not report.is_file():
        raise IntegrityDenial(f"report missing at {ledger['cycle_path']}/report.md")
    if _sha256(report.read_bytes()) != ledger["report_sha256"]:
        raise IntegrityDenial("report blob hash mismatch")
    if not cycle_dir.name.startswith(subject["sha"][:12]):
        raise IntegrityDenial(f"cycle directory {cycle_dir.name} does not belong to "
                              f"{subject['sha'][:12]}")

    # The report commit must exist and precede this receipt (ordering rule).
    report_commit = ledger["report_commit"]
    if report_commit and commit_exists(audit_root, report_commit):
        head = resolve(audit_root, "HEAD")[0]
        if head != report_commit and not is_ancestor(audit_root, report_commit, head):
            raise IntegrityDenial("report commit is not an ancestor of the audit head")
    elif report_commit:
        raise IntegrityDenial("report commit named by the receipt is not in the audit repo")

    admission_shortfalls = []
    if receipt["audit"]["verdict"] != "PASS":
        admission_shortfalls.append(
            f"verdict is {receipt['audit']['verdict']}, not PASS")
    if receipt["audit"]["audit_integrity"] != "OK":
        admission_shortfalls.append(
            f"audit integrity is {receipt['audit']['audit_integrity']}")
    if cfg is not None:
        short = schema.isolation_shortfall(receipt, cfg.isolation_minimum)
        if short:
            admission_shortfalls.append(
                f"isolation evidence is missing {short}")

    return {
        "receipt_digest": schema.digest(receipt),
        "sha": subject["sha"],
        "cycle_id": receipt["cycle"]["cycle_id"],
        "verified": True,
        "admission_ready": not admission_shortfalls,
        "admission_shortfalls": admission_shortfalls,
    }


def admit(receipt: dict, store: StateStore, evidence: dict,
          cfg: Config | None = None) -> dict:
    """Consume the receipt once, in the controller's lock.

    Refuses install modes that cannot stand behind their own digest, because an
    admission is exactly the moment that identity has to hold.
    """
    if receipt["audit"]["verdict"] != "PASS":
        raise IntegrityDenial(f"verdict is {receipt['audit']['verdict']}, not PASS — "
                              f"nothing to admit", verdict=receipt["audit"]["verdict"])
    if receipt["audit"]["audit_integrity"] != "OK":
        raise IntegrityDenial(f"audit integrity: {receipt['audit']['audit_integrity']}")
    if cfg is not None:
        short = schema.isolation_shortfall(receipt, cfg.isolation_minimum)
        if short:
            raise IntegrityDenial(
                f"isolation evidence is weaker than this deployment requires: "
                f"missing {short}", missing=short)

    ident = _selfid.identity()
    if ident["install_mode"] not in _selfid.ADMISSIBLE_MODES:
        raise IntegrityDenial(
            f"install mode {ident['install_mode']!r} may verify but never admit: its "
            f"code can change under the digest it reports",
            install_mode=ident["install_mode"])
    if receipt["verifier"]["code_digest_sha256"] != ident["code_digest_sha256"]:
        raise IntegrityDenial(
            "the verifier that minted this receipt is not the one admitting it; "
            "re-verify with the recorded version before admitting",
            minted_by=receipt["verifier"].get("version"))
    store.admit(evidence["cycle_id"], evidence["sha"], evidence["receipt_digest"])
    return {"admitted": True, "receipt_digest": evidence["receipt_digest"],
            "cycle_id": evidence["cycle_id"]}

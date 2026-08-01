"""One audit cycle: DCL, model audit, verdict synthesis, report, receipt.

Verdict synthesis is code, never model output (I4), and every path that is not
a clean, valid, model-backed PASS lands somewhere other than PASS (I8):

    escalation lock            -> ESCALATE   (an escalated cycle is not routed around)
    DCL hard failure           -> BLOCKED    (dominates any model opinion)
    invalid or failed audit    -> ESCALATE
    prompt bound exceeded      -> ESCALATE   (the model did not see everything)
    no model ran               -> DCL_ONLY   (never a conforming PASS)
    otherwise                  -> the model's own verdict
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..config import Config, heterogeneity
from ..dcl import run_checks
from ..errors import ConfigDenial, Denial, ProviderDenial
from ..providers import get_provider
from ..providers.registry import NON_EVIDENTIAL
from . import prompt as prompt_mod
from .validate import known_rules, parse_reply, validate_reply


@dataclass
class AuditOutcome:
    verdict: str
    dcl: dict
    model_reply: dict | None
    invalid_reason: str | None
    integrity: str
    exchange: dict
    prompt_sha256: str
    report: str


def dcl_source_digest() -> str:
    """Hash of the check layer's own source, so a receipt pins what ran."""
    import crossaudit.dcl as pkg

    root = Path(pkg.__file__).parent
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def render_report(*, cfg: Config, sha: str, round_: int, verdict: str, dcl: dict,
                  reply: dict | None, invalid: str | None, constitution_commit: str,
                  provider: str, model: str) -> str:
    lines = [
        f"# Audit Report — {cfg.science_repo}@{sha[:12]}",
        "",
        "| | |",
        "|---|---|",
        f"| verdict | **{verdict}** |",
        f"| round | {round_} |",
        f"| constitution | `{constitution_commit[:12]}` |",
        f"| auditor | `{provider}:{model}` (vendor {cfg.auditor.vendor}) |",
        f"| deterministic layer | {dcl['total_hard_failures']} hard failure(s) |",
        "",
        "## Deterministic findings",
        "",
    ]
    if dcl["findings"]:
        for f in dcl["findings"]:
            lines.append(f"### [{f['severity']}] {f['rule']} — {f['artifact']}")
            lines.append(f"{f['observation']}")
            lines.append("")
    else:
        lines += ["None.", ""]

    lines += ["## Model findings", ""]
    if invalid:
        lines += [f"### [BLOCKER] CA-META-002 — invalid Auditor reply",
                  f"The model audit was rejected: {invalid}. Under I3 an invalid audit "
                  f"escalates; it can never pass an increment.", ""]
    elif reply:
        if reply.get("findings"):
            for f in reply["findings"]:
                lines.append(f"### [{f['severity']}] {f['rule']} — {f.get('artifact', '?')}")
                lines.append(f"{f['observation']}")
                lines.append("")
        else:
            lines += ["None.", ""]
        lines += [f"Rules applied: {', '.join(reply.get('sections_applied', []))}", ""]
    else:
        lines += ["No model audit ran; this is a deterministic-tier result only.", ""]
    return "\n".join(lines)


def run_audit(*, cfg: Config, sha: str, round_: int, files: Mapping[str, bytes],
              notes: list[str], constitution: str, constitution_commit: str,
              task: str = "",
              escalation_lock: bool = False, offline: bool = False,
              allow_custom_endpoint: bool = False, retention: str = "sealed"
              ) -> AuditOutcome:
    dcl = run_checks(files, cfg.checks, notes, cfg.plugins).as_dict()
    prompt, bounded, prompt_sha = prompt_mod.build(
        constitution, constitution_commit, dcl, files, task)
    reply: dict | None = None
    invalid: str | None = None
    integrity = "OK"
    exchange: dict = {"mode": "none"}

    if not offline:
        ok, why = heterogeneity(cfg)
        if not ok and cfg.generator_vendor:
            raise ConfigDenial(why)                   # a same-vendor pair is not CrossAudit
        complete = get_provider(cfg.auditor.provider)
        try:
            raw = complete(model=cfg.auditor.model, system=prompt_mod.SYSTEM,
                           prompt=prompt, key_env=cfg.auditor.key_env,
                           base_url=cfg.auditor.base_url,
                           allow_custom=allow_custom_endpoint)
            exchange = {"mode": retention, "provider": cfg.auditor.provider,
                        **raw.commitments(retention)}
            parsed, perr = parse_reply(raw.text)
            invalid = perr or validate_reply(parsed, known_rules(constitution))
            reply = parsed if invalid is None else None
        except ProviderDenial as exc:
            invalid = f"auditor call failed: {exc.reason}"
            integrity = "PROVIDER_FAILURE"
            exchange = {"mode": "none", "error": exc.reason}
        except Denial:
            raise

    if escalation_lock:
        verdict = "ESCALATE"
    elif dcl["total_hard_failures"] > 0:
        verdict = "BLOCKED"
    elif invalid:
        verdict = "ESCALATE"
        integrity = integrity if integrity != "OK" else "INVALID_REPLY"
    elif bounded:
        verdict = "ESCALATE"
        integrity = "BOUNDS_EXCEEDED"
    elif reply:
        verdict = reply["verdict"]
    else:
        verdict = "DCL_ONLY"

    if cfg.auditor.provider in NON_EVIDENTIAL and verdict == "PASS":
        # A fixture is not an audit; it may exercise the loop, never bless a commit.
        integrity = "NON_EVIDENTIAL_PROVIDER"

    report = render_report(cfg=cfg, sha=sha, round_=round_, verdict=verdict, dcl=dcl,
                           reply=reply, invalid=invalid,
                           constitution_commit=constitution_commit,
                           provider=cfg.auditor.provider, model=cfg.auditor.model)
    return AuditOutcome(verdict=verdict, dcl=dcl, model_reply=reply,
                        invalid_reason=invalid, integrity=integrity, exchange=exchange,
                        prompt_sha256=prompt_sha, report=report)

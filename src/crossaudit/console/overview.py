"""The numbers on the dashboard, every one of them derived from the ledger.

A supervision dashboard is the last place a figure should be invented. Each
metric here is computed from committed reports, receipts and controller state,
and where the ledger cannot answer, the answer is absent rather than zero:
"0 escalations" and "we have never looked" are different claims, and only one of
them is safe to show in a large font.

The shape follows what a person actually asks, in order: how much came through,
how much passed, what is stuck, where is the current increment in the loop, and
what is waiting on me.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..controller import StateStore
from ..dispute import DISPUTES_LOG, parse_findings

VERDICT_RE = re.compile(r"\|\s*verdict\s*\|\s*\*\*(\w+)\*\*")
ROUND_RE = re.compile(r"\|\s*round\s*\|\s*(\d+)")
AUDITOR_RE = re.compile(r"\|\s*auditor\s*\|\s*`([^`]+)`")
CONST_RE = re.compile(r"\|\s*constitution\s*\|\s*`([0-9a-f]+)`")

SEVERITY_ORDER = ("BLOCKER", "ADVISORY")


@dataclass
class Cycle:
    """One audit round, as the ledger recorded it."""

    directory: str
    sha: str
    round: int
    verdict: str
    findings: list[dict]
    at: int
    auditor: str = ""
    constitution: str = ""

    @property
    def blockers(self) -> int:
        return sum(1 for f in self.findings if f["severity"] == "BLOCKER")


def read_cycles(cfg: Config) -> list[Cycle]:
    """Every audit the ledger holds, oldest first."""
    out: list[Cycle] = []
    ledger = cfg.root / cfg.ledger_dir
    if not ledger.is_dir():
        return out
    for report in sorted(ledger.glob("*/report.md")):
        text = report.read_text()
        name = report.parent.name
        sha, _, rest = name.partition("-r")
        verdict = (VERDICT_RE.search(text) or [None, "?"])[1] if VERDICT_RE.search(text) else "?"
        round_m = ROUND_RE.search(text)
        aud = AUDITOR_RE.search(text)
        const = CONST_RE.search(text)
        out.append(Cycle(
            directory=name, sha=sha, round=int(round_m.group(1)) if round_m else 1,
            verdict=verdict,
            findings=[{"severity": f.severity, "rule": f.rule, "artifact": f.artifact,
                       "observation": f.observation} for f in parse_findings(text)],
            at=int(report.stat().st_mtime),
            auditor=aud.group(1) if aud else "",
            constitution=const.group(1) if const else ""))
    return out


def metrics(cfg: Config, cycles: list[Cycle]) -> list[dict]:
    """The headline band. Absent evidence shows as absent, never as zero."""
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    states = store.snapshot().get("cycles", {})
    total = len(cycles)
    passed = sum(1 for c in cycles if c.verdict == "PASS")
    blocked = sum(1 for c in cycles if c.verdict == "BLOCKED")
    escalated = sum(1 for s in states.values() if s["status"] == "ESCALATED")
    admitted = sum(1 for s in states.values() if s["status"] == "CONSUMED")

    def pct(n: int) -> str:
        return f"{n / total:.0%}" if total else ""

    return [
        {"label": "Audits", "value": total, "note": "rounds the ledger holds",
         "tone": "neutral"},
        {"label": "Passed", "value": passed, "badge": pct(passed),
         "note": "cleared both layers", "tone": "good"},
        {"label": "Blocked", "value": blocked, "badge": pct(blocked),
         "note": "a defect was caught", "tone": "bad"},
        {"label": "Waiting on you", "value": escalated,
         "note": "escalated; the loop cannot settle these", "tone": "warn"},
        {"label": "Admitted", "value": admitted,
         "note": "receipts consumed, once each", "tone": "good"},
    ]


def pipeline(cfg: Config, cycles: list[Cycle]) -> list[dict]:
    """The five steps of one increment, and where the latest one stopped.

    Steps are marked done, current, failed or pending — never optimistically. A
    step nobody reached is pending, which is a different thing from passing.
    """
    latest = cycles[-1] if cycles else None
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    states = store.snapshot().get("cycles", {})
    status = ""
    if latest:
        for s in states.values():
            if s["active_sha"].startswith(latest.sha):
                status = s["status"]
                break

    def state(done: bool, failed: bool = False, current: bool = False) -> str:
        return ("failed" if failed else "current" if current
                else "done" if done else "pending")

    if latest is None:
        blank = [("Commit", "the generator writes and commits"),
                 ("Checks", "deterministic layer, no model involved"),
                 ("Audit", "a different vendor reads the commit"),
                 ("Verdict", "code decides; the checks dominate"),
                 ("Admission", "a receipt is consumed, once")]
        return [{"title": t, "detail": d, "state": "pending"} for t, d in blank]

    dcl_failed = any(f["rule"].startswith(("CA-FILE", "CA-META", "CA-DATA-001"))
                     and f["severity"] == "BLOCKER" for f in latest.findings)
    model_ran = latest.verdict != "DCL_ONLY"
    passed = latest.verdict == "PASS"
    admitted = status == "CONSUMED"

    return [
        {"title": "Commit", "detail": f"{latest.sha[:12]} · round {latest.round}",
         "state": "done"},
        {"title": "Checks",
         "detail": "clean" if not dcl_failed else "hard failure — final, no model "
                                                 "may waive it",
         "state": state(True, failed=dcl_failed)},
        {"title": "Audit",
         "detail": (latest.auditor or "auditor") if model_ran
                   else "no model ran — cannot be PASS",
         "state": state(model_ran, current=not model_ran)},
        {"title": "Verdict",
         "detail": f"{latest.verdict} · {len(latest.findings)} finding(s)",
         "state": state(passed, failed=latest.verdict in ("BLOCKED", "ESCALATE"))},
        {"title": "Admission",
         "detail": "receipt consumed" if admitted
                   else "waiting: verify the receipt to admit" if passed
                   else "not reached",
         "state": state(admitted, current=passed and not admitted)},
    ]


def findings_by_severity(cycles: list[Cycle]) -> dict:
    counts: dict[str, int] = {}
    for c in cycles:
        for f in c.findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    total = sum(counts.values())
    order = [s for s in SEVERITY_ORDER if s in counts] + [
        s for s in sorted(counts) if s not in SEVERITY_ORDER]
    return {"total": total,
            "rows": [{"severity": s, "count": counts[s],
                      "share": counts[s] / total if total else 0} for s in order]}


def top_rules(cycles: list[Cycle], limit: int = 5) -> list[dict]:
    """Which rules actually catch things — the Constitution's own report card."""
    counts: dict[str, int] = {}
    for c in cycles:
        for f in c.findings:
            counts[f["rule"]] = counts.get(f["rule"], 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"rule": r, "count": n} for r, n in ranked]


def escalations(cfg: Config) -> list[dict]:
    """What is waiting on a person, with the reason it stopped."""
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    cycles = read_cycles(cfg)
    out = []
    for cid, s in sorted(store.snapshot().get("cycles", {}).items()):
        if s["status"] != "ESCALATED":
            continue
        why = "the round budget ran out"
        for c in reversed(cycles):
            if s["active_sha"].startswith(c.sha):
                if c.verdict == "DCL_ONLY":
                    why = "no model audit ran, so it cannot pass"
                elif c.findings:
                    why = c.findings[0]["observation"][:140]
                break
        out.append({"cycle_id": cid, "sha": s["active_sha"][:12],
                    "round": s["round"], "why": why})
    return out


def disputes(cfg: Config, limit: int = 5) -> list[dict]:
    path = cfg.root / cfg.ledger_dir / DISPUTES_LOG
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [{"rule": r["rule"], "artifact": r["artifact"], "ruling": r["ruling"],
             "reasoning": r["reasoning"][:160], "t": r.get("t", 0)}
            for r in rows[-limit:]]

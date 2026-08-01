"""Reconstructing the two conversations from the ledger.

The console shows the generator and the auditor as two windows, but neither of
them is a chat log: what exists is commits, reports, receipts and routing
decisions. This module reads those back into the two streams a person would
recognise as conversations, which is the only honest way to render them —
nothing here is stored for the console's benefit.

Where the user's own words belong to one side, they appear in that window: a
sentence routed to the work shows in the generator's stream, a sentence about
the standards in the auditor's. That is the black box made legible — you see
which window heard you, and how sure the router was.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import Config
from ..dispute import DISPUTES_LOG, parse_findings
from ..router import history as routing_history

GENERATOR_LANES = {"generator", "project"}
AUDITOR_LANES = {"amendment", "dispute", "resolve"}
ROUND_RE = re.compile(r"\(round (\d+)\)\s*$")


def _commits(root: Path, limit: int = 60) -> list[dict]:
    import subprocess

    # The record separator leads each entry: with --name-only the file list
    # follows its commit's header, so a trailing separator would put every
    # commit's files at the head of the next commit's chunk.
    out = subprocess.run(
        ["git", "log", f"-{limit}", "--format=%x1e%H%x1f%ct%x1f%s", "--name-only"],
        cwd=str(root), capture_output=True, text=True)
    if out.returncode != 0:
        return []
    rows = []
    for chunk in out.stdout.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, files = chunk.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 3:
            continue
        rows.append({"sha": parts[0], "t": int(parts[1]), "subject": parts[2],
                     "files": [f for f in files.split("\n") if f.strip()]})
    return rows[::-1]


def generator_stream(cfg: Config, routing: list[dict]) -> list[dict]:
    """What the generator did, plus the user's words that were meant for it."""
    stream: list[dict] = []
    scope = tuple((cfg.scope_dirs or []))
    for c in _commits(cfg.root):
        work = [f for f in c["files"]
                if not scope or f.split("/", 1)[0] in scope]
        if not work or c["subject"].startswith(("audit report", "audit receipt",
                                                "amend rules", "dispute ")):
            continue
        m = ROUND_RE.search(c["subject"])
        stream.append({
            "kind": "generator", "t": c["t"],
            "summary": ROUND_RE.sub("", c["subject"]).strip(),
            "round": int(m.group(1)) if m else None,
            "files": work[:6],
            "notes": "",
        })
    for r in routing:
        if r.get("lane") in GENERATOR_LANES:
            stream.append({"kind": "you", **r})
    return sorted(stream, key=lambda m: m["t"])[-40:]


def auditor_stream(cfg: Config, routing: list[dict]) -> list[dict]:
    """Every verdict, every dispute ruling, and the user's words about standards."""
    stream: list[dict] = []
    ledger = cfg.root / cfg.ledger_dir
    for report in sorted(ledger.glob("*/report.md")):
        text = report.read_text()
        verdict = "?"
        m = re.search(r"\|\s*verdict\s*\|\s*\*\*(\w+)\*\*", text)
        if m:
            verdict = m.group(1)
        stream.append({
            "kind": "auditor", "t": int(report.stat().st_mtime), "verdict": verdict,
            "findings": [{"severity": f.severity, "rule": f.rule,
                          "artifact": f.artifact, "observation": f.observation[:400]}
                         for f in parse_findings(text)],
        })
    disputes = ledger / DISPUTES_LOG
    if disputes.is_file():
        for line in disputes.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            stream.append({
                "kind": "auditor", "t": d.get("t", 0), "verdict": d["ruling"],
                "findings": [{"severity": "dispute", "rule": d["rule"],
                              "artifact": d["artifact"],
                              "observation": d["reasoning"]}],
            })
    for r in routing:
        if r.get("lane") in AUDITOR_LANES:
            stream.append({"kind": "you", **r})
    return sorted(stream, key=lambda m: m["t"])[-40:]


def both(cfg: Config) -> tuple[list[dict], list[dict]]:
    routing = routing_history(cfg.root / cfg.ledger_dir / "routing.jsonl", 60)
    return generator_stream(cfg, routing), auditor_stream(cfg, routing)

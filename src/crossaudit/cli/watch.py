"""`crossaudit watch` — the loop, live, in the terminal.

Three panes: the Generator's commits, the Auditor's verdicts, and the
conversation between them (the ledger's event stream). Stdlib curses only, so
the core dependency budget stays at one; and strictly read-only — this is a
viewfinder over the ledger, never a second way to act on it. Every fact drawn
here comes from state.json, the cycles directory, or git; nothing is invented
and nothing can be clicked into existence.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..errors import ConfigDenial
from ..gitio import git

REFRESH_S = 2.0


# ------------------------------------------------------------------ data
def gather(cfg: Config) -> dict:
    """Everything the screen shows, as plain data (testable without curses)."""
    root = cfg.root
    state_path = root / cfg.state_dir / "state.json"
    state = {"cycles": {}, "history": []}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            pass

    verdict_by_sha: dict[str, dict] = {}
    for h in state.get("history", []):
        if h.get("event") == "verdict":
            verdict_by_sha[h["sha"]] = {"verdict": h["verdict"], "round": h["round"],
                                        "status": h["status"]}
    admitted = {h["sha"] for h in state.get("history", []) if h.get("event") == "admit"}

    commits = []
    raw = git("log", "--format=%H%x00%ct%x00%s", "-n", "30", cwd=root, check=False)
    for line in raw.splitlines():
        try:
            sha, ct, subject = line.split("\0", 2)
        except ValueError:
            continue
        is_ledger = subject.startswith(("audit report ", "audit receipt "))
        commits.append({"sha": sha, "t": int(ct), "subject": subject,
                        "ledger": is_ledger,
                        "verdict": verdict_by_sha.get(sha), "admitted": sha in admitted})

    cycles = []
    for cid, c in sorted(state.get("cycles", {}).items()):
        cycles.append({"cycle_id": cid, "status": c.get("status"),
                       "round": c.get("round"), "max_rounds": cfg.max_rounds,
                       "sha": c.get("active_sha", "")[:12],
                       "consumed": len(c.get("consumed", []))})

    events = []
    for h in state.get("history", [])[-40:]:
        t = datetime.fromtimestamp(h.get("t", 0)).strftime("%H:%M:%S")
        ev = h.get("event")
        sha = str(h.get("sha", ""))[:10]
        if ev == "open":
            events.append((t, "gen->aud", f"increment {sha} submitted (round 1)"))
        elif ev == "advance":
            events.append((t, "gen->aud", f"revision {sha} submitted (round {h.get('round')})"))
        elif ev == "readvance_same_sha":
            events.append((t, "gen->aud", f"{sha} re-submitted (round {h.get('round')})"))
        elif ev == "resume_open_round":
            events.append((t, "loop", f"round {h.get('round')} resumed after interruption"))
        elif ev == "verdict":
            events.append((t, "aud->gen",
                           f"{sha}: {h.get('verdict')} (round {h.get('round')}"
                           f" -> {h.get('status')})"))
        elif ev == "admit":
            events.append((t, "gate", f"{sha}: receipt consumed, increment admitted"))
        elif ev == "blocked_by_escalation":
            events.append((t, "gate", f"{sha}: held — an escalation awaits a human"))
        elif ev == "verdict_after_admission_ignored":
            events.append((t, "gate", f"{sha}: late verdict ignored (cycle closed)"))

    return {"repo": cfg.science_repo, "auditor": f"{cfg.auditor.provider}:{cfg.auditor.model}",
            "generator": cfg.generator_vendor or "undeclared",
            "commits": commits, "cycles": cycles, "events": events}


# ---------------------------------------------------------------- render
def _badge(c: dict) -> str:
    if c["admitted"]:
        return "ADMITTED"
    if c["verdict"]:
        return c["verdict"]["verdict"]
    if c["ledger"]:
        return "ledger"
    return "unaudited"


def draw(scr, data: dict) -> None:  # pragma: no cover - curses geometry
    import curses

    scr.erase()
    maxy, maxx = scr.getmaxyx()

    def put(y: int, x: int, text: str, attr: int = 0) -> None:
        if 0 <= y < maxy:
            scr.addnstr(y, x, text, max(0, maxx - x - 1), attr)

    bold = curses.A_BOLD
    dim = curses.A_DIM
    put(0, 0, f" CrossAudit watch — {data['repo']}", bold)
    put(1, 0, f" generator: {data['generator']}   auditor: {data['auditor']}"
              f"   (read-only view of the ledger; q quits)", dim)
    put(2, 0, "─" * (maxx - 1))

    half = max(20, maxx // 2)
    put(3, 0, " GENERATOR — commits", bold)
    row = 4
    for c in [c for c in data["commits"] if not c["ledger"]][:8]:
        mark = _badge(c)
        put(row, 1, f"{c['sha'][:10]}  {mark:9s} {c['subject'][:half - 25]}")
        row += 1
    if row == 4:
        put(row, 1, "(no commits yet)", dim)
        row += 1

    put(3, half, " AUDITOR — cycles", bold)
    arow = 4
    for cy in data["cycles"][-8:]:
        put(arow, half + 1,
            f"{cy['sha']}  round {cy['round']}/{cy['max_rounds']}  {cy['status']}"
            + ("  [consumed]" if cy["consumed"] else ""))
        arow += 1
    if arow == 4:
        put(arow, half + 1, "(no cycles yet)", dim)
        arow += 1

    top = max(row, arow) + 1
    put(top, 0, " CONVERSATION — the ledger's event stream", bold)
    put(top + 1, 0, "─" * (maxx - 1))
    lanes = {"gen->aud": "generator ─▶ auditor", "aud->gen": "auditor ─▶ generator",
             "gate": "admission gate", "loop": "loop"}
    erow = top + 2
    for t, lane, msg in data["events"][-(maxy - erow - 2):]:
        put(erow, 1, f"{t}  {lanes.get(lane, lane):22s} {msg}")
        erow += 1
    if erow == top + 2:
        put(erow, 1, "(nothing has happened yet — run `crossaudit run`)", dim)

    put(maxy - 1, 0, " every line above is derived from the ledger; "
                     "this screen can display, never decide ", dim)
    scr.refresh()


def run_watch(cfg: Config) -> int:  # pragma: no cover - interactive
    import sys

    if not sys.stdout.isatty():
        raise ConfigDenial("watch needs a terminal; for machines, use `status --json`")
    import curses

    def loop(scr):
        curses.curs_set(0)
        scr.timeout(int(REFRESH_S * 1000))
        while True:
            draw(scr, gather(cfg))
            ch = scr.getch()
            if ch in (ord("q"), ord("Q"), 27):
                return

    curses.wrapper(loop)
    return 0

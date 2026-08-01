"""`crossaudit talk` — the single conversational surface (DESIGN.md §2).

The user says what they want in ordinary language. The router decides the lane,
the decision is committed, and the lane's action runs through the same engine
verbs the CLI has always exposed. The box is opaque to interact with and glass
on the inside: `crossaudit routing` prints every decision it ever made.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .. import constitution as const_mod
from .. import router as router_mod
from ..config import Config, load
from ..controller import StateStore
from ..errors import ConfigDenial, Denial
from ..gitio import git, is_repo
from ..providers import get_provider

ROUTING_LOG = "routing.jsonl"


def _auditor_complete(cfg: Config):
    """A `complete(system, prompt)` bound to the auditor role.

    Routing and rule drafting run on the auditor side: it is the end whose job
    is understanding standards, and it is the end that must never receive the
    generator's internal narrative — so nothing here forwards anything but the
    user's own words (P2).
    """
    fn = get_provider(cfg.auditor.provider)

    def complete(*, system: str, prompt: str):
        return fn(model=cfg.auditor.model, system=system, prompt=prompt,
                  key_env=cfg.auditor.key_env, base_url=cfg.auditor.base_url,
                  allow_custom=bool(os.environ.get("CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT")))

    return complete


def _routing_path(cfg: Config) -> Path:
    return cfg.root / cfg.ledger_dir / ROUTING_LOG


def _record_routing(cfg: Config, routing, executed: str) -> Path:
    """Append and commit one routing decision without touching staged user work."""
    path = router_mod.record(_routing_path(cfg), routing, executed)
    try:
        relative = str(path.relative_to(cfg.root))
    except ValueError as exc:
        raise ConfigDenial(f"routing ledger escaped the project: {path}") from exc
    git("add", "--", relative, cwd=cfg.root)
    # A path-limited commit leaves anything the user had already staged alone.
    git("commit", "-q", "--only", "-m",
        f"route: {routing.lane} — {routing.utterance[:56]}", "--", relative,
        cwd=cfg.root)
    return path


def _context(cfg: Config) -> str:
    """What the router needs to judge a sentence: the rules and the loop's state."""
    bits = []
    const = cfg.root / cfg.constitution
    if const.is_file():
        rules = [ln for ln in const.read_text().splitlines() if ln.startswith("### ")]
        if rules:
            bits.append("CURRENT RULE IDS: " + ", ".join(r[4:].strip() for r in rules))
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    cycles = store.snapshot().get("cycles", {})
    if cycles:
        pending = [f"{cid[:8]}:{c['status']}" for cid, c in cycles.items()
                   if c["status"] in ("OPEN", "BLOCKED", "ESCALATED")]
        bits.append("OPEN CYCLES: " + (", ".join(pending) if pending else "none"))
    return "\n".join(bits)


def _confirm(question: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"  {question} [auto-confirmed]")
        return True
    if not sys.stdin.isatty():
        raise ConfigDenial(f"this needs your confirmation ({question}) but stdin is "
                           f"not a terminal; re-run in a terminal or pass --yes")
    return input(f"  {question} [Y/n] ").strip().lower() in ("", "y", "yes")


# --------------------------------------------------------------------- lanes
def lane_amendment(cfg: Config, routing, *, assume_yes: bool) -> str:
    const_path = cfg.root / cfg.constitution
    if not const_path.is_file():
        raise ConfigDenial(f"no Constitution at {const_path}; run `crossaudit init` first")
    current = const_path.read_text()
    change_set = const_mod.amend(current, routing.restated,
                                 complete=_auditor_complete(cfg))
    print(f"\n  Understood as: {change_set.get('intent', routing.restated)}")
    print("  Proposed change to the rules:\n")
    for c in change_set["changes"]:
        verb = {"add": "new", "modify": "changed", "remove": "removed"}[c["action"]]
        print(f"    [{verb}] {c['id']} ({c.get('severity', '?')}) — {c.get('title', '')}")
        if c.get("now"):
            print(f"           {c['now']}")
        print(f"           why: {c.get('why', '')}")
    print()
    if not _confirm("Commit this amendment?", assume_yes=assume_yes):
        return "declined by user"
    const_path.write_text(const_mod.apply_amendment(current, change_set))
    git("add", "--", cfg.constitution, cwd=cfg.root)
    git("commit", "-q", "-m",
        f"amend rules: {change_set.get('intent', routing.restated)[:72]}", cwd=cfg.root)
    sha = git("rev-parse", "HEAD", cwd=cfg.root)
    print(f"  Rules amended and committed ({sha[:12]}). It applies from the next "
          f"cycle onward; work already under audit is judged by the rules it "
          f"started under.")
    return f"amended at {sha[:12]}"


def lane_query(cfg: Config, routing) -> str:
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    cycles = store.snapshot().get("cycles", {})
    if not cycles:
        print("\n  Nothing has been audited yet.")
        return "answered: no cycles"
    print()
    for cid, c in sorted(cycles.items()):
        print(f"  {cid[:8]}  {c['status']:9s} round {c['round']}  "
              f"{c['active_sha'][:12]}")
    blocked = [c for c in cycles.values() if c["status"] == "BLOCKED"]
    esc = [c for c in cycles.values() if c["status"] == "ESCALATED"]
    if esc:
        print(f"\n  {len(esc)} escalation(s) waiting on you. Say what to do with "
              f"them, or run `crossaudit watch` to read the exchange.")
    elif blocked:
        print(f"\n  {len(blocked)} increment(s) blocked; fix and they re-audit.")
    return f"answered: {len(cycles)} cycles"


def lane_generator(cfg: Config, routing) -> str:
    """A change to the work goes to the generator, through the same loop `build`
    runs: write, commit, audit, and repeat on findings."""
    from .build import cmd_build

    print(f"\n  That is a change to the work: {routing.restated}")

    class _Args:
        words = routing.restated.split()

    try:
        code = cmd_build(_Args())
    except Denial as exc:
        print(f"  The generator could not run: {exc.reason}")
        print("  Set CROSSAUDIT_GENERATOR_MODEL and its key, or make the change "
              "yourself and run `crossaudit run`.")
        return f"generator unavailable: {exc.reason}"
    return f"built and audited (exit {code})"


def _latest_report(cfg: Config) -> tuple[str, str]:
    """(report text, cycle directory name) of the most recent audit."""
    ledger = cfg.root / cfg.ledger_dir
    reports = sorted(ledger.glob("*/report.md"), key=lambda p: p.stat().st_mtime)
    if not reports:
        raise ConfigDenial("nothing has been audited yet, so nothing can be disputed")
    return reports[-1].read_text(), reports[-1].parent.name


def lane_dispute(cfg: Config, routing, *, hint: str = "") -> str:
    """One contested finding, one trip back to the auditor, with grounds.

    The auditor rules on its own finding; the dispute buys a second reading, not
    a veto. A withdrawal is recorded, not applied retroactively: the report that
    was committed stays committed, and the ledger carries the correction beside
    it.
    """
    from .. import dispute as dis

    report, cycle_dir = _latest_report(cfg)
    findings = dis.parse_findings(report)
    finding = dis.select(findings, hint)
    log = cfg.root / cfg.ledger_dir / dis.DISPUTES_LOG
    if dis.already_disputed(log, cycle_dir, finding.key):
        print(f"\n  {finding.key} has already had its one reading. If you still "
              f"disagree, the lane is amendment: the rule, not the finding.")
        return f"refused: {finding.key} already disputed"

    artefact = cfg.root / finding.artifact
    artefact_text = artefact.read_text() if artefact.is_file() else "(artefact not found)"
    constitution = (cfg.root / cfg.constitution).read_text()

    print(f"\n  Disputing {finding.key}")
    print(f"    the finding: {finding.observation[:160]}")
    print(f"    your grounds: {routing.restated}")
    print("  Returning it to the auditor for one re-reading…")

    ruling = dis.adjudicate(finding, routing.restated, artefact_text,
                            dis.rule_text(constitution, finding.rule),
                            complete=_auditor_complete(cfg), cycle_id=cycle_dir)
    dis.record(log, ruling)
    git("add", "--", str((log).relative_to(cfg.root)), cwd=cfg.root)
    git("commit", "-q", "-m",
        f"dispute {finding.key}: {ruling.ruling.lower()}", cwd=cfg.root)

    if ruling.withdrawn:
        print(f"\n  WITHDRAWN — {ruling.reasoning}")
        print("  The finding is struck from the record's effect; the report that "
              "raised it stays, with the withdrawal recorded beside it.")
    else:
        print(f"\n  UPHELD — {ruling.reasoning}")
        print("  The finding stands. Fix the artefact, or if you think the rule "
              "itself is wrong, say so and it becomes an amendment.")
    return f"{finding.key} {ruling.ruling.lower()}"


def lane_resolve(cfg: Config, routing, *, assume_yes: bool) -> str:
    store = StateStore(cfg.root / cfg.state_dir / "state.json")
    cycles = store.snapshot().get("cycles", {})
    escalated = [cid for cid, c in cycles.items() if c["status"] == "ESCALATED"]
    if not escalated:
        print("\n  Nothing is escalated; there is nothing to rule on.")
        return "no escalation pending"
    if len(escalated) > 1:
        print(f"\n  {len(escalated)} escalations are open; name one:")
        for cid in escalated:
            print(f"    {cid}")
        return "ambiguous: multiple escalations"
    cid = escalated[0]
    print(f"\n  Escalation {cid[:8]} is waiting. You said: {routing.restated}")
    if not _confirm(f"Return {cid[:8]} to the loop for another audit?",
                    assume_yes=assume_yes):
        return "declined by user"
    store.resolve_escalation(cid, "reopen", routing.utterance)
    print(f"  Ruling recorded; {cid[:8]} is open again. Your reason is in the ledger.")
    return f"reopened {cid[:8]}"


def lane_project(cfg: Config, routing) -> str:
    print("\n  A project description sets up the rules, which `crossaudit init`")
    print("  already did here. To change the standards, say what should change")
    print("  and it becomes an amendment.")
    return "already initialised"


# ---------------------------------------------------------------------- verb
def cmd_talk(args) -> int:
    cfg = load()
    if not is_repo(cfg.root):
        raise ConfigDenial(f"{cfg.root} is not a git repository; the ledger is git")
    utterance = " ".join(args.words).strip()
    if not utterance:
        raise ConfigDenial("say something: `crossaudit talk \"...\"`")

    routing = router_mod.route(utterance, complete=_auditor_complete(cfg),
                               context=_context(cfg))
    print(f"\n  → {routing.lane} ({routing.confidence:.0%} sure) — {routing.reasoning}")

    if not routing.certain:
        # Fail-closed, in product form: guessing the direction of a change would
        # contaminate either the rulebook or the work.
        question = routing.clarify or ("Is this a change to the work, or to the "
                                       "standards it is judged by?")
        print(f"\n  Not confident enough to act. {question}")
        print("  Say it again with that settled, and it will go through.")
        _record_routing(cfg, routing, "asked for clarification")
        return 0

    lane_fns = {
        "amendment": lambda: lane_amendment(cfg, routing, assume_yes=args.yes),
        "query": lambda: lane_query(cfg, routing),
        "generator": lambda: lane_generator(cfg, routing),
        "dispute": lambda: lane_dispute(cfg, routing),
        "resolve": lambda: lane_resolve(cfg, routing, assume_yes=args.yes),
        "project": lambda: lane_project(cfg, routing),
    }
    try:
        executed = lane_fns[routing.lane]()
    except Denial as exc:
        _record_routing(cfg, routing, f"denied: {exc.reason}")
        raise
    _record_routing(cfg, routing, executed)
    return 0


def cmd_routing(args) -> int:
    """Open the box: every decision the router ever made."""
    cfg = load()
    rows = router_mod.history(_routing_path(cfg), limit=args.limit)
    if not rows:
        print("no routing decisions recorded yet")
        return 0
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"{'lane':<11}{'conf':>6}  utterance / what was done")
    print("-" * 76)
    for r in rows:
        print(f"{r['lane']:<11}{r['confidence']:>5.0%}  {r['utterance'][:58]}")
        print(f"{'':<17}  -> {r['executed']}")
    return 0

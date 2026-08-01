"""`crossaudit build` — the closed loop (DESIGN.md §8, a3).

The user states a task once. The generator writes, the work is committed, the
auditor judges it, and if it was blocked the findings go back to the generator
for another round — until PASS, or until the round budget hands it to a human.

What the user sees is a narration. What the ledger receives is unchanged: every
round is a commit, every verdict a report and a receipt, every escalation a
decision waiting for a person. The box is opaque to interact with and glass on
the inside.

Two things this verb refuses to do, both deliberate:

* **It never lifts a rule to make progress.** A blocked round is returned to the
  generator, never to the rulebook. Loosening a rule is an amendment, which is a
  human's lane and takes effect only between cycles.
* **It stops at the round budget.** Three failed rounds mean the loop cannot
  resolve this itself, which is exactly what I5 is for: escalate rather than
  spin.
"""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path

from .. import generator as gen_mod
from ..config import Config, heterogeneity, load
from ..controller import StateStore
from ..errors import EXIT_ESCALATED, EXIT_OK, ConfigDenial, Denial
from ..gitio import git, is_repo
from ..providers import get_provider
from ..providers.registry import NEEDS_KEY
from .main import cmd_run
from .talk import _routing_path

TASK_FILE = "TASK.md"


def _generator_complete(cfg: Config, allow_custom: bool):
    """A `complete(system, prompt)` bound to the generator role.

    The generator role needs its own credential; falling back to the auditor's
    would put one key behind both ends of a loop whose whole premise is that the
    ends are separate.
    """
    provider = os.environ.get("CROSSAUDIT_GENERATOR_PROVIDER") or (
        "anthropic" if (cfg.generator_vendor or "").lower() == "anthropic"
        else "openai_compat")
    model = os.environ.get("CROSSAUDIT_GENERATOR_MODEL", "")
    if not model:
        raise ConfigDenial(
            "the generator's model is not set: export CROSSAUDIT_GENERATOR_MODEL "
            "(and CROSSAUDIT_GENERATOR_PROVIDER if it is not the vendor default)")
    key_env = "CROSSAUDIT_GENERATOR_KEY"
    if NEEDS_KEY.get(provider, True) and not os.environ.get(key_env, "").strip():
        raise ConfigDenial(
            f"the generator has no key in ${key_env}. The auditor's key is not "
            f"reused: one credential behind both ends would collapse the "
            f"separation the loop depends on")
    base_url = os.environ.get("CROSSAUDIT_GENERATOR_BASE_URL") or None
    fn = get_provider(provider)

    def complete(*, system: str, prompt: str):
        return fn(model=model, system=system, prompt=prompt, key_env=key_env,
                  base_url=base_url, allow_custom=allow_custom)

    return complete


def _current_work(cfg: Config) -> dict[str, str]:
    """The work as it stands, read from the working tree inside the scope dirs."""
    out: dict[str, str] = {}
    for d in (cfg.scope_dirs or []):
        base = cfg.root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.is_symlink():
                try:
                    out[str(p.relative_to(cfg.root))] = p.read_text()
                except UnicodeDecodeError:
                    continue
    return out


def _last_report(cfg: Config) -> str:
    ledger = cfg.root / cfg.ledger_dir
    reports = sorted(ledger.glob("*/report.md"), key=lambda p: p.stat().st_mtime)
    return reports[-1].read_text() if reports else ""


class _Args:
    """The argument shape `cmd_run` expects, when the loop calls it rather than a user."""

    json = False
    sha = None
    yes = True
    allow_custom_endpoint = True


def cmd_build(args) -> int:
    cfg = load()
    if not is_repo(cfg.root):
        raise ConfigDenial(f"{cfg.root} is not a git repository; the ledger is git")
    if not cfg.scope_dirs:
        raise ConfigDenial(
            "scope.dirs is not set: the generator must be told where it may write, "
            "or it could rewrite the rules it is judged by")
    het_ok, why = heterogeneity(cfg)
    if not het_ok:
        raise ConfigDenial(why)

    task = " ".join(args.words).strip()
    task_path = cfg.root / TASK_FILE
    if not task:
        if not task_path.is_file():
            raise ConfigDenial('say what to build: crossaudit build "..."')
        task = task_path.read_text()
    else:
        # The task joins the ledger too: a reader asking "why does this exist"
        # should find the answer in the repository, not in someone's terminal.
        task_path.write_text(task + "\n")
        git("add", "--", TASK_FILE, cwd=cfg.root)
        git("commit", "-q", "-m", f"task: {task.splitlines()[0][:68]}", cwd=cfg.root)

    allow_custom = bool(os.environ.get("CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT"))
    complete = _generator_complete(cfg, allow_custom)
    constitution = (cfg.root / cfg.constitution).read_text()
    store = StateStore(cfg.root / cfg.state_dir / "state.json")

    print("\nCrossAudit — building under audit")
    print("=" * 60)
    print(f"  task     {task.splitlines()[0][:60]}")
    print(f"  rules    {cfg.constitution} ({constitution.count(chr(10) + '### ')} rules)")
    print(f"  writing  {', '.join(cfg.scope_dirs)}/")
    print(f"  rounds   up to {cfg.max_rounds}, then it goes to you")

    findings = ""
    for round_no in range(1, cfg.max_rounds + 1):
        print(f"\n  ── round {round_no} ─────────────────────────────────────")
        print("  generator  writing…", end="", flush=True)
        work = gen_mod.generate(task=task, constitution=constitution,
                                current=_current_work(cfg), complete=complete,
                                findings=findings, allowed_dirs=cfg.scope_dirs)
        written = gen_mod.apply(work, cfg.root)
        print(f"\r  generator  {len(written)} file(s): {', '.join(written[:3])}"
              + (" …" if len(written) > 3 else ""))
        if work.notes:
            print(f"             note: {work.notes[:100]}")

        if not git("status", "--porcelain", cwd=cfg.root, check=False).strip():
            print("  generator  produced no change; nothing further to audit")
            break
        git("add", "--", *cfg.scope_dirs, cwd=cfg.root)
        git("commit", "-q", "-m", f"{work.summary} (round {round_no})", cwd=cfg.root)

        print("  auditor    reviewing…", end="", flush=True)
        # The inner verb narrates for someone who invoked it directly. Here the
        # loop is doing the invoking, so its narration is captured and summarised:
        # a box that leaks its own internals is not a box. The full text is in
        # the ledger either way, which is where a curious reader should look.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cmd_run(_Args())
        inner = buffer.getvalue()
        cycles = store.snapshot().get("cycles", {})
        latest = max(cycles.values(), key=lambda c: c.get("round", 0), default={})
        status = latest.get("status", "?")

        if code == EXIT_OK:
            print("\r  auditor    passed             ")
            print(f"\n  Done in {round_no} round(s). The work passed audit and the "
                  f"ledger has the whole exchange.")
            print("  Read it:  crossaudit watch      Admit it:  crossaudit verify "
                  "<receipt> --admit")
            return EXIT_OK
        if status == "ESCALATED":
            print("\r  auditor    escalated          ")
            print(f"\n  Round {round_no} escalated: the loop cannot settle this itself.")
            print("  Say what should happen — `crossaudit talk \"...\"` — or read the "
                  "exchange with `crossaudit watch`.")
            return EXIT_ESCALATED
        findings = gen_mod.render_findings(_last_report(cfg))
        blocking = [ln.strip("- ").strip() for ln in inner.splitlines()
                    if ln.strip().startswith("- [")]
        print("\r  auditor    blocked            ")
        for line in blocking[:3]:
            print(f"             {line[:96]}")
        print("  loop       findings returned to the generator")

    print(f"\n  Round budget spent ({cfg.max_rounds}). It is yours now: "
          f"`crossaudit watch` to read the exchange.")
    return EXIT_ESCALATED

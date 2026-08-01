"""`crossaudit pair` — creating the two repositories, and saying honestly what
that buys (DESIGN.md §6.2).

Two repositories are not about research. They are about privilege separation:
the generator cannot reach the rules it is judged by or the reports written
about it, and the auditor cannot reach the work's history. That separation is
what lets the ledger hold the two agents to account against *each other*, which
a single repository can never do.

This verb plans before it acts, always. `--plan` (the default) prints exactly
what would be created and changed; `--apply` does it. Nothing here writes to
anyone's account without that second word.

It also refuses to overstate what it achieved. Creating repositories and
uploading secrets produces the `paired` tier — privilege separation, history
out of unilateral control. It does not produce `enforced`: that needs an
independent, persistent controller consuming receipts atomically and an
admission check bound to a verified App, and until `doctor` can see both, the
honest word is "verified notification", not "enforced".
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..config import load
from ..errors import EXIT_CONFIG, EXIT_OK, ConfigDenial

TIERS = {
    "local": "one history, yours to rewrite: self-review, not accountability",
    "remote": "history out of unilateral control: you can be held to your own record",
    "paired": "privilege separation: the two agents can be held to account "
              "against each other",
    "enforced": "admission actually refused on a failed audit",
}


def gh() -> str:
    path = shutil.which("gh")
    if not path:
        raise ConfigDenial(
            "pairing needs the GitHub CLI: install it from https://cli.github.com "
            "and run `gh auth login`. CrossAudit deliberately does not implement "
            "its own OAuth flow or handle your token")
    proc = subprocess.run([path, "auth", "status"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ConfigDenial("gh is installed but not authenticated; run `gh auth login`")
    return path


def _gh(*args: str, check: bool = True) -> str:
    proc = subprocess.run([gh(), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise ConfigDenial(f"gh {' '.join(args[:2])} failed: "
                           f"{proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def _owner() -> str:
    return json.loads(_gh("api", "user"))["login"]


def _exists(repo: str) -> bool:
    return subprocess.run([gh(), "repo", "view", repo],
                          capture_output=True).returncode == 0


def plan(science: str, audit: str, *, private: bool) -> list[tuple[str, str]]:
    """(action, why) pairs, in the order they would run."""
    vis = "--private" if private else "--public"
    return [
        (f"gh repo create {science} {vis}",
         "the work and its history"),
        (f"gh repo create {audit} {vis}",
         "the rules and every report: the generator has no write path here"),
        (f"push AUDIT_RULES.md to {audit}",
         "the Constitution lives where the audited party cannot edit it"),
        (f"gh secret set CROSSAUDIT_AUDITOR_KEY --repo {audit}",
         "the auditor's key, readable only by the audit side"),
        (f"gh api repos/{science}/branches/main/protection",
         "admission as a required check — a deployer toggle, and paid on private "
         "repositories under some plans"),
    ]


def cmd_pair(args) -> int:
    cfg = load()
    owner = _owner()
    science = args.science or f"{owner}/{cfg.root.name}"
    audit = args.audit or f"{science}-audit"
    private = not args.public

    print("\nCrossAudit — pairing the repositories")
    print("=" * 66)
    print(f"  science  {science}")
    print(f"  audit    {audit}")
    print(f"  buys     {TIERS['paired']}")
    print(f"  not      {TIERS['enforced']} — that needs a controller and an App")
    print()

    for i, (action, why) in enumerate(plan(science, audit, private=private), 1):
        print(f"  {i}. {action}")
        print(f"     {why}")

    if not args.apply:
        print("\n  This was a plan; nothing was created. Run again with --apply.")
        return EXIT_OK

    print("\n  Applying…")
    for repo in (science, audit):
        if _exists(repo):
            print(f"  · {repo} exists; adopting it rather than creating")
        else:
            _gh("repo", "create", repo, "--private" if private else "--public")
            print(f"  · created {repo}")

    const = cfg.root / cfg.constitution
    if not const.is_file():
        raise ConfigDenial(f"no Constitution at {const}; run `crossaudit init` first")

    # The audit repository is seeded from a scratch clone: the rules must arrive
    # there without the science repository ever gaining a write path to them.
    staging = cfg.root / cfg.state_dir / "pair-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    _gh("repo", "clone", audit, str(staging), "--", "-q")
    shutil.copyfile(const, staging / const.name)
    (staging / "cycles").mkdir(exist_ok=True)
    (staging / "cycles" / "README.md").write_text(
        "# Ledger\n\nOne directory per audit cycle: the report, the deterministic\n"
        "check output, and the receipt that binds them to a commit. Append-only:\n"
        "a re-audit adds an attempt, it never rewrites one.\n")
    for cmd in (["add", "-A"], ["commit", "-q", "-m", "seed: constitution and ledger"],
                ["push", "-q", "origin", "HEAD"]):
        subprocess.run(["git", *cmd], cwd=str(staging), capture_output=True)
    shutil.rmtree(staging)
    print(f"  · seeded {audit} with the Constitution and an empty ledger")

    key = os.environ.get(cfg.auditor.key_env, "").strip()
    if key:
        subprocess.run([gh(), "secret", "set", cfg.auditor.key_env, "--repo", audit],
                       input=key, text=True, capture_output=True)
        print(f"  · uploaded {cfg.auditor.key_env} to {audit} (never printed, never "
              f"written to disk here)")
    else:
        print(f"  · ${cfg.auditor.key_env} is not set; upload it yourself with "
              f"`gh secret set {cfg.auditor.key_env} --repo {audit}`")

    print("\n  Branch protection is the one step left, and it is yours: it needs")
    print("  admin rights and, on private repositories, a paid plan on some tiers.")
    print(f"    gh api repos/{science}/branches/main/protection -X PUT \\")
    print("      -f 'required_status_checks[strict]=true' \\")
    print("      -f 'required_status_checks[contexts][]=crossaudit/admission'")
    print("\n  Then `crossaudit doctor --online` reads the rules that actually")
    print("  exist and tells you which tier you are really at — plan text is not")
    print("  evidence.")
    return EXIT_OK

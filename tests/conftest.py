"""Fixtures for the delivery tests: a real git science repo and a live config.

Everything runs against the installed package in a temporary directory. No test
touches the developer's home, the repository's own state, or the network.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from crossaudit.config import load
from crossaudit.scaffold import read as read_template

GOOD_RESULTS = {
    "quantities": [
        {"name": "binding_energy", "value": -3.65, "unit": "kcal/mol",
         "source": "scripts/run_demo.py@a1b2c3d"},
        {"name": "distance", "value": 2.73, "unit": "angstrom",
         "source": "scripts/run_demo.py@a1b2c3d"},
    ],
    "convergence": {"converged": True, "achieved": 7.4e-07, "threshold": 1e-06},
}

BAD_RESULTS = {
    "quantities": [
        {"name": "binding_energy", "value": -3.65, "unit": "kcal/mol",
         "source": "legacy_fit.py@1692761"},
        {"name": "distance", "value": 2.73, "source": "scripts/run_demo.py@a1b2c3d"},
    ],
    "convergence": {"converged": False, "achieved": 7.4e-07, "threshold": 1e-06},
}

METADATA = "code_version: a1b2c3d\ninputs:\n  - scripts/run_demo.py@a1b2c3d\n"

CONFIG = """\
version: 1
science_repo: lab/science
constitution: AUDIT_RULES.md
max_rounds: 3
auditor:
  vendor: anthropic
  provider: replay
  model: claude-fable-5
  key_env: CROSSAUDIT_AUDITOR_KEY
generator:
  vendor: openai
isolation:
  minimum:
    parametric: true
    contextual: true
    permissive: false
ledger:
  dir: cycles
state:
  dir: .crossaudit
checks: [schema, units, convergence, provenance]
"""


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture()
def science(tmp_path: Path) -> Path:
    repo = tmp_path / "science"
    (repo / "experiments" / "demo").mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=repo.parent) if False else None
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    git("config", "user.email", "lab@example.invalid", cwd=repo)
    git("config", "user.name", "Lab", cwd=repo)
    (repo / "AUDIT_RULES.md").write_text(read_template("AUDIT_RULES.md"))
    (repo / "crossaudit.yml").write_text(CONFIG)
    (repo / ".gitignore").write_text(".crossaudit/\n")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "bootstrap", cwd=repo)
    return repo


def write_increment(repo: Path, results: dict, summary: str, message: str) -> str:
    d = repo / "experiments" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metadata.yml").write_text(METADATA)
    (d / "results.json").write_text(json.dumps(results, indent=1))
    (d / "SUMMARY.md").write_text(summary)
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", message, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture()
def cfg(science: Path):
    return load(science / "crossaudit.yml")


@pytest.fixture()
def transcripts(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "transcripts"
    d.mkdir()
    monkeypatch.setenv("CROSSAUDIT_REPLAY_DIR", str(d))
    return d


def record_reply(transcripts: Path, cfg, sha: str, reply: dict, scope: str = "experiments"):
    """Record what the auditor will answer for this exact prompt."""
    import subprocess as sp

    from crossaudit.auditor import prompt as pm
    from crossaudit.dcl import run_checks
    from crossaudit.gitio import materialise
    from crossaudit.providers import replay

    files, notes = materialise(cfg.root, sha, scope)
    dcl = run_checks(files, cfg.checks, notes).as_dict()
    const = (cfg.root / cfg.constitution).read_text()
    cc = sp.run(["git", "log", "-1", "--format=%H", "--", cfg.constitution],
                cwd=str(cfg.root), capture_output=True, text=True).stdout.strip()
    prompt, _bounded, _sha = pm.build(const, cc, dcl, files)
    return replay.record(transcripts, system=pm.SYSTEM, prompt=prompt,
                         text=json.dumps(reply))


PASS_REPLY = {"verdict": "PASS",
              "sections_applied": ["CA-DATA-001", "CA-METH-002"],
              "findings": []}

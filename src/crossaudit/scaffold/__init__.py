"""Templates `init` instantiates. The Constitution is a template here, never law."""
from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).parent / "templates"


def read(name: str) -> str:
    path = TEMPLATES / name
    if not path.is_file():
        raise FileNotFoundError(f"packaged template {name!r} is missing")
    return path.read_text()


CONFIG_TEMPLATE = """\
# crossaudit.yml — the one configuration file.
# Credentials are NOT here: each role names the environment variable that
# carries its key, and the value is read at call time.
version: 1

science_repo: {science_repo}
{audit_repo_line}
constitution: {constitution}
max_rounds: {max_rounds}

auditor:
  vendor: {auditor_vendor}
  provider: {auditor_provider}
  model: {auditor_model}
  key_env: CROSSAUDIT_AUDITOR_KEY
{base_url_line}
generator:
  # Declared so I1 (heterogeneity) can be asserted from configuration.
  vendor: {generator_vendor}
{generator_details}

isolation:
  # Refuse to admit a receipt whose isolation evidence is weaker than this.
  # permissive: true means the two roles' credentials were never both reachable
  # by one process — a single machine holding both keys cannot evidence it.
  minimum:
    parametric: true
    contextual: true
    permissive: {permissive_minimum}

state:
  dir: {state_dir}

scope:
  # The generator and the default deterministic check may only read/write here.
  dirs: [experiments]

checks: [schema, units, convergence, provenance]
"""


# --------------------------------------------------------------- repo shapes
# What each repository looks like the moment it is created, so a science repo
# reads as a lab notebook and an audit repo reads as a ledger, from commit one.

SCIENCE_TREE: dict[str, str] = {
    "experiments/README.md": """\
# experiments/

One directory per increment. An increment is the unit the auditor reads, so it
must stand alone:

    experiments/<date>-<slug>/
    ├── metadata.yml     code_version + declared inputs (what produced this?)
    ├── results.json     quantities, each with unit and source; convergence block
    └── SUMMARY.md       the claim, in prose that must agree with the data

`crossaudit run` audits the latest commit's increment against AUDIT_RULES.md.
The audit trail lands in cycles/ as paired report + receipt commits.
""",
    "experiments/TEMPLATE/metadata.yml": """\
# Copy this directory to experiments/<date>-<slug>/ and fill it in.
code_version: <git sha or tag of the code that produced the results>
inputs:
  - <script-or-data-path>@<revision>
""",
    "experiments/TEMPLATE/results.json": """\
{
  "quantities": [
    {"name": "<quantity>", "value": 0.0, "unit": "<unit>",
     "source": "<declared-input>@<revision>"}
  ],
  "convergence": {"converged": true, "achieved": 0.0, "threshold": 0.0}
}
""",
    "experiments/TEMPLATE/SUMMARY.md": """\
One paragraph: what was computed, and what it shows. The prose here is audited
against results.json — a sign or magnitude that disagrees is a BLOCKER.
""",
    "cycles/README.md": """\
# cycles/ — the audit ledger (append-only)

Written by `crossaudit`, never by hand. Each cycle directory holds the audit
report, the deterministic check output, and the receipt that binds them to one
science commit. History is the point: nothing here is ever rewritten.
""",
}

AUDIT_TREE: dict[str, str] = {
    "README.md": """\
# Audit repository

This repository is a ledger, not a workspace. It holds:

- `AUDIT_RULES.md` — the Constitution: versioned, human-authored rules the
  auditor cites by ID. Changes land only between cycles.
- `cycles/` — one append-only directory per audit cycle: report, deterministic
  check output, receipt.

The generating agent has no write access here; the auditing side has no write
access to the science repository. That mutual unwritability is the point.
""",
    "cycles/README.md": """\
# cycles/ — append-only

`<science-sha>-r<round>/report.md` + `checks.json` + `receipt.json`.
A receipt binds the science commit, every input hash, the Constitution's
commit, and the verifier's own identity. Verify one with:

    crossaudit verify <path>/receipt.json
""",
}


def write_tree(root, tree: "dict[str, str]", *, force: bool = False) -> list[str]:
    """Materialise a repo shape. Existing files are never overwritten."""
    written = []
    for rel, content in tree.items():
        dest = Path(root) / rel
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        written.append(rel)
    return written

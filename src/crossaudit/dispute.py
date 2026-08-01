"""The dispute channel: contesting one finding, once (I5's other half).

An auditor is fallible in both directions. A false-positive BLOCKER, silently
obeyed, degrades the work as surely as a missed defect does — so the protocol
gives the contested finding one trip back to the auditor, with grounds, and
that is all. One trip, because a dispute channel without a bound becomes the
oscillation it exists to prevent.

The asymmetry that makes this safe: the disputer states grounds, and the
auditor rules. Nothing here lets a dispute overturn a finding by itself; it
buys a second reading, and the second reading is the auditor's.

Two more things this module refuses:

* **The generator cannot dispute.** Grounds come from the principal, routed
  through the dispute lane. A generator arguing with its own audit is exactly
  the anchoring channel P2 exists to close.
* **A rule cannot be disputed, only a finding.** Disagreeing with the rule
  itself is an amendment, which is deliberate, dated, and effective only
  between cycles.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .constitution import parse_json_reply
from .errors import ConfigDenial, ProviderDenial

DISPUTES_LOG = "disputes.jsonl"
FINDING_LINE = re.compile(r"^### \[(BLOCKER|ADVISORY)\] (CA-[A-Z]+-\d+) — (.+)$", re.M)

ADJUDICATE_SYSTEM = """You are the Auditor, re-reading one of your own findings \
because the project's principal has contested it. You are not being asked to be \
agreeable; you are being asked to be right.

You will be given: the rule, your finding, the artefact it was raised against, \
and the grounds for the dispute.

Rule the finding UPHELD or WITHDRAWN:
- WITHDRAWN if the grounds show the finding rested on a misreading of the \
artefact, or that the rule does not in fact reach this case.
- UPHELD if the defect is real, even when the grounds are forcefully argued. \
Being persuaded by confidence rather than evidence is the failure mode you are \
here to avoid.
- If the grounds argue that the rule itself is wrong, UPHOLD and say so: rules \
change by amendment, not by dispute.

Reply with exactly one JSON object and nothing else:
{"ruling": "UPHELD"|"WITHDRAWN",
 "reasoning": "what in the grounds or the artefact decided it",
 "note_for_the_record": "one line the ledger should carry"}"""


@dataclass
class Finding:
    severity: str
    rule: str
    artifact: str
    observation: str

    @property
    def key(self) -> str:
        return f"{self.rule}@{self.artifact}"


@dataclass
class Ruling:
    finding_key: str
    rule: str
    artifact: str
    grounds: str
    ruling: str
    reasoning: str
    note: str
    cycle_id: str = ""
    t: int = 0

    @property
    def withdrawn(self) -> bool:
        return self.ruling == "WITHDRAWN"

    def as_dict(self) -> dict:
        return asdict(self)


def parse_findings(report: str) -> list[Finding]:
    """Findings as the report recorded them, in order."""
    out: list[Finding] = []
    matches = list(FINDING_LINE.finditer(report))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        body = report[start:end].strip()
        # The observation ends where the next section begins.
        body = body.split("\n## ")[0].strip()
        out.append(Finding(severity=m.group(1), rule=m.group(2),
                           artifact=m.group(3).strip(), observation=body))
    return out


def select(findings: list[Finding], hint: str) -> Finding:
    """Pick the finding a dispute is about. Ambiguity is refused, never guessed."""
    if not findings:
        raise ConfigDenial("that cycle's report records no findings to dispute")
    hint = hint.strip().upper()
    if hint:
        exact = [f for f in findings if f.rule.upper() == hint or f.key.upper() == hint]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise ConfigDenial(
                f"{hint} was raised against {len(exact)} artefacts; name one: "
                + ", ".join(f.key for f in exact))
    blockers = [f for f in findings if f.severity == "BLOCKER"]
    if len(blockers) == 1:
        return blockers[0]
    raise ConfigDenial(
        "name the finding to dispute by its rule id: "
        + ", ".join(f.key for f in (blockers or findings)))


def already_disputed(log: Path, cycle_id: str, key: str) -> bool:
    """One trip back, and only one. This is the bound that keeps a channel from
    becoming an argument."""
    for row in history(log):
        if row.get("cycle_id") == cycle_id and row.get("finding_key") == key:
            return True
    return False


def adjudicate(finding: Finding, grounds: str, artefact_text: str, rule_text: str,
               *, complete, cycle_id: str = "") -> Ruling:
    if not grounds.strip():
        raise ConfigDenial(
            "a dispute needs grounds: say what the auditor misread, and why")
    reply = complete(
        system=ADJUDICATE_SYSTEM,
        prompt=(f"THE RULE\n{rule_text.strip() or '(rule text not found)'}\n\n"
                f"YOUR FINDING\n[{finding.severity}] {finding.rule} — "
                f"{finding.artifact}\n{finding.observation}\n\n"
                f"THE ARTEFACT AS COMMITTED\n<<<ARTEFACT\n{artefact_text}\nARTEFACT\n\n"
                f"THE GROUNDS FOR DISPUTE\n{grounds.strip()}"))
    raw = parse_json_reply(reply.text)
    ruling = str(raw.get("ruling", "")).strip().upper()
    if ruling not in ("UPHELD", "WITHDRAWN"):
        raise ProviderDenial(f"adjudication returned an unusable ruling {ruling!r}")
    return Ruling(finding_key=finding.key, rule=finding.rule, artifact=finding.artifact,
                  grounds=grounds.strip(), ruling=ruling,
                  reasoning=str(raw.get("reasoning", "")).strip(),
                  note=str(raw.get("note_for_the_record", "")).strip(),
                  cycle_id=cycle_id, t=int(time.time()))


def record(log: Path, ruling: Ruling) -> Path:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as fh:
        fh.write(json.dumps(ruling.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return log


def history(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def rule_text(constitution: str, rule_id: str) -> str:
    m = re.search(rf"^### {re.escape(rule_id)}\n(.*?)(?=^### |\Z)",
                  constitution, re.M | re.S)
    return m.group(0).strip() if m else ""

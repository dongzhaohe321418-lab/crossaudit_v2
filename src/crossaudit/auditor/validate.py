"""Reply validation (I3): what an auditor must say for its word to count.

A reply that cites nothing, invents a rule, or passes an increment while
carrying a blocker is *invalid* — not a lenient PASS. Invalid escalates.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

RULE_HEADING = re.compile(r"^###\s+(CA-[A-Z]+-\d+)", re.M)
SEVERITIES = ("BLOCKER", "ADVISORY")
VERDICTS = ("PASS", "BLOCKED", "ESCALATE")


def known_rules(constitution: str) -> set[str]:
    """Rule IDs the Constitution actually defines.

    If the heading style ever drifts this returns fewer rules and every citation
    becomes unknown — loudly wrong rather than quietly permissive.
    """
    return set(RULE_HEADING.findall(constitution))


def parse_reply(text: str) -> tuple[dict | None, str | None]:
    """Extract the JSON object from a model reply. Prose around it is tolerated."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        return None, "reply contains no JSON object"
    try:
        return json.loads(stripped[start:end + 1]), None
    except json.JSONDecodeError as exc:
        return None, f"reply JSON is malformed: {exc}"


def validate_reply(reply: object, rules: Iterable[str]) -> str | None:
    """None if valid, else why it is not."""
    known = set(rules)
    if not isinstance(reply, dict):
        return "reply is not a JSON object"
    if reply.get("verdict") not in VERDICTS:
        return "missing/invalid verdict"
    applied = reply.get("sections_applied")
    if not isinstance(applied, list) or not applied:
        return "no sections_applied: report cites no rule coverage (CA-META-002)"
    unknown = [r for r in applied if r not in known]
    if unknown:
        return f"sections_applied cites rules not in the Constitution: {unknown}"
    findings = reply.get("findings")
    if not isinstance(findings, list):
        return "findings is not a list"
    for f in findings:
        if not isinstance(f, dict):
            return f"finding is not an object: {f!r}"
        if f.get("severity") not in SEVERITIES:
            return f"finding with invalid severity: {f.get('severity')!r}"
        if str(f.get("rule", "")) not in known:
            return f"finding cites a rule not in the Constitution: {f.get('rule')!r}"
        if not str(f.get("observation", "")).strip():
            return "finding carries no observation: a citation without evidence"
    blockers = [f for f in findings if f["severity"] == "BLOCKER"]
    if reply["verdict"] == "BLOCKED" and not blockers:
        return "verdict BLOCKED without any BLOCKER finding"
    if reply["verdict"] == "PASS" and blockers:
        return "verdict PASS while carrying a BLOCKER finding"
    return None

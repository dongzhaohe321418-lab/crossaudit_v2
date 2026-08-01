"""Distilling spoken requirements into a committed Constitution (P3).

The user says what the project is and what they are afraid of getting wrong.
This module turns that into numbered, severity-tagged rules, shows them, and —
only after a nod — writes them as a file that git versions and receipts cite.

Two properties the distillation must preserve:

* **Nothing is invented silently.** Every drafted rule carries the fragment of
  the user's own words it came from, so a reader can check the translation.
* **The draft is never law until committed.** Audits run against the committed
  file at a commit hash; a draft in memory is a proposal, and the difference is
  the whole of P3.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import ConfigDenial, ProviderDenial

RULE_ID = re.compile(r"^CA-[A-Z]{2,10}-\d{3}$")
SEVERITIES = ("BLOCKER", "ADVISORY")

DISTIL_SYSTEM = """You turn a person's description of their project into audit \
rules. You are not writing an essay; you are drafting law that another model \
will apply mechanically to committed files.

Rules of drafting:
- Each rule needs a stable ID (CA-<AREA>-<NNN>, area is 2-10 uppercase letters), \
a severity, and a criterion decidable by reading the artefacts. If a reviewer \
could argue either way about whether a rule was met, either sharpen it or make \
it ADVISORY.
- BLOCKER is for objective defects that must stop the work: internal \
contradiction, missing provenance, unsupported claim, declared-but-absent \
artefact. ADVISORY is for judgement: style, taste, scope, suggestions.
- Draft between 3 and 10 rules. Prefer few sharp rules to many vague ones.
- Every rule must quote the fragment of the user's own words it came from, in \
`from_user`. If a rule follows from the domain rather than from something the \
user said, put the empty string and say so in the criterion.
- Do not invent domain requirements the user did not imply. You are translating, \
not advising.

Reply with exactly one JSON object and nothing else:
{"project_summary": "one sentence, the project in the user's own terms",
 "domain": "short label, e.g. literature-review, web-app, contract-review",
 "rules": [{"id": "CA-DATA-001", "severity": "BLOCKER",
            "title": "short imperative title",
            "criterion": "what must hold, decidably",
            "from_user": "the fragment this came from"}]}"""

AMEND_SYSTEM = """You amend an existing rulebook from a person's instruction. \
You will be given the current rules and one sentence of intent.

Produce the smallest change that satisfies the intent:
- To tighten or add: a new rule, or a sharpened criterion on an existing one.
- To loosen: lower a BLOCKER to ADVISORY, or narrow its criterion. Never delete \
a rule silently; a removal must be stated as such with its reason.
- Keep every untouched rule byte-identical.

Reply with exactly one JSON object and nothing else:
{"intent": "what you understood the person to want",
 "changes": [{"action": "add"|"modify"|"remove", "id": "CA-...",
              "was": "prior criterion or empty", "now": "new criterion or empty",
              "severity": "BLOCKER"|"ADVISORY", "title": "...",
              "why": "one line, tied to what the person said"}]}"""


@dataclass
class Rule:
    id: str
    severity: str
    title: str
    criterion: str
    from_user: str = ""

    def validate(self) -> None:
        if not RULE_ID.match(self.id):
            raise ConfigDenial(f"rule id {self.id!r} is not of the form CA-AREA-NNN")
        if self.severity not in SEVERITIES:
            raise ConfigDenial(f"rule {self.id}: severity must be one of {SEVERITIES}")
        if not self.criterion.strip():
            raise ConfigDenial(f"rule {self.id}: a rule with no criterion is not a rule")

    def render(self) -> str:
        origin = (f"\n<!-- from the user: \"{self.from_user.strip()}\" -->"
                  if self.from_user.strip() else "")
        return (f"### {self.id}\n**{self.severity}.** {self.title.strip()}\n\n"
                f"{self.criterion.strip()}{origin}\n")


@dataclass
class Draft:
    project_summary: str
    domain: str
    rules: list[Rule]

    def validate(self) -> None:
        if not self.rules:
            raise ConfigDenial("a Constitution with no rules cannot audit anything")
        seen: set[str] = set()
        for r in self.rules:
            r.validate()
            if r.id in seen:
                raise ConfigDenial(f"duplicate rule id {r.id}")
            seen.add(r.id)
        if not any(r.severity == "BLOCKER" for r in self.rules):
            raise ConfigDenial(
                "every rule is ADVISORY, so nothing can ever gate: at least one "
                "BLOCKER is needed for the loop to have teeth")

    def render(self, project: str) -> str:
        head = [
            f"# Constitution — {project}",
            "",
            "Drafted from the project owner's own description and committed here.",
            "Every audit cites the commit that carried this file, so a rule change is",
            "dated and attributable, and takes effect only *between* cycles: no work is",
            "judged against a target that moved under it.",
            "",
            f"**Project.** {self.project_summary.strip()}",
            f"**Domain.** {self.domain.strip()}",
            "",
            "Severities are two. **BLOCKER** is an objective defect and gates the work.",
            "**ADVISORY** is judgement, is recorded, and never gates.",
            "",
            "---",
            "",
        ]
        body = "\n".join(r.render() for r in self.rules)
        tail = ("\n---\n\n<!-- Amend by talking to CrossAudit: `crossaudit amend "
                "\"from now on ...\"`. Amendments are drafted, shown, confirmed, and "
                "committed; they never take effect mid-cycle. -->\n")
        return "\n".join(head) + body + tail

    @staticmethod
    def from_json(raw: dict) -> "Draft":
        try:
            rules = [Rule(id=str(r["id"]).strip().upper(), severity=str(r["severity"]).strip().upper(),
                          title=str(r["title"]), criterion=str(r["criterion"]),
                          from_user=str(r.get("from_user", "")))
                     for r in raw["rules"]]
            d = Draft(project_summary=str(raw["project_summary"]),
                      domain=str(raw.get("domain", "unspecified")), rules=rules)
        except (KeyError, TypeError) as exc:
            raise ProviderDenial(f"the drafting model returned an unusable shape: {exc}") from exc
        d.validate()
        return d

    def as_dict(self) -> dict:
        return {"project_summary": self.project_summary, "domain": self.domain,
                "rules": [asdict(r) for r in self.rules]}


def parse_json_reply(text: str) -> dict:
    """Extract the single JSON object from a model reply, tolerating prose around it."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise ProviderDenial("the drafting model returned no JSON object")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderDenial(f"the drafting model returned malformed JSON: {exc}") from exc


def distil(description: str, *, complete) -> Draft:
    """Draft a Constitution from the user's description. `complete` is a provider."""
    if len(description.strip()) < 12:
        raise ConfigDenial(
            "that is too short to draft rules from — say what the project is and "
            "what you are most afraid of getting wrong")
    reply = complete(system=DISTIL_SYSTEM,
                     prompt=f"The project owner says:\n\n{description.strip()}")
    return Draft.from_json(parse_json_reply(reply.text))


def amend(current_rules: str, instruction: str, *, complete) -> dict:
    """Draft the smallest rulebook change satisfying the instruction."""
    if not instruction.strip():
        raise ConfigDenial("an amendment needs an instruction")
    reply = complete(
        system=AMEND_SYSTEM,
        prompt=f"CURRENT RULES\n<<<RULES\n{current_rules}\nRULES\n\n"
               f"THE PERSON SAYS:\n{instruction.strip()}")
    raw = parse_json_reply(reply.text)
    changes = raw.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ProviderDenial("the amendment produced no changes")
    for c in changes:
        if c.get("action") not in ("add", "modify", "remove"):
            raise ProviderDenial(f"unknown amendment action {c.get('action')!r}")
        if not RULE_ID.match(str(c.get("id", ""))):
            raise ProviderDenial(f"amendment names an invalid rule id {c.get('id')!r}")
    return raw


def apply_amendment(constitution: str, change_set: dict) -> str:
    """Apply drafted changes to the rulebook text, appending a dated amendment log.

    Rules are edited in place so the file stays readable, and every change is
    also appended to an amendment section, because a rulebook whose history is
    invisible is one nobody can be held to.
    """
    text = constitution
    for c in change_set["changes"]:
        rid, action = c["id"], c["action"]
        block = (f"### {rid}\n**{c.get('severity', 'BLOCKER')}.** {c.get('title', '').strip()}\n\n"
                 f"{c.get('now', '').strip()}\n")
        pattern = re.compile(rf"^### {re.escape(rid)}\n.*?(?=^### |\Z)", re.M | re.S)
        if action == "add" and not pattern.search(text):
            marker = "\n---\n\n<!-- Amend by talking"
            text = (text.replace(marker, "\n" + block + marker)
                    if marker in text else text + "\n" + block)
        elif action == "modify":
            text = pattern.sub(block + "\n", text) if pattern.search(text) else text + "\n" + block
        elif action == "remove":
            text = pattern.sub("", text)
    log = ["\n\n## Amendments\n"] if "## Amendments" not in text else []
    log.append(f"\n**{change_set.get('intent', 'amendment').strip()}**\n")
    for c in change_set["changes"]:
        log.append(f"- `{c['id']}` {c['action']}: {c.get('why', '').strip()}")
    return text + "\n".join(log) + "\n"


def write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path

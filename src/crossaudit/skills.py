"""Skills: user-supplied instructions that shape how the generator works.

A skill is a markdown file the project owner writes — a house style, a domain
convention, a checklist, a worked example. It is loaded into the generator's
prompt so the work comes out the way this project wants it, without anyone
having to say so again every round.

The line that makes this safe is worth stating plainly: **a skill changes how
the generator writes, never what it is allowed to write or who judges it.**
Concretely, and enforced here rather than merely asked for:

* **Skills never reach the auditor.** The auditor judges committed artefacts
  against the committed Constitution. A skill that could speak to the auditor
  would be an unversioned rule — the exact thing P3 exists to prevent, since it
  would let the standards move without a dated amendment anybody agreed to.
* **Skills cannot widen the generator's reach.** `scope.dirs` is read from
  configuration, and nothing in a skill file can add to it. A skill saying "also
  edit AUDIT_RULES.md" is a text file with an opinion; the path guard is what
  decides.
* **Skills are committed and hashed into the receipt.** They shape output, so
  they are part of how the work came to be, and I2 says that cannot live only
  in someone's directory. A round run under different skills is a different
  round, and the ledger says so.
* **A skill cannot impersonate the rules.** The prompt fences them apart and
  says which is which: rules bind, skills advise, and where they disagree the
  rules win.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigDenial

SKILLS_DIR = "skills"
MAX_SKILL_BYTES = 60_000
MAX_TOTAL_BYTES = 200_000
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True)
class Skill:
    name: str
    path: str
    body: str
    applies_to: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.body.encode()).hexdigest()

    def matches(self, paths: list[str]) -> bool:
        """A skill with no `applies_to` is always in force; otherwise it waits
        until the round actually touches something it is about."""
        if not self.applies_to:
            return True
        return any(p.startswith(pref) or pref in p for pref in self.applies_to
                   for p in paths)


def _parse(text: str, name: str, rel: str) -> Skill:
    applies: tuple[str, ...] = ()
    body = text
    m = FRONT_MATTER.match(text)
    if m:
        for line in m.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "applies_to":
                applies = tuple(v.strip() for v in value.split(",") if v.strip())
        body = text[m.end():]
    return Skill(name=name, path=rel, body=body.strip(), applies_to=applies)


def load(root: Path, directory: str = SKILLS_DIR) -> list[Skill]:
    """Read every skill in the project. Absent directory is not an error."""
    base = root / directory
    if not base.is_dir():
        return []
    out: list[Skill] = []
    total = 0
    for p in sorted(base.rglob("*.md")):
        if p.is_symlink():
            raise ConfigDenial(f"refusing a symlinked skill: {p.name}")
        data = p.read_bytes()
        if len(data) > MAX_SKILL_BYTES:
            raise ConfigDenial(
                f"skill {p.name} is {len(data)} bytes (limit {MAX_SKILL_BYTES}); a "
                f"skill is guidance, and one this long crowds out the work itself")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ConfigDenial(
                f"the skills total more than {MAX_TOTAL_BYTES} bytes; trim them, or "
                f"scope them with applies_to so each round loads only what it needs")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigDenial(f"skill {p.name} is not UTF-8: {exc}") from exc
        out.append(_parse(text, p.stem, str(p.relative_to(root))))
    return out


def select(skills: list[Skill], touched: list[str]) -> list[Skill]:
    return [s for s in skills if s.matches(touched)]


def render(skills: list[Skill]) -> str:
    """The generator-side block. Fenced and labelled so it cannot pass for law."""
    if not skills:
        return ""
    parts = [
        "HOUSE SKILLS — how this project wants the work done.",
        "These are the owner's guidance, not the rules you are judged by. Where a",
        "skill and a rule disagree, the rule wins and you should say so in notes.",
        "Nothing here widens where you may write.",
        "",
    ]
    for s in skills:
        scope = f" (applies to: {', '.join(s.applies_to)})" if s.applies_to else ""
        parts.append(f"--- skill: {s.name}{scope} ---\n{s.body}\n")
    return "<<<SKILLS\n" + "\n".join(parts) + "SKILLS"


def manifest(skills: list[Skill]) -> dict:
    """What the receipt records: which guidance shaped this round, and its hash."""
    return {s.path: s.digest for s in sorted(skills, key=lambda s: s.path)}


TEMPLATE = """\
---
applies_to: work/
---

# House style

Replace this with how you want the work done. A few things that belong here:

- conventions this project follows that a competent stranger would not guess
- the shape of a good output: sections, length, tone, what to lead with
- worked examples of the kind of thing you want more of
- steps to take before declaring a piece finished

What does not belong here: the standards your work is *judged* by. Those are the
Constitution, and they change by amendment so that a dated, agreed record exists
of what the bar was when something passed. A skill that tries to relax a rule
will be ignored by the auditor, which never sees this file.

`applies_to` above is optional: a comma-separated list of path prefixes. Without
it the skill is in force for every round; with it, only when the round touches
those paths.
"""

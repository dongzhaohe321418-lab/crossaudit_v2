"""Domain-neutral checks: what can be verified mechanically about any work.

The v1 pack assumed experiment data — units, convergence, provenance. Those are
excellent checks and wrong to demand of a contract review or a web app. This
pack asks only what holds for any project whose output is files:

    declared     every file the work declares as an input exists
    parseable    files whose extension promises a format actually parse as it
    internal     internal links and references point at something that exists
    complete     no placeholder left where content was promised

None of these needs a model, all of them fail loudly, and each one catches a
class of defect that models are unreliable at noticing precisely because it is
boring: a broken link, a stray TODO, a JSON file that stopped being JSON.

Where a domain pack exists, it adds to this. Where none does, this is what
stands between the model audit and nothing — and the honest consequence, stated
in DESIGN.md §5, is that I4's mechanical guarantee is thinner, not absent.
"""
from __future__ import annotations

import json
import re
from typing import Mapping

import yaml

from .framework import ADVISORY, BLOCKER, Finding, register

PLACEHOLDERS = re.compile(
    r"(?:^|\s)(TODO|TBD|FIXME|XXX|LOREM IPSUM|PLACEHOLDER|\[INSERT[^\]]*\]|"
    r"<[A-Z_]{3,}>|\.\.\.\s*$)", re.M)
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
TEXT_SUFFIXES = (".md", ".txt", ".rst", ".tex", ".py", ".js", ".ts", ".yml",
                 ".yaml", ".json", ".toml", ".csv", ".html", ".css", ".sh")


def _text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def check_parseable(files: Mapping[str, bytes]) -> list[Finding]:
    """A file whose name promises a format must keep the promise."""
    out: list[Finding] = []
    for path, data in files.items():
        text = _text(data)
        if text is None:
            continue
        try:
            if path.endswith(".json"):
                json.loads(text)
            elif path.endswith((".yml", ".yaml")):
                yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            out.append(Finding(BLOCKER, "CA-FILE-001", path,
                               f"declares itself {path.rsplit('.', 1)[-1]} but does "
                               f"not parse: {exc}"))
    return out


def check_declared(files: Mapping[str, bytes]) -> list[Finding]:
    """Anything the work declares as an input must exist in the audited scope.

    A declaration pointing at nothing is the cheapest kind of unfounded claim,
    and it is the one mechanical check that survives every domain.
    """
    out: list[Finding] = []
    for path, data in files.items():
        if not path.endswith((".yml", ".yaml")):
            continue
        text = _text(data)
        if text is None:
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            continue                                   # reported by check_parseable
        if not isinstance(doc, dict):
            continue
        for key in ("inputs", "sources", "requires", "depends_on"):
            for item in doc.get(key) or []:
                ref = str(item).split("@")[0].strip()
                if not ref or ref.startswith(("http://", "https://")):
                    continue
                if not any(p == ref or p.endswith("/" + ref) for p in files):
                    out.append(Finding(
                        BLOCKER, "CA-FILE-002", path,
                        f"{key} declares {ref!r}, which is not in the audited scope"))
    return out


def check_internal(files: Mapping[str, bytes]) -> list[Finding]:
    """Relative links between the work's own files must resolve."""
    out: list[Finding] = []
    known = set(files)
    for path, data in files.items():
        if not path.endswith((".md", ".rst")):
            continue
        text = _text(data)
        if text is None:
            continue
        base = path.rsplit("/", 1)[0] if "/" in path else ""
        for target in MD_LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = target if target.startswith("/") else (
                f"{base}/{target}" if base else target)
            resolved = re.sub(r"[^/]+/\.\./", "", resolved).lstrip("./")
            if resolved not in known and not any(p.endswith("/" + resolved)
                                                 for p in known):
                out.append(Finding(ADVISORY, "CA-FILE-003", path,
                                   f"link to {target!r} resolves to nothing in the "
                                   f"audited scope"))
    return out


def check_complete(files: Mapping[str, bytes]) -> list[Finding]:
    """No placeholder may survive into audited work."""
    out: list[Finding] = []
    for path, data in files.items():
        if not path.endswith(TEXT_SUFFIXES):
            continue
        text = _text(data)
        if text is None:
            continue
        for m in PLACEHOLDERS.finditer(text):
            line = text[:m.start()].count("\n") + 1
            out.append(Finding(BLOCKER, "CA-FILE-004", path,
                               f"line {line}: {m.group(1).strip()!r} left in place of "
                               f"content that was promised"))
            break                                      # one per file is enough
    return out


register("parseable", check_parseable)
register("declared", check_declared)
register("internal", check_internal)
register("complete", check_complete)

#: The pack `init` writes when the project is not obviously scientific.
NEUTRAL_PACK = ["parseable", "declared", "internal", "complete"]

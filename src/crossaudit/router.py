"""The router: deciding which lane a sentence belongs to (P1).

The user speaks as they normally would. This module decides whether that
sentence is about the work (generator), the standards (amendment), a contested
finding (dispute), a pending escalation (resolve), or a question (query).

Three properties, each of which is a pillar in DESIGN.md made executable:

* **The decision is a ledger entry, not a hidden judgement.** Every routing goes
  to `routing.jsonl` with the utterance, the lane, the confidence and what was
  executed. A router whose choices are invisible is a third unaudited agent.
* **Unsure means ask.** Below the confidence threshold the box briefly stops
  being a box and asks one clarifying question. Guessing the direction of a
  change contaminates either the rulebook or the work.
* **The router forwards the user, never the generator.** Nothing the generator
  says can reach the auditor through this path (P2).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .constitution import parse_json_reply
from .errors import ProviderDenial

LANES = ("project", "generator", "amendment", "dispute", "resolve", "query")
CONFIDENCE_FLOOR = 0.75

ROUTER_SYSTEM = """You sort one sentence from a project owner into exactly one \
lane of a supervision system. You are a switchboard, not an assistant: you do not \
answer the person, you decide where their words go.

The lanes:
- project: describing what the project is, or its goals, for the first time.
- generator: asking for the work itself to change (add, cut, rewrite, fix).
- amendment: asking for the audit standards to change (stricter, looser, a new \
thing to watch for). The tell is that it is about how work is judged, not about \
this particular piece of work.
- dispute: contesting a specific audit finding as wrong or unfair.
- resolve: ruling on something the loop escalated — letting it through, or \
abandoning it.
- query: asking about state. Answerable from records; changes nothing.

Judge intent, not vocabulary. "This section is too long" is generator: it asks \
for a change to the work. "Sections should never exceed a page" is amendment: it \
sets a standard for all future work. When a sentence carries both, choose the one \
that would be lost if you chose the other, and say so in your reasoning.

Confidence is your genuine probability that the lane is right. Below 0.75 the \
system will ask the person instead of acting, so a low number is useful, not a \
failure — use it whenever a sentence is genuinely ambiguous.

Reply with exactly one JSON object and nothing else:
{"lane": "...", "confidence": 0.0-1.0,
 "reasoning": "one sentence: what made this that lane",
 "restated": "the person's request as an instruction for that lane",
 "clarify": "if confidence is low, the single question to ask them; else empty"}"""


@dataclass
class Routing:
    utterance: str
    lane: str
    confidence: float
    reasoning: str
    restated: str
    clarify: str = ""
    executed: str = "pending"
    t: int = 0

    @property
    def certain(self) -> bool:
        return self.confidence >= CONFIDENCE_FLOOR

    def as_dict(self) -> dict:
        return asdict(self)


def route(utterance: str, *, complete, context: str = "") -> Routing:
    """Classify one utterance. The classification is data; the caller executes."""
    reply = complete(
        system=ROUTER_SYSTEM,
        prompt=(f"{context}\n\n" if context else "")
               + f"THE PERSON SAYS:\n{utterance.strip()}")
    raw = parse_json_reply(reply.text)
    lane = str(raw.get("lane", "")).strip().lower()
    if lane not in LANES:
        raise ProviderDenial(f"router returned an unknown lane {lane!r}")
    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    return Routing(utterance=utterance.strip(), lane=lane,
                   confidence=max(0.0, min(1.0, confidence)),
                   reasoning=str(raw.get("reasoning", "")).strip(),
                   restated=str(raw.get("restated", utterance)).strip(),
                   clarify=str(raw.get("clarify", "")).strip(),
                   t=int(time.time()))


def record(path: Path, routing: Routing, executed: str) -> Path:
    """Append the decision to the routing ledger. Called for every utterance,
    including the ones that were only clarified and never acted on."""
    routing.executed = executed
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(routing.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def history(path: Path, limit: int = 50) -> list[dict]:
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[-limit:]

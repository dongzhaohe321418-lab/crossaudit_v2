"""a4: the dispute channel, the domain-neutral checks, and the plugin gate.

Each of these is a place where the system could be talked into being weaker
than it claims, so most of these tests are refusals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from crossaudit import dispute as dis
from crossaudit.dcl import run_checks
from crossaudit.dcl.plugins import DCL_API_VERSION, load_allowed
from crossaudit.errors import ConfigDenial, ProviderDenial

REPORT = "\n".join([
    "# Audit Report — repo@abc123", "",
    "| verdict | **BLOCKED** |", "",
    "## Deterministic findings", "",
    "### [BLOCKER] CA-FILE-004 — work/intro.md",
    "line 3: 'TODO' left in place of content that was promised", "",
    "## Model findings", "",
    "### [BLOCKER] CA-TXT-001 — work/summary.md",
    "The summary states 0.052 while the data file records 0.044.", "",
    "### [ADVISORY] CA-STY-001 — work/summary.md",
    "Three sentences begin the same way.", "",
])


@dataclass
class Reply:
    text: str


def stub(payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)

    def complete(*, system: str, prompt: str):
        return Reply(text=body)

    return complete


# ------------------------------------------------------------------ disputes
def test_findings_are_read_back_out_of_the_committed_report():
    found = dis.parse_findings(REPORT)
    assert [f.rule for f in found] == ["CA-FILE-004", "CA-TXT-001", "CA-STY-001"]
    assert found[1].artifact == "work/summary.md"
    assert "0.052" in found[1].observation


def test_a_dispute_names_its_finding_or_is_refused():
    found = dis.parse_findings(REPORT)
    with pytest.raises(ConfigDenial, match="name the finding"):
        dis.select(found, "")                    # two blockers: ambiguous
    assert dis.select(found, "CA-TXT-001").rule == "CA-TXT-001"
    assert dis.select(found, "ca-txt-001").rule == "CA-TXT-001"


def test_a_lone_blocker_needs_no_naming():
    single = dis.parse_findings("\n".join([
        "### [BLOCKER] CA-X-001 — a.md", "something", "",
        "### [ADVISORY] CA-Y-001 — a.md", "style", ""]))
    assert dis.select(single, "").rule == "CA-X-001"


def test_grounds_are_mandatory():
    f = dis.parse_findings(REPORT)[1]
    with pytest.raises(ConfigDenial, match="needs grounds"):
        dis.adjudicate(f, "   ", "artefact", "rule", complete=stub({}))


def test_the_auditor_rules_and_a_withdrawal_is_recorded(tmp_path: Path):
    f = dis.parse_findings(REPORT)[1]
    ruling = dis.adjudicate(
        f, "the 0.052 figure is in a quotation, not our claim", "…", "rule text",
        complete=stub({"ruling": "WITHDRAWN", "reasoning": "the line is quoted",
                       "note_for_the_record": "quotation, not assertion"}),
        cycle_id="abc-r1")
    assert ruling.withdrawn
    log = tmp_path / "cycles" / dis.DISPUTES_LOG
    dis.record(log, ruling)
    rows = dis.history(log)
    assert rows[0]["ruling"] == "WITHDRAWN" and rows[0]["cycle_id"] == "abc-r1"
    # The grounds are kept verbatim: a reader must be able to judge the judging.
    assert "quotation" in rows[0]["grounds"]


def test_an_upheld_finding_stands():
    f = dis.parse_findings(REPORT)[1]
    ruling = dis.adjudicate(f, "I disagree, it reads fine", "…", "rule",
                            complete=stub({"ruling": "UPHELD",
                                           "reasoning": "the contradiction is real",
                                           "note_for_the_record": "stands"}))
    assert not ruling.withdrawn


def test_an_unusable_ruling_denies_rather_than_defaulting_either_way():
    f = dis.parse_findings(REPORT)[1]
    with pytest.raises(ProviderDenial, match="unusable ruling"):
        dis.adjudicate(f, "grounds", "…", "rule",
                       complete=stub({"ruling": "MAYBE", "reasoning": ""}))


def test_one_finding_gets_one_reading(tmp_path: Path):
    """The bound that stops a dispute channel becoming an argument."""
    log = tmp_path / "cycles" / dis.DISPUTES_LOG
    f = dis.parse_findings(REPORT)[1]
    assert not dis.already_disputed(log, "abc-r1", f.key)
    dis.record(log, dis.Ruling(finding_key=f.key, rule=f.rule, artifact=f.artifact,
                               grounds="g", ruling="UPHELD", reasoning="r", note="n",
                               cycle_id="abc-r1"))
    assert dis.already_disputed(log, "abc-r1", f.key)
    # A different cycle is a different finding, even under the same rule.
    assert not dis.already_disputed(log, "def-r1", f.key)


def test_rule_text_is_pulled_from_the_constitution_for_the_re_reading():
    const = ("### CA-TXT-001\n**BLOCKER.** Prose matches data\n\nNo sentence "
             "contradicts its data file.\n\n### CA-OTHER-001\n**ADVISORY.** x\n")
    assert "Prose matches data" in dis.rule_text(const, "CA-TXT-001")
    assert "CA-OTHER" not in dis.rule_text(const, "CA-TXT-001")


# ------------------------------------------------------- domain-neutral pack
NEUTRAL = ["parseable", "declared", "internal", "complete"]


def test_a_json_file_that_stopped_being_json_is_caught():
    r = run_checks({"work/data.json": b"{not json,}"}, NEUTRAL)
    assert r.hard_failures == 1 and r.findings[0].rule == "CA-FILE-001"


def test_a_declaration_pointing_at_nothing_is_caught():
    files = {"work/meta.yml": b"inputs:\n  - sources/missing.md\n"}
    r = run_checks(files, NEUTRAL)
    assert any(f.rule == "CA-FILE-002" for f in r.findings)


def test_a_declaration_that_resolves_is_not_flagged():
    files = {"work/meta.yml": b"inputs:\n  - sources/there.md@rev1\n",
             "sources/there.md": b"content"}
    assert run_checks(files, NEUTRAL).hard_failures == 0


def test_a_placeholder_left_in_the_work_is_a_blocker():
    r = run_checks({"work/intro.md": b"# Intro\n\nTODO: write this\n"}, NEUTRAL)
    assert any(f.rule == "CA-FILE-004" for f in r.findings)


def test_a_broken_internal_link_is_advisory_not_blocking():
    files = {"work/a.md": b"see [the other](b.md)\n"}
    r = run_checks(files, NEUTRAL)
    assert r.hard_failures == 0
    assert any(f.rule == "CA-FILE-003" for f in r.findings)


def test_the_neutral_pack_says_nothing_about_units_or_convergence():
    """It must not smuggle science assumptions back in: this file would fail the
    v1 pack and must pass the neutral one."""
    files = {"work/notes.md": b"A contract review, no numbers at all.\n"}
    assert run_checks(files, NEUTRAL).hard_failures == 0


# -------------------------------------------------------------- plugin gate
def test_plugins_are_not_discovered_only_allowed():
    assert load_allowed(None) == [] and load_allowed([]) == []


def test_an_unnamed_pack_is_never_loaded_even_if_installed(monkeypatch):
    loaded = []

    class FakeEP:
        name = "evil"

        def load(self):
            loaded.append("evil")
            return object()

    monkeypatch.setattr("importlib.metadata.entry_points", lambda **k: [FakeEP()])
    load_allowed(["something-else"]) if False else None
    with pytest.raises(ConfigDenial, match="not installed"):
        load_allowed(["something-else"])
    assert loaded == []                     # discovery never ran it


def test_a_pack_declaring_the_wrong_api_version_is_refused(monkeypatch):
    class Pack:
        DCL_API_VERSION = DCL_API_VERSION + 1

        @staticmethod
        def register_checks():
            raise AssertionError("must not be called")

    class EP:
        name = "domain"

        def load(self):
            return Pack

    monkeypatch.setattr("importlib.metadata.entry_points", lambda **k: [EP()])
    with pytest.raises(ConfigDenial, match="refusing rather than guessing"):
        load_allowed(["domain"])


def test_a_pack_without_register_checks_is_refused(monkeypatch):
    class EP:
        name = "domain"

        def load(self):
            return type("P", (), {"DCL_API_VERSION": DCL_API_VERSION})

    monkeypatch.setattr("importlib.metadata.entry_points", lambda **k: [EP()])
    with pytest.raises(ConfigDenial, match="no register_checks"):
        load_allowed(["domain"])

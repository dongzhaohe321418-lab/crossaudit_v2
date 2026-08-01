"""Tests for the generator half of the loop.

The model is stubbed; what is tested is the boundary around it. A generator
inside a supervision system is exactly the component you must not trust by
default, so most of these are refusals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from crossaudit import generator as gen
from crossaudit.errors import ConfigDenial, ProviderDenial


@dataclass
class Reply:
    text: str


def stub(payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)

    def complete(*, system: str, prompt: str):
        return Reply(text=body)

    return complete


def work_payload(path="work/a.md", content="hello", **kw):
    return {"summary": "wrote a section",
            "files": [{"path": path, "content": content}], "notes": "", **kw}


ALLOWED = ["work"]


def test_a_round_returns_whole_files():
    w = gen.generate(task="write a section", constitution="rules", current={},
                     complete=stub(work_payload()), allowed_dirs=ALLOWED)
    assert w.files == {"work/a.md": "hello"} and w.summary == "wrote a section"


@pytest.mark.parametrize("bad", [
    "/etc/passwd",                       # absolute
    "../outside.md",                     # traversal
    "work/../../escape.md",              # traversal through the allowed dir
    ".git/config",                       # hidden
    "AUDIT_RULES.md",                    # the rules it is judged by
    "crossaudit.yml",                    # the configuration
    "cycles/forged/receipt.json",        # the ledger
])
def test_the_generator_cannot_write_outside_its_working_directories(bad):
    with pytest.raises(ProviderDenial):
        gen.generate(task="t", constitution="r", current={},
                     complete=stub(work_payload(path=bad)), allowed_dirs=ALLOWED)


def test_an_empty_round_is_refused():
    with pytest.raises(ProviderDenial, match="no files"):
        gen.generate(task="t", constitution="r", current={},
                     complete=stub({"summary": "s", "files": []}), allowed_dirs=ALLOWED)


def test_an_oversized_file_is_refused():
    huge = "x" * (gen.MAX_FILE_BYTES + 1)
    with pytest.raises(ProviderDenial, match="size bound"):
        gen.generate(task="t", constitution="r", current={},
                     complete=stub(work_payload(content=huge)), allowed_dirs=ALLOWED)


def test_a_round_that_rewrites_the_world_is_refused():
    many = {"summary": "s", "files": [{"path": f"work/{i}.md", "content": "x"}
                                      for i in range(gen.MAX_FILES_PER_ROUND + 1)]}
    with pytest.raises(ProviderDenial, match="should be an increment"):
        gen.generate(task="t", constitution="r", current={}, complete=stub(many),
                     allowed_dirs=ALLOWED)


def test_prose_instead_of_json_denies_rather_than_writing_nothing():
    with pytest.raises(ProviderDenial):
        gen.generate(task="t", constitution="r", current={},
                     complete=stub("Sure! I'll get started on that."),
                     allowed_dirs=ALLOWED)


def test_an_empty_task_is_refused():
    with pytest.raises(ConfigDenial, match="needs a task"):
        gen.generate(task="   ", constitution="r", current={},
                     complete=stub(work_payload()), allowed_dirs=ALLOWED)


def test_the_prompt_carries_rules_and_findings_but_never_the_auditor_s_report_headers():
    prompt = gen.build_prompt(task="write it", constitution="### CA-X-001\nbe exact",
                              current={"work/a.md": "old"}, findings="[BLOCKER] fix this",
                              allowed_dirs=ALLOWED)
    assert "### CA-X-001" in prompt          # it must know what it is judged by
    assert "[BLOCKER] fix this" in prompt    # and what was wrong last time
    assert "work/a.md" in prompt and "old" in prompt
    assert "may write only inside: work/" in prompt


def test_findings_are_extracted_without_the_report_s_provenance():
    report = "\n".join([
        "# Audit Report — repo@abc123", "", "| | |", "|---|---|",
        "| verdict | **BLOCKED** |", "| auditor | `openai:gpt` |", "",
        "## Deterministic findings", "",
        "### [BLOCKER] CA-DATA-001 — results.json",
        "quantities[1] has no unit", "",
    ])
    out = gen.render_findings(report)
    assert "CA-DATA-001" in out and "no unit" in out
    # The generator has no business knowing which vendor judged it, or the sha.
    assert "openai:gpt" not in out and "abc123" not in out


def test_apply_writes_only_what_was_returned(tmp_path: Path):
    w = gen.Work(summary="s", files={"work/deep/a.md": "one", "work/b.md": "two"})
    written = gen.apply(w, tmp_path)
    assert written == ["work/b.md", "work/deep/a.md"]
    assert (tmp_path / "work/deep/a.md").read_text() == "one"
    assert not (tmp_path / "AUDIT_RULES.md").exists()
